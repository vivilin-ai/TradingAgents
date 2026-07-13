"""Tests for the structured decision ledger (P0)."""

import json

import pytest

from tradingagents.eval.ledger import DecisionLedger


@pytest.fixture()
def ledger(tmp_path):
    return DecisionLedger({
        "decision_ledger_path": str(tmp_path / "decisions.jsonl"),
        "eval_horizons": [5, 10],
    })


def test_record_and_load(ledger):
    assert ledger.record_decision("NVDA", "2026-07-06", "Buy", 182.34)
    entries = ledger.load_entries()
    assert len(entries) == 1
    e = entries[0]
    assert e["ticker"] == "NVDA"
    assert e["rating"] == "Buy"
    assert e["decision_price"] == 182.34
    assert e["outcomes"] == {}


def test_record_is_idempotent(ledger):
    assert ledger.record_decision("NVDA", "2026-07-06", "Buy")
    assert not ledger.record_decision("NVDA", "2026-07-06", "Sell")
    assert len(ledger.load_entries()) == 1
    assert ledger.load_entries()[0]["rating"] == "Buy"


def test_no_path_is_noop():
    ledger = DecisionLedger({})
    assert not ledger.record_decision("NVDA", "2026-07-06", "Buy")
    assert ledger.load_entries() == []


def test_pending_and_resolved(ledger):
    ledger.record_decision("NVDA", "2026-07-06", "Buy")
    ledger.record_decision("AAPL", "2026-07-06", "Hold")
    assert len(ledger.pending_entries()) == 2

    applied = ledger.apply_settlements([{
        "ticker": "NVDA", "trade_date": "2026-07-06", "horizon": 5,
        "raw": 0.012, "alpha": 0.004, "benchmark": 0.008,
        "exec_price": 180.0, "exec_date": "2026-07-07",
    }])
    assert applied == 1

    nvda = [e for e in ledger.load_entries() if e["ticker"] == "NVDA"][0]
    assert nvda["outcomes"]["5"]["alpha"] == 0.004
    assert nvda["exec_price"] == 180.0
    assert nvda["exec_date"] == "2026-07-07"
    # 10d still unresolved -> still pending
    assert len(ledger.pending_entries()) == 2
    assert len(ledger.resolved_entries(5)) == 1

    ledger.apply_settlements([{
        "ticker": "NVDA", "trade_date": "2026-07-06", "horizon": 10,
        "raw": 0.02, "alpha": 0.01, "benchmark": 0.01,
        "exec_price": 180.0, "exec_date": "2026-07-07",
    }])
    pending = ledger.pending_entries()
    assert [e["ticker"] for e in pending] == ["AAPL"]


def test_malformed_lines_are_skipped(ledger):
    ledger.record_decision("NVDA", "2026-07-06", "Buy")
    with open(ledger.path, "a", encoding="utf-8") as f:
        f.write("not json\n")
        f.write(json.dumps({"no_ticker": True}) + "\n")
    assert len(ledger.load_entries()) == 1


def test_settlement_for_unknown_entry_ignored(ledger):
    ledger.record_decision("NVDA", "2026-07-06", "Buy")
    applied = ledger.apply_settlements([{
        "ticker": "TSLA", "trade_date": "2026-07-06", "horizon": 5,
        "raw": 0.0, "alpha": 0.0, "benchmark": 0.0,
        "exec_price": 1.0, "exec_date": "2026-07-07",
    }])
    assert applied == 0
