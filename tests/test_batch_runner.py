"""Unit tests for BatchRunner — mocks TradingAgentsGraph so no LLM calls are made."""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.batch.runner import BatchRunner, _iso_week, _latest_trading_day
from tradingagents.default_config import DEFAULT_CONFIG


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_state(ticker: str = "NVDA") -> dict:
    return {
        "company_of_interest": ticker,
        "trade_date": "2026-05-26",
        "market_report": "Market looks bullish.",
        "sentiment_report": "Positive sentiment.",
        "news_report": "- Earnings beat expectations.",
        "fundamentals_report": "Strong balance sheet.",
        "investment_debate_state": {
            "bull_history": "Bull case: strong momentum.",
            "bear_history": "Bear case: valuation risk.",
            "judge_decision": "Overweight. The bull case is more compelling.",
            "history": "",
            "current_response": "",
            "count": 1,
        },
        "trader_investment_plan": "Buy 100 shares.",
        "risk_debate_state": {
            "aggressive_history": "Aggressive: full position.",
            "conservative_history": "Conservative: half position due to macro risks.",
            "neutral_history": "Neutral: standard allocation.",
            "judge_decision": "**Rating**: Overweight\nApproved with half position.",
            "history": "",
            "count": 1,
        },
        "investment_plan": "Overweight NVDA.",
        "final_trade_decision": "**Rating**: Overweight\nBuy NVDA with half position.",
    }


# ── _iso_week ─────────────────────────────────────────────────────────────────

def test_iso_week():
    d = datetime.date(2026, 5, 26)  # Monday of W22
    assert _iso_week(d) == "2026-W22"


def test_latest_trading_day_weekday():
    monday = datetime.date(2026, 5, 25)
    assert _latest_trading_day(monday) == monday


def test_latest_trading_day_weekend():
    sunday = datetime.date(2026, 5, 24)
    assert _latest_trading_day(sunday).weekday() < 5


# ── BatchRunner.run ───────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_config(tmp_path):
    cfg = DEFAULT_CONFIG.copy()
    cfg["watchlist_path"] = str(tmp_path / "watchlist.yaml")
    cfg["weekly_reports_dir"] = str(tmp_path / "reports" / "weekly")
    cfg["notifier"] = "none"
    return cfg


@pytest.fixture()
def watchlist_with_two_tickers(tmp_config):
    from tradingagents.batch.watchlist import add_tickers
    add_tickers(tmp_config["watchlist_path"], ["NVDA", "AAPL"])
    return tmp_config


def test_run_creates_summary(watchlist_with_two_tickers):
    cfg = watchlist_with_two_tickers
    state_nvda = _make_state("NVDA")
    state_aapl = _make_state("AAPL")

    with patch("tradingagents.batch.runner.TradingAgentsGraph") as MockGraph:
        instance = MockGraph.return_value
        instance.propagate.side_effect = [
            (state_nvda, "Overweight"),
            (state_aapl, "Hold"),
        ]

        runner = BatchRunner(config=cfg)
        summary_path = runner.run(trade_date="2026-05-26", narrative=False, notify=False)

    assert summary_path.exists()
    content = summary_path.read_text(encoding="utf-8")
    assert "NVDA" in content
    assert "AAPL" in content
    assert "Overweight" in content
    assert "Hold" in content


def test_run_writes_individual_reports(watchlist_with_two_tickers):
    cfg = watchlist_with_two_tickers
    state = _make_state("NVDA")

    with patch("tradingagents.batch.runner.TradingAgentsGraph") as MockGraph:
        MockGraph.return_value.propagate.side_effect = [
            (state, "Overweight"),
            (_make_state("AAPL"), "Hold"),
        ]
        runner = BatchRunner(config=cfg)
        summary_path = runner.run(trade_date="2026-05-26", narrative=False, notify=False)

    week_dir = summary_path.parent
    assert (week_dir / "NVDA.md").exists()
    assert (week_dir / "AAPL.md").exists()


def test_run_isolates_failures(watchlist_with_two_tickers):
    """A failure on one ticker must not abort the batch."""
    cfg = watchlist_with_two_tickers
    state = _make_state("AAPL")

    with patch("tradingagents.batch.runner.TradingAgentsGraph") as MockGraph:
        MockGraph.return_value.propagate.side_effect = [
            RuntimeError("API error"),
            (state, "Hold"),
        ]
        runner = BatchRunner(config=cfg)
        summary_path = runner.run(trade_date="2026-05-26", narrative=False, notify=False)

    content = summary_path.read_text(encoding="utf-8")
    assert "AAPL" in content
    assert "Error" in content or "ERROR" in content
    assert (summary_path.parent / "errors.md").exists()


def test_empty_watchlist_returns_summary(tmp_config):
    runner = BatchRunner(config=tmp_config)
    summary_path = runner.run(trade_date="2026-05-26", narrative=False, notify=False)
    # Returns a path even though nothing was run
    assert isinstance(summary_path, Path)
