"""Unit tests for the weekly summary generator."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tradingagents.batch.summary import (
    build_table,
    generate_summary,
    _first_sentence,
    _extract_key_event,
)


def _ok_result(ticker: str, rating: str = "Buy") -> dict:
    return {
        "ticker": ticker,
        "date": "2026-05-26",
        "rating": rating,
        "final_state": {
            "investment_debate_state": {
                "judge_decision": f"{ticker} looks strong. Further upside expected.",
            },
            "risk_debate_state": {
                "conservative_history": "Position size risk is a concern here.",
            },
            "news_report": f"- {ticker} reported record earnings this quarter.",
            "final_trade_decision": f"**Rating**: {rating}\nApproved.",
        },
        "error": None,
    }


def _err_result(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "date": "2026-05-26",
        "rating": "Hold",
        "final_state": None,
        "error": "Connection timeout",
    }


# ── _first_sentence ───────────────────────────────────────────────────────────

def test_first_sentence_plain():
    assert _first_sentence("Hello world. Second sentence.") == "Hello world."


def test_first_sentence_empty():
    assert _first_sentence("") == "—"


def test_first_sentence_strips_markdown():
    result = _first_sentence("## Header\n**Bold** text. More text.")
    # The ## and ** markers should be stripped
    assert "##" not in result
    assert "**" not in result


# ── _extract_key_event ────────────────────────────────────────────────────────

def test_extract_key_event():
    news = "- Earnings beat expectations.\n- CEO resigned."
    event = _extract_key_event(news)
    assert "Earnings" in event


def test_extract_key_event_empty():
    assert _extract_key_event("") == "—"


# ── build_table ───────────────────────────────────────────────────────────────

def test_build_table_contains_tickers():
    results = [_ok_result("NVDA", "Buy"), _ok_result("AAPL", "Hold")]
    table = build_table(results)
    assert "NVDA" in table
    assert "AAPL" in table


def test_build_table_error_row():
    results = [_err_result("TSLA")]
    table = build_table(results)
    assert "TSLA" in table
    assert "Error" in table or "ERROR" in table


def test_build_table_ratings():
    results = [_ok_result("NVDA", "Buy"), _ok_result("MSFT", "Sell")]
    table = build_table(results)
    assert "Buy" in table
    assert "Sell" in table


# ── generate_summary ──────────────────────────────────────────────────────────

def test_generate_summary_no_narrative():
    results = [_ok_result("NVDA", "Overweight"), _ok_result("AAPL", "Hold")]
    md = generate_summary(results, "2026-05-26", "2026-W22", narrative=False)
    assert "# Weekly Analysis" in md
    assert "NVDA" in md
    assert "AAPL" in md
    assert "Cross-Ticker Narrative" not in md


def test_generate_summary_with_narrative():
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="Macro theme: tech outperforms.")

    results = [_ok_result("NVDA"), _ok_result("AAPL")]
    md = generate_summary(results, "2026-05-26", "2026-W22", narrative=True, llm=llm)
    assert "Cross-Ticker Narrative" in md
    assert "Macro theme" in md


def test_generate_summary_narrative_no_llm():
    results = [_ok_result("NVDA")]
    md = generate_summary(results, "2026-05-26", "2026-W22", narrative=True, llm=None)
    assert "Cross-Ticker Narrative" in md
    assert "skipped" in md.lower() or "no llm" in md.lower()


def test_generate_summary_errors_section():
    results = [_ok_result("NVDA"), _err_result("TSLA")]
    md = generate_summary(results, "2026-05-26", "2026-W22", narrative=False)
    assert "Errors" in md
    assert "TSLA" in md


def test_generate_summary_rating_counts():
    results = [
        _ok_result("NVDA", "Buy"),
        _ok_result("AAPL", "Buy"),
        _ok_result("MSFT", "Hold"),
    ]
    md = generate_summary(results, "2026-05-26", "2026-W22", narrative=False)
    # Should mention 2 Buy and 1 Hold somewhere in the header
    assert "Buy" in md
    assert "Hold" in md
