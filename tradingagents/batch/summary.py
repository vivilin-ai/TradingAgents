"""Weekly summary document generator.

Produces a ``summary.md`` with two parts:
1. A deterministic table (always present): ticker, rating, one-line thesis,
   main risk, key event.
2. An optional LLM-generated narrative: cross-ticker themes, divergences,
   and industry observations (controlled by ``weekly_summary_narrative``).
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

# Rating emoji mapping
_RATING_EMOJI = {
    "buy": "🟢",
    "overweight": "🔵",
    "hold": "⚪",
    "underweight": "🟡",
    "sell": "🔴",
}


def _rating_emoji(rating: str) -> str:
    return _RATING_EMOJI.get(rating.lower(), "⚪")


def _first_sentence(text: str) -> str:
    """Extract the first meaningful sentence from a block of text."""
    if not text:
        return "—"
    # Strip markdown headers/bold and grab first sentence
    clean = re.sub(r"#{1,6}\s*", "", text)
    clean = re.sub(r"\*+", "", clean)
    clean = clean.strip()
    m = re.search(r"[^.!?]+[.!?]", clean)
    if m:
        sentence = m.group(0).strip()
        return sentence[:200] + ("…" if len(sentence) > 200 else "")
    return clean[:200] + ("…" if len(clean) > 200 else "")


def _extract_key_event(news_report: str) -> str:
    """Pull the first notable event mentioned in the news report."""
    if not news_report:
        return "—"
    for line in news_report.splitlines():
        line = line.strip("- •*# \t")
        if len(line) > 20:
            return line[:150] + ("…" if len(line) > 150 else "")
    return "—"


def _extract_main_risk(risk_state: dict) -> str:
    """Pull the first sentence from the conservative analyst's history."""
    conservative = (risk_state or {}).get("conservative_history", "")
    return _first_sentence(conservative)


def build_table(results: list[dict[str, Any]]) -> str:
    """Build the deterministic summary table from batch results."""
    header = (
        "| Ticker | Rating | Thesis | Main Risk | Key Event |\n"
        "|--------|--------|--------|-----------|-----------|"
    )
    rows = []
    for r in results:
        if r.get("error"):
            rows.append(
                f"| {r['ticker']} | ❌ Error | {r['error'][:80]} | — | — |"
            )
            continue

        state = r.get("final_state") or {}
        rating = r.get("rating", "Hold")
        emoji = _rating_emoji(rating)

        # Thesis: first sentence of research manager decision
        debate = state.get("investment_debate_state") or {}
        thesis = _first_sentence(debate.get("judge_decision", ""))

        # Risk: first sentence from conservative analyst
        risk = _extract_main_risk(state.get("risk_debate_state"))

        # Key event: first bullet from news report
        key_event = _extract_key_event(state.get("news_report", ""))

        rows.append(
            f"| {r['ticker']} | {emoji} {rating} | {thesis} | {risk} | {key_event} |"
        )

    return header + "\n" + "\n".join(rows)


def _build_narrative_prompt(results: list[dict[str, Any]], trade_date: str) -> str:
    """Build the prompt for the LLM cross-ticker narrative."""
    summaries = []
    for r in results:
        if r.get("error"):
            summaries.append(f"- {r['ticker']}: ERROR — {r['error'][:120]}")
            continue
        state = r.get("final_state") or {}
        debate = state.get("investment_debate_state") or {}
        pm_decision = state.get("final_trade_decision", "")
        summaries.append(
            f"- {r['ticker']} ({r.get('rating', 'Hold')}): "
            f"{_first_sentence(pm_decision)}"
        )

    bullets = "\n".join(summaries)
    return (
        f"You are a senior portfolio strategist reviewing a weekly batch analysis "
        f"run on {trade_date}. Here are the decisions for each ticker:\n\n"
        f"{bullets}\n\n"
        "Write a concise 3–5 paragraph narrative (plain prose, no bullet lists) "
        "covering:\n"
        "1. Overarching macro or sector themes visible across tickers.\n"
        "2. Notable divergences or contradictions between bullish and bearish signals.\n"
        "3. Two or three key observations a portfolio manager should act on this week.\n"
        "Keep each paragraph to 3–4 sentences. Do not repeat the table data verbatim."
    )


def generate_narrative(
    results: list[dict[str, Any]],
    trade_date: str,
    llm: "BaseChatModel",
) -> str:
    """Call the LLM to produce a cross-ticker narrative."""
    try:
        prompt = _build_narrative_prompt(results, trade_date)
        response = llm.invoke(prompt)
        content = getattr(response, "content", str(response))
        return str(content).strip()
    except Exception as exc:
        logger.warning("Narrative generation failed: %s", exc)
        return f"*(Narrative generation failed: {exc})*"


def generate_summary(
    results: list[dict[str, Any]],
    trade_date: str,
    iso_week: str,
    narrative: bool = True,
    llm: Optional["BaseChatModel"] = None,
) -> str:
    """Produce the full ``summary.md`` content.

    Args:
        results:    List of dicts from ``BatchRunner.run()``.
        trade_date: The analysis date string (YYYY-MM-DD).
        iso_week:   ISO week label, e.g. ``"2026-W22"``.
        narrative:  Include LLM cross-ticker narrative when True.
        llm:        Language model to use for narrative (required when
                    ``narrative=True``).
    """
    completed = [r for r in results if not r.get("error")]
    errors = [r for r in results if r.get("error")]

    rating_counts: dict[str, int] = {}
    for r in completed:
        rating_counts[r.get("rating", "Hold")] = (
            rating_counts.get(r.get("rating", "Hold"), 0) + 1
        )

    rating_summary = " / ".join(
        f"{cnt} {rating}" for rating, cnt in rating_counts.items()
    )

    lines = [
        f"# Weekly Analysis — {iso_week}",
        f"",
        f"**Date:** {trade_date}  ",
        f"**Tickers analysed:** {len(results)} total, "
        f"{len(completed)} completed, {len(errors)} failed  ",
        f"**Ratings:** {rating_summary or '—'}",
        f"",
        f"## Decision Table",
        f"",
        build_table(results),
    ]

    if errors:
        lines += [
            "",
            "## Errors",
            "",
            "| Ticker | Error |",
            "|--------|-------|",
        ]
        for r in errors:
            lines.append(f"| {r['ticker']} | {r['error'][:200]} |")

    if narrative:
        if llm is None:
            lines += [
                "",
                "## Cross-Ticker Narrative",
                "",
                "*(Narrative skipped: no LLM provided.)*",
            ]
        else:
            lines += [
                "",
                "## Cross-Ticker Narrative",
                "",
                generate_narrative(results, trade_date, llm),
            ]

    return "\n".join(lines)
