"""A decision that can never settle must be abandoned, not retried forever.

An invalid or delisted symbol left every weekly evaluation retrying the same
fetch and re-logging the same warning indefinitely.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingagents.eval.ledger import DecisionLedger
from tradingagents.eval.prices import make_fake_fetcher
from tradingagents.eval.resolver import OutcomeResolver


def frame(start: str, days: int, base: float, daily: float) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=days)
    px = base * (1 + daily) ** np.arange(days)
    return pd.DataFrame({"Open": px, "Close": px}, index=idx)


@pytest.fixture()
def config(tmp_path):
    return {
        "decision_ledger_path": str(tmp_path / "decisions.jsonl"),
        "eval_horizons": [2, 5],
        "eval_benchmark": "SPY",
        "eval_abandon_after_days": 45,
    }


@pytest.fixture()
def fetcher():
    # No frame for MARVELL at all.
    return make_fake_fetcher({
        "NVDA": frame("2026-06-01", 60, 100.0, 0.01),
        "SPY": frame("2026-06-01", 60, 500.0, 0.0),
    })


def test_recent_unfetchable_entry_is_retried(config, fetcher):
    ledger = DecisionLedger(config)
    ledger.record_decision("MARVELL", "2026-06-01", "Buy")

    OutcomeResolver(config, fetcher=fetcher).resolve(ledger, as_of="2026-06-20")

    entry = ledger.load_entries()[0]
    assert not entry.get("unresolvable"), "still within the grace window"
    assert len(ledger.pending_entries()) == 1


def test_long_overdue_unfetchable_entry_is_abandoned(config, fetcher):
    ledger = DecisionLedger(config)
    ledger.record_decision("MARVELL", "2026-06-01", "Buy")

    OutcomeResolver(config, fetcher=fetcher).resolve(ledger, as_of="2026-08-01")

    entry = ledger.load_entries()[0]
    assert entry["unresolvable"] is True
    assert "no price data" in entry["unresolvable_reason"]
    # Never retried again — no more weekly warnings for this symbol.
    assert ledger.pending_entries() == []


def test_abandoning_one_ticker_does_not_affect_others(config, fetcher):
    ledger = DecisionLedger(config)
    ledger.record_decision("MARVELL", "2026-06-01", "Buy")
    ledger.record_decision("NVDA", "2026-06-01", "Buy")

    resolver = OutcomeResolver(config, fetcher=fetcher)
    settlements = resolver.resolve(ledger, as_of="2026-08-01")

    assert {s["ticker"] for s in settlements} == {"NVDA"}
    by_ticker = {e["ticker"]: e for e in ledger.load_entries()}
    assert by_ticker["MARVELL"]["unresolvable"] is True
    assert not by_ticker["NVDA"].get("unresolvable")
    assert ledger.pending_entries() == []


def test_abandoned_entries_stay_out_of_pending_on_later_runs(config, fetcher):
    ledger = DecisionLedger(config)
    ledger.record_decision("MARVELL", "2026-06-01", "Buy")

    resolver = OutcomeResolver(config, fetcher=fetcher)
    resolver.resolve(ledger, as_of="2026-08-01")
    # A second run must be a complete no-op for this entry.
    assert resolver.resolve(ledger, as_of="2026-08-08") == []
    assert ledger.mark_unresolvable([("MARVELL", "2026-06-01")], "x") == 0


def test_abandoned_entry_still_counts_in_history(config, fetcher):
    """Abandoned entries stay in the ledger so past decisions are not erased."""
    ledger = DecisionLedger(config)
    ledger.record_decision("MARVELL", "2026-06-01", "Buy")
    OutcomeResolver(config, fetcher=fetcher).resolve(ledger, as_of="2026-08-01")

    entries = ledger.load_entries()
    assert len(entries) == 1
    assert entries[0]["rating"] == "Buy"
