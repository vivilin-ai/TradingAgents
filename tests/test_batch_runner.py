"""Unit tests for BatchRunner — mocks TradingAgentsGraph so no LLM calls are made."""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from tradingagents.batch.runner import BatchRunner, _latest_trading_day, _output_dir
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
            "history": "", "current_response": "", "count": 1,
        },
        "trader_investment_plan": "Buy 100 shares.",
        "risk_debate_state": {
            "aggressive_history": "Aggressive: full position.",
            "conservative_history": "Conservative: half position.",
            "neutral_history": "Neutral: standard allocation.",
            "judge_decision": "**Rating**: Overweight\nApproved.",
            "history": "", "count": 1,
        },
        "investment_plan": "Overweight NVDA.",
        "final_trade_decision": "**Rating**: Overweight\nBuy NVDA with half position.",
    }


# ── _latest_trading_day ───────────────────────────────────────────────────────

def test_latest_trading_day_weekday():
    monday = datetime.date(2026, 5, 25)
    assert _latest_trading_day(monday) == monday


def test_latest_trading_day_weekend():
    sunday = datetime.date(2026, 5, 24)
    assert _latest_trading_day(sunday).weekday() < 5


# ── _output_dir ───────────────────────────────────────────────────────────────

def test_output_dir_manual_single(tmp_path):
    cfg = DEFAULT_CONFIG.copy()
    cfg["reports_root"] = str(tmp_path)
    p = _output_dir(cfg, "manual", "2026-05-26", ticker="NVDA")
    assert p == tmp_path / "manual" / "2026-05-26_NVDA"


def test_output_dir_batch(tmp_path):
    cfg = DEFAULT_CONFIG.copy()
    cfg["reports_root"] = str(tmp_path)
    p = _output_dir(cfg, "batch", "2026-05-26")
    assert p == tmp_path / "batch" / "2026-05-26"


def test_output_dir_scheduled(tmp_path):
    cfg = DEFAULT_CONFIG.copy()
    cfg["reports_root"] = str(tmp_path)
    p = _output_dir(cfg, "scheduled", "2026-05-26", task_name="daily_nvda")
    assert p == tmp_path / "scheduled" / "daily_nvda" / "2026-05-26"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_config(tmp_path):
    cfg = DEFAULT_CONFIG.copy()
    cfg["watchlist_path"] = str(tmp_path / "watchlist.yaml")
    cfg["reports_root"] = str(tmp_path / "reports")
    return cfg


@pytest.fixture()
def watchlist_with_two_tickers(tmp_config):
    from tradingagents.batch.watchlist import add_tickers
    add_tickers(tmp_config["watchlist_path"], ["NVDA", "AAPL"])
    return tmp_config


# ── run_single ────────────────────────────────────────────────────────────────

def test_run_single_creates_report(tmp_config):
    state = _make_state("NVDA")
    with patch("tradingagents.batch.runner.TradingAgentsGraph") as MockGraph:
        MockGraph.return_value.propagate.return_value = (state, "Overweight")
        runner = BatchRunner(config=tmp_config)
        result = runner.run_single("NVDA", trade_date="2026-05-26")

    assert result["ticker"] == "NVDA"
    assert result["rating"] == "Overweight"
    assert result["error"] is None
    assert Path(result["report_path"]).exists()


def test_run_single_error_isolation(tmp_config):
    with patch("tradingagents.batch.runner.TradingAgentsGraph") as MockGraph:
        MockGraph.return_value.propagate.side_effect = RuntimeError("boom")
        runner = BatchRunner(config=tmp_config)
        result = runner.run_single("NVDA", trade_date="2026-05-26")

    assert result["error"] is not None
    assert "boom" in result["error"]


def test_run_single_calls_on_complete(tmp_config):
    state = _make_state("NVDA")
    completed = []
    with patch("tradingagents.batch.runner.TradingAgentsGraph") as MockGraph:
        MockGraph.return_value.propagate.return_value = (state, "Buy")
        runner = BatchRunner(config=tmp_config)
        runner.run_single("NVDA", trade_date="2026-05-26", on_complete=completed.append)

    assert len(completed) == 1
    assert completed[0]["ticker"] == "NVDA"


# ── run_batch ─────────────────────────────────────────────────────────────────

def test_run_batch_creates_summary(watchlist_with_two_tickers):
    cfg = watchlist_with_two_tickers
    with patch("tradingagents.batch.runner.TradingAgentsGraph") as MockGraph:
        MockGraph.return_value.propagate.side_effect = [
            (_make_state("NVDA"), "Overweight"),
            (_make_state("AAPL"), "Hold"),
        ]
        runner = BatchRunner(config=cfg)
        results, summary_path = runner.run_batch(trade_date="2026-05-26", narrative=False)

    assert summary_path.exists()
    content = summary_path.read_text(encoding="utf-8")
    assert "NVDA" in content
    assert "AAPL" in content


def test_run_batch_writes_individual_reports(watchlist_with_two_tickers):
    cfg = watchlist_with_two_tickers
    with patch("tradingagents.batch.runner.TradingAgentsGraph") as MockGraph:
        MockGraph.return_value.propagate.side_effect = [
            (_make_state("NVDA"), "Overweight"),
            (_make_state("AAPL"), "Hold"),
        ]
        runner = BatchRunner(config=cfg)
        results, summary_path = runner.run_batch(trade_date="2026-05-26", narrative=False)

    week_dir = summary_path.parent
    assert (week_dir / "NVDA.md").exists()
    assert (week_dir / "AAPL.md").exists()


def test_run_batch_isolates_failures(watchlist_with_two_tickers):
    cfg = watchlist_with_two_tickers
    with patch("tradingagents.batch.runner.TradingAgentsGraph") as MockGraph:
        MockGraph.return_value.propagate.side_effect = [
            RuntimeError("API error"),
            (_make_state("AAPL"), "Hold"),
        ]
        runner = BatchRunner(config=cfg)
        results, summary_path = runner.run_batch(trade_date="2026-05-26", narrative=False)

    assert len(results) == 2
    assert results[0]["error"] is not None
    assert results[1]["error"] is None
    assert (summary_path.parent / "errors.md").exists()


def test_run_batch_empty_watchlist(tmp_config):
    runner = BatchRunner(config=tmp_config)
    results, summary_path = runner.run_batch(trade_date="2026-05-26", narrative=False)
    assert results == []
    assert summary_path.exists()


def test_run_batch_explicit_tickers(tmp_config):
    state = _make_state("MSFT")
    with patch("tradingagents.batch.runner.TradingAgentsGraph") as MockGraph:
        MockGraph.return_value.propagate.return_value = (state, "Buy")
        runner = BatchRunner(config=tmp_config)
        results, _ = runner.run_batch(tickers=["MSFT"], trade_date="2026-05-26", narrative=False)

    assert len(results) == 1
    assert results[0]["ticker"] == "MSFT"
