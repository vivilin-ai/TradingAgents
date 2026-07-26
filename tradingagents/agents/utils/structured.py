"""Shared helpers for invoking the decision-making agents with structured output.

The Portfolio Manager, Trader, and Research Manager all produce a typed
Pydantic instance via ``with_structured_output(Schema)``, so their ratings come
from a schema enum rather than from prose that has to be interpreted.

**Structured output is mandatory by default.** These agents issue investment
recommendations: a decision whose rating had to be inferred from free text can
contradict its own reasoning, and silently substituting prose for a validated
decision hides that from the user. So a structured call is retried a bounded
number of times and then raises, failing the run loudly instead of improvising.

Setting ``require_structured_output`` to False restores the old lenient
behaviour (prose plus explicit format instructions) for providers that cannot
do structured output at all; every such degradation is logged as a warning.
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


class StructuredOutputUnavailable(RuntimeError):
    """The model could not return a validated decision.

    Raised instead of quietly producing prose, so a failed decision surfaces as
    a failed run rather than as advice the pipeline invented a rating for.
    """


def _require_structured() -> bool:
    """Whether structured output is mandatory (default: yes)."""
    try:
        from tradingagents.dataflows.config import get_config

        return bool(get_config().get("require_structured_output", True))
    except Exception:  # config not initialised (e.g. isolated unit test)
        return True


def bind_structured(llm: Any, schema: type[T], agent_name: str) -> Optional[Any]:
    """Return ``llm.with_structured_output(schema)``.

    Raises :class:`StructuredOutputUnavailable` when the provider cannot do
    structured output at all, so the misconfiguration is reported up front
    rather than silently turning every decision into unvalidated prose.
    Returns ``None`` only when the requirement has been explicitly waived.
    """
    try:
        return llm.with_structured_output(schema)
    except (NotImplementedError, AttributeError) as exc:
        if _require_structured():
            raise StructuredOutputUnavailable(
                f"{agent_name}: this model does not support structured output "
                f"({exc}). Refusing to generate an investment decision as "
                "unvalidated free text. Use a model that supports structured "
                "output, or set require_structured_output=False to allow it."
            ) from exc
        logger.warning(
            "%s: provider does not support with_structured_output (%s); "
            "falling back to free-text generation because "
            "require_structured_output is disabled",
            agent_name, exc,
        )
        return None


def invoke_structured(
    structured_llm: Optional[Any],
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
    schema: Optional[type[BaseModel]] = None,
    max_attempts: int = 3,
) -> str:
    """Run the structured call and render the validated result to markdown.

    A structured call can fail transiently (truncated or malformed JSON), so it
    is retried up to ``max_attempts`` times with the identical prompt. If every
    attempt fails, :class:`StructuredOutputUnavailable` is raised — the run is
    reported as failed rather than answered with improvised prose.

    ``prompt`` is whatever the underlying LLM accepts: a string, or a list of
    messages for chat models that take that shape.
    """
    if structured_llm is not None:
        last_error: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            try:
                result = structured_llm.invoke(prompt)
                if result is None:
                    raise ValueError("model returned no structured result")
                return render(result)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "%s: structured output attempt %d/%d failed: %s",
                    agent_name, attempt, max_attempts, exc,
                )
        if _require_structured():
            raise StructuredOutputUnavailable(
                f"{agent_name}: structured output failed {max_attempts} times "
                f"({last_error}). Refusing to fall back to unvalidated free "
                "text for an investment decision."
            ) from last_error
    elif _require_structured():
        raise StructuredOutputUnavailable(
            f"{agent_name}: no structured-output binding is available."
        )

    logger.warning(
        "%s: emitting an unvalidated free-text decision because "
        "require_structured_output is disabled", agent_name,
    )
    if schema is not None:
        prompt = _append_instructions(prompt, build_format_instructions(schema))
    response = plain_llm.invoke(prompt)
    return response.content
