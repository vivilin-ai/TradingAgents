"""Tests for backfilling the ledger from the markdown decision log."""

import numpy as np
import pandas as pd
import pytest

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.eval.backfill import backfill_from_memory_log
from tradingagents.eval.evaluator import WeeklyEvaluator
from tradingagents.eval.ledger import DecisionLedger
from tradingagents.eval.prices import make_fake_fetcher


@pytest.fixture()
def config(tmp_path):
    return {
        "decision_ledger_path": str(tmp_path / "decisions.jsonl"),
        "memory_log_path": str(tmp_path / "trading_memory.md"),
        "lessons_path": str(tmp_path / "lessons.md"),
        "calibration_path": str(tmp_path / "calibration.md"),
        "eval_state_path": str(tmp_path / "eval_state.json"),
        "reports_root": str(tmp_path / "reports"),
        "eval_horizons": [2, 5],
        "eval_benchmark": "SPY",
        "eval_cost_bps": 0,
        "calibration_min_samples": 2,
    }


def seed_memory_log(config):
    """Two pending + one already-resolved markdown entry from 'past weeks'."""
    log = TradingMemoryLog(config)
    log.store_decision("NVDA", "2026-06-01", "Rating: Buy\nEnter on momentum.")
    log.store_decision("AAPL", "2026-06-08", "Rating: Sell\nExit ahead of guidance.")
    log.store_decision("NVDA", "2026-06-08", "Rating: Overweight\nAdd gradually.")
    # Resolve one so the backfill sees a mix of pending and resolved entries.
    log.update_with_outcome(
        ticker="NVDA", trade_date="2026-06-01",
        raw_return=0.05, alpha_return=0.03, holding_days=5,
        reflection="Directional call correct.",
    )
    return log


def test_backfill_imports_all_entries(config):
    seed_memory_log(config)
    counts = backfill_from_memory_log(config)
    assert counts == {"imported": 3, "skipped": 0}

    entries = DecisionLedger(config).load_entries()
    assert {(e["ticker"], e["trade_date"], e["rating"]) for e in entries} == {
        ("NVDA", "2026-06-01", "Buy"),
        ("AAPL", "2026-06-08", "Sell"),
        ("NVDA", "2026-06-08", "Overweight"),
    }
    # Imported entries are pending settlement regardless of markdown state.
    assert all(e["outcomes"] == {} for e in entries)


def test_backfill_is_idempotent_and_merges_with_live_entries(config):
    seed_memory_log(config)
    # One decision already recorded live by trading_graph.
    DecisionLedger(config).record_decision("NVDA", "2026-06-01", "Buy", 100.0)

    counts = backfill_from_memory_log(config)
    assert counts == {"imported": 2, "skipped": 1}

    counts_again = backfill_from_memory_log(config)
    assert counts_again == {"imported": 0, "skipped": 3}
    assert len(DecisionLedger(config).load_entries()) == 3


def test_backfilled_history_settles_immediately(config):
    seed_memory_log(config)
    backfill_from_memory_log(config)

    def frame(base, daily):
        idx = pd.bdate_range("2026-06-01", periods=30)
        px = base * (1 + daily) ** np.arange(30)
        return pd.DataFrame({"Open": px, "Close": px}, index=idx)

    fetcher = make_fake_fetcher({
        "NVDA": frame(100.0, 0.01),
        "AAPL": frame(200.0, -0.005),
        "SPY": frame(500.0, 0.0),
    })
    result = WeeklyEvaluator(config=config, llm=None, fetcher=fetcher).run(as_of="2026-07-10")

    # 3 decisions x 2 horizons all settle in one run.
    assert len(result["settlements"]) == 6
    assert DecisionLedger(config).pending_entries() == []
    # Buy/Overweight on a riser + Sell on a faller -> sim beats the flat benchmark.
    assert result["sim_summary"]["total_return"] > result["sim_summary"]["benchmark_return"]


def test_backfill_with_empty_log(config):
    assert backfill_from_memory_log(config) == {"imported": 0, "skipped": 0}
