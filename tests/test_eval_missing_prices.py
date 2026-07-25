"""Regression tests: a ticker with no price data must not crash the pipeline.

An invalid or delisted symbol in the watchlist (e.g. "MARVELL" instead of
"MRVL") used to raise KeyError inside the portfolio simulation and take the
whole weekly evaluation down with it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingagents.eval import portfolio_sim
from tradingagents.eval.evaluator import WeeklyEvaluator
from tradingagents.eval.ledger import DecisionLedger
from tradingagents.eval.prices import make_fake_fetcher

WEIGHT_MAP = {"Buy": 1.0, "Overweight": 0.7, "Hold": None, "Underweight": 0.3, "Sell": 0.0}


def frame(start: str, days: int, base: float, daily: float) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=days)
    px = base * (1 + daily) ** np.arange(days)
    return pd.DataFrame({"Open": px, "Close": px}, index=idx)


@pytest.fixture()
def config(tmp_path):
    return {
        "decision_ledger_path": str(tmp_path / "decisions.jsonl"),
        "memory_log_path": str(tmp_path / "trading_memory.md"),
        "lessons_path": str(tmp_path / "lessons.md"),
        "calibration_path": str(tmp_path / "calibration.md"),
        "eval_state_path": str(tmp_path / "eval_state.json"),
        "reports_root": str(tmp_path / "reports"),
        "eval_horizons": [2],
        "eval_benchmark": "SPY",
        "eval_cost_bps": 0,
        "calibration_min_samples": 2,
    }


def test_simulate_skips_ticker_without_prices():
    fetcher = make_fake_fetcher({
        "NVDA": frame("2026-06-01", 20, 100.0, 0.01),
        "SPY": frame("2026-06-01", 20, 500.0, 0.0),
    })
    entries = [
        {"ticker": "NVDA", "trade_date": "2026-06-01", "rating": "Buy", "outcomes": {}},
        # No price data for this one at all.
        {"ticker": "MARVELL", "trade_date": "2026-06-01", "rating": "Buy", "outcomes": {}},
    ]
    result = portfolio_sim.simulate(
        entries, WEIGHT_MAP, fetcher, cost_bps=0.0, as_of="2026-06-26",
    )
    assert result is not None
    # Capacity still splits across both tickers, so only half the NAV is
    # invested — the unavailable ticker's slot stays in cash rather than
    # levering up NVDA.
    px = frame("2026-06-01", 20, 100.0, 0.01)
    stock_gain = float(px["Close"].iloc[-1] / px["Open"].iloc[1]) - 1
    assert result["total_return"] == pytest.approx(stock_gain / 2, rel=1e-9)


def test_simulate_returns_none_when_no_ticker_has_prices():
    fetcher = make_fake_fetcher({"SPY": frame("2026-06-01", 20, 500.0, 0.0)})
    entries = [{"ticker": "MARVELL", "trade_date": "2026-06-01", "rating": "Buy", "outcomes": {}}]
    assert portfolio_sim.simulate(entries, WEIGHT_MAP, fetcher, as_of="2026-06-26") is None


def test_weekly_run_survives_unresolvable_ticker(config):
    ledger = DecisionLedger(config)
    ledger.record_decision("NVDA", "2026-06-01", "Buy", 100.0)
    ledger.record_decision("MARVELL", "2026-06-01", "Buy", 50.0)

    fetcher = make_fake_fetcher({
        "NVDA": frame("2026-06-01", 20, 100.0, 0.01),
        "SPY": frame("2026-06-01", 20, 500.0, 0.0),
    })
    result = WeeklyEvaluator(config=config, llm=None, fetcher=fetcher).run(as_of="2026-06-26")

    # NVDA settles, MARVELL stays pending, simulation still produced numbers.
    assert [s["ticker"] for s in result["settlements"]] == ["NVDA"]
    assert [e["ticker"] for e in ledger.pending_entries()] == ["MARVELL"]
    assert result["sim_summary"] is not None
    assert result["report_path"] is not None
