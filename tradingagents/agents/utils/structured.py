"""Shared helpers for invoking an agent with structured output and a graceful fallback.

The Portfolio Manager, Trader, and Research Manager all follow the same
canonical pattern:

1. At agent creation, wrap the LLM with ``with_structured_output(Schema)``
   so the model returns a typed Pydantic instance. If the provider does
   not support structured output (rare; mostly older Ollama models), the
   wrap is skipped and the agent uses free-text generation instead.
2. At invocation, run the structured call and render the result back to
   markdown. If the structured call itself fails for any reason
   (malformed JSON from a weak model, transient provider issue), fall
   back to a plain ``llm.invoke`` so the pipeline never blocks.

Centralising the pattern here keeps the agent factories small and ensures
all three agents log the same warnings when fallback fires.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Callable, Optional, TypeVar, get_args

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def build_format_instructions(schema: type[BaseModel]) -> str:
    """Render a schema as explicit markdown formatting rules.

    The schema's field descriptions *are* the output instructions when
    structured output is active. On the free-text fallback those instructions
    vanish, so the model returns unlabelled prose — and a decision with no
    ``**Rating**:`` line has to be guessed at by the heuristic parser, which
    is how a bearish write-up ends up tagged Hold. Restating the shape keeps
    the fallback's output parseable.
    """
    lines = []
    for name, field in schema.model_fields.items():
        label = " ".join(word.capitalize() for word in name.split("_"))
        annotation = field.annotation
        base = annotation
        args = [a for a in get_args(annotation) if a is not type(None)]
        if args:
            base = args[0]
        if isinstance(base, type) and issubclass(base, Enum):
            choices = " / ".join(member.value for member in base)
            lines.append(f"**{label}**: exactly one of {choices}")
        elif field.is_required():
            lines.append(f"**{label}**: <your text>")
        else:
            lines.append(f"**{label}**: <your text, or omit this line>")
    return (
        "Structure your answer in markdown using exactly these labels, "
        "each starting its own line:\n" + "\n".join(lines)
    )


def build_json_instructions(schema: type[BaseModel]) -> str:
    """Render a schema as a JSON contract for providers limited to JSON mode.

    ``method="json_mode"`` only sets ``response_format={"type":"json_object"}``;
    unlike tool calling it does not transmit the schema, so the shape has to be
    stated in the prompt or the model returns prose and parsing fails.
    """
    fields = []
    for name, field in schema.model_fields.items():
        annotation = field.annotation
        base = annotation
        args = [a for a in get_args(annotation) if a is not type(None)]
        if args:
            base = args[0]
        if isinstance(base, type) and issubclass(base, Enum):
            allowed = ", ".join(f'"{m.value}"' for m in base)
            fields.append(f'  "{name}": one of {allowed}')
        elif base is float or base is int:
            fields.append(f'  "{name}": number{"" if field.is_required() else " or null"}')
        else:
            fields.append(f'  "{name}": string{"" if field.is_required() else " or null"}')
    return (
        "Reply with a single JSON object and nothing else — no prose, no code "
        "fences. It must have exactly these keys:\n{\n"
        + ",\n".join(fields)
        + "\n}"
    )


def ensure_rating_line(text: str, llm: Any, agent_name: str) -> str:
    """Guarantee the decision text opens with an explicit ``**Rating**:`` line.

    Free-text output has no enforced shape, so the rating had to be inferred
    from prose — and an inferred rating can contradict the reasoning it was
    read from. Rather than guess, ask the model to name the rating it just
    argued for and record that answer explicitly, so every stored decision
    carries an authoritative label.

    Returns ``text`` unchanged when it already carries a label, or when the
    repair call fails (the caller logs and the heuristic still applies).
    """
    from tradingagents.agents.utils.rating import RATINGS_5_TIER, analyze_rating

    if not text or not text.strip():
        return text
    if analyze_rating(text).method == "label":
        return text

    choices = " / ".join(RATINGS_5_TIER)
    ask = (
        "Below is a trading decision write-up. Reply with exactly one word — "
        f"the rating it argues for, chosen from: {choices}. "
        "No punctuation, no explanation.\n\n" + text
    )
    try:
        answer = llm.invoke(ask).content or ""
    except Exception as exc:
        logger.warning("%s: rating repair call failed (%s)", agent_name, exc)
        return text

    word = answer.strip().strip("*.:：，,。").split()[:1]
    canonical = {r.lower(): r for r in RATINGS_5_TIER}
    rating = canonical.get(word[0].lower()) if word else None
    if rating is None:
        logger.warning(
            "%s: rating repair returned %r, which is not a 5-tier rating",
            agent_name, answer[:80],
        )
        return text

    logger.info("%s: recovered explicit rating %s for an unlabelled decision",
                agent_name, rating)
    return f"**Rating**: {rating}\n\n{text}"


def _append_instructions(prompt: Any, instructions: str) -> Any:
    """Attach instructions to whatever prompt shape the caller passed."""
    if isinstance(prompt, str):
        return f"{prompt}\n\n{instructions}"
    if isinstance(prompt, list):
        return list(prompt) + [("human", instructions)]
    return prompt


def bind_structured(llm: Any, schema: type[T], agent_name: str) -> Optional[Any]:
    """Return ``llm.with_structured_output(schema)`` or ``None`` if unsupported.

    Logs a warning when the binding fails so the user understands the agent
    will use free-text generation for every call instead of one-shot fallback.
    """
    try:
        return llm.with_structured_output(schema)
    except (NotImplementedError, AttributeError) as exc:
        logger.info(
            "%s: provider does not support with_structured_output (%s); "
            "falling back to free-text generation",
            agent_name, exc,
        )
        return None


def invoke_structured_or_freetext(
    structured_llm: Optional[Any],
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
    schema: Optional[type[BaseModel]] = None,
) -> str:
    """Run the structured call and render to markdown; fall back to free-text on any failure.

    ``prompt`` is whatever the underlying LLM accepts (a string for chat
    invocations, a list of message dicts for chat models that take that
    shape). The same value is forwarded to the free-text path so the
    fallback sees the same input the structured call did.
    """
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(prompt)
            if result is None:
                raise ValueError("LLM returned None for structured output")
            return render(result)
        except Exception as exc:
            logger.warning(
                "%s: structured-output invocation failed (%s); result was %s. retrying once as free text",
                agent_name, exc, type(result) if 'result' in locals() else 'N/A'
            )

    if schema is not None:
        prompt = _append_instructions(prompt, build_format_instructions(schema))
    response = plain_llm.invoke(prompt)
    return response.content
