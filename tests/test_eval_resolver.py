"""Tests for multi-horizon settlement (P1) with synthetic prices."""

import numpy as np
import pandas as pd
import pytest

from tradingagents.eval.ledger import DecisionLedger
from tradingagents.eval.prices import make_fake_fetcher
from tradingagents.eval.resolver import OutcomeResolver


def make_frame(start: str, days: int, open_base: float, daily_gain: float) -> pd.DataFrame:
    """Business-day frame; Close = Open * (1 + daily_gain), Open grows daily."""
    idx = pd.bdate_range(start, periods=days)
    opens = open_base * (1 + daily_gain) ** np.arange(days)
    closes = opens * (1 + daily_gain)
    return pd.DataFrame({"Open": opens, "Close": closes}, index=idx)


@pytest.fixture()
def config(tmp_path):
    return {
        "decision_ledger_path": str(tmp_path / "decisions.jsonl"),
        "eval_horizons": [2, 5],
        "eval_benchmark": "SPY",
    }


def test_settlement_next_open_convention(config):
    # NVDA rises 1%/day, SPY is flat -> positive alpha.
    frames = {
        "NVDA": make_frame("2026-06-01", 20, 100.0, 0.01),
        "SPY":  make_frame("2026-06-01", 20, 500.0, 0.0),
    }
    ledger = DecisionLedger(config)
    # Monday 2026-06-01 -> exec on Tuesday 2026-06-02.
    ledger.record_decision("NVDA", "2026-06-01", "Buy", 101.0)

    resolver = OutcomeResolver(config, fetcher=make_fake_fetcher(frames))
    settlements = resolver.resolve(ledger, as_of="2026-06-26")

    assert {s["horizon"] for s in settlements} == {2, 5}
    s2 = next(s for s in settlements if s["horizon"] == 2)
    assert s2["exec_date"] == "2026-06-02"
    # Entry: Tue open; exit: Wed close (2 trading days: Tue, Wed).
    # raw = Open*1.01^1 ... exit close = open_base*1.01^2 * 1.01 -> vs exec open 1.01^1
    expected_raw = 1.01 ** 2 - 1  # one day of open drift + close uplift on day 2
    assert s2["raw"] == pytest.approx(expected_raw, rel=1e-9)
    assert s2["benchmark"] == pytest.approx(0.0, abs=1e-12)
    assert s2["alpha"] == pytest.approx(expected_raw, rel=1e-9)

    nvda = ledger.load_entries()[0]
    assert set(nvda["outcomes"].keys()) == {"2", "5"}


def test_horizon_not_due_stays_pending(config):
    frames = {
        "NVDA": make_frame("2026-06-01", 4, 100.0, 0.01),  # only 3 days after signal
        "SPY":  make_frame("2026-06-01", 4, 500.0, 0.0),
    }
    ledger = DecisionLedger(config)
    ledger.record_decision("NVDA", "2026-06-01", "Buy")

    resolver = OutcomeResolver(config, fetcher=make_fake_fetcher(frames))
    settlements = resolver.resolve(ledger, as_of="2026-06-04")

    assert {s["horizon"] for s in settlements} == {2}  # 5d not due yet
    assert len(ledger.pending_entries()) == 1

    # Later, with more data, the 5d horizon settles and nothing re-settles.
    frames["NVDA"] = make_frame("2026-06-01", 10, 100.0, 0.01)
    frames["SPY"] = make_frame("2026-06-01", 10, 500.0, 0.0)
    resolver2 = OutcomeResolver(config, fetcher=make_fake_fetcher(frames))
    second = resolver2.resolve(ledger, as_of="2026-06-12")
    assert {s["horizon"] for s in second} == {5}
    assert ledger.pending_entries() == []


def test_missing_ticker_data_is_skipped(config):
    frames = {"SPY": make_frame("2026-06-01", 20, 500.0, 0.0)}
    ledger = DecisionLedger(config)
    ledger.record_decision("GONE", "2026-06-01", "Buy")

    resolver = OutcomeResolver(config, fetcher=make_fake_fetcher(frames))
    assert resolver.resolve(ledger, as_of="2026-06-26") == []
    assert len(ledger.pending_entries()) == 1


def test_lagging_benchmark_blocks_settlement(config):
    frames = {
        "NVDA": make_frame("2026-06-01", 20, 100.0, 0.01),
        "SPY":  make_frame("2026-06-01", 3, 500.0, 0.0),  # benchmark lags
    }
    ledger = DecisionLedger(config)
    ledger.record_decision("NVDA", "2026-06-01", "Buy")

    resolver = OutcomeResolver(config, fetcher=make_fake_fetcher(frames))
    settlements = resolver.resolve(ledger, as_of="2026-06-26")
    # 2d settles (SPY reaches 2026-06-03), 5d cannot.
    assert {s["horizon"] for s in settlements} == {2}
