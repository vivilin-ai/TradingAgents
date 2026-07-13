"""Integration-style tests for WeeklyEvaluator with fake prices and a mock LLM."""

import json
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from tradingagents.eval.evaluator import WeeklyEvaluator
from tradingagents.eval.ledger import DecisionLedger
from tradingagents.eval.prices import make_fake_fetcher


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
        "eval_horizons": [2, 5],
        "eval_benchmark": "SPY",
        "eval_cost_bps": 0,
        "calibration_min_samples": 2,
    }


@pytest.fixture()
def fetcher():
    return make_fake_fetcher({
        "NVDA": frame("2026-06-01", 30, 100.0, 0.01),
        "AAPL": frame("2026-06-01", 30, 200.0, -0.005),
        "SPY": frame("2026-06-01", 30, 500.0, 0.0),
    })


def seed_ledger(config):
    ledger = DecisionLedger(config)
    ledger.record_decision("NVDA", "2026-06-01", "Buy", 100.0)
    ledger.record_decision("NVDA", "2026-06-08", "Buy", 105.0)
    ledger.record_decision("AAPL", "2026-06-01", "Sell", 200.0)
    return ledger


def test_full_run_without_llm(config, fetcher):
    seed_ledger(config)
    evaluator = WeeklyEvaluator(config=config, llm=None, fetcher=fetcher)
    result = evaluator.run(as_of="2026-07-10")

    # All three decisions settle on both horizons.
    assert len(result["settlements"]) == 6
    assert result["n_reflections"] == 0  # no LLM

    # Scorecard rendered to disk.
    assert result["report_path"] is not None
    md = open(result["report_path"], encoding="utf-8").read()
    assert "周度记分卡" in md

    # Sim ran: Buy on a riser + Sell on a faller -> beats flat benchmark.
    sim = result["sim_summary"]
    assert sim is not None
    assert sim["total_return"] > sim["benchmark_return"]

    # Calibration block written (min_samples=2, Buy has 2 samples).
    calibration = open(config["calibration_path"], encoding="utf-8").read()
    assert "Buy calls" in calibration

    # Eval state persisted.
    state = json.loads(open(config["eval_state_path"], encoding="utf-8").read())
    assert state["active_params"] == "default"

    # Digest is Telegram-sized text.
    assert "周度评估完成" in result["digest"]


def test_run_is_idempotent_on_settlements(config, fetcher):
    seed_ledger(config)
    evaluator = WeeklyEvaluator(config=config, llm=None, fetcher=fetcher)
    first = evaluator.run(as_of="2026-07-10")
    second = evaluator.run(as_of="2026-07-10")
    assert len(first["settlements"]) == 6
    assert second["settlements"] == []


def test_reflections_backfill_markdown_log(config, fetcher):
    from tradingagents.agents.utils.memory import TradingMemoryLog

    seed_ledger(config)
    memory_log = TradingMemoryLog(config)
    memory_log.store_decision("NVDA", "2026-06-01", "Rating: Buy\nEnter now.")
    memory_log.store_decision("AAPL", "2026-06-01", "Rating: Sell\nExit now.")

    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="- Momentum entries worked twice this week.")

    evaluator = WeeklyEvaluator(config=config, llm=llm, fetcher=fetcher)
    result = evaluator.run(as_of="2026-07-10")

    # Two markdown entries matched pending settlements -> reflections backfilled.
    assert result["n_reflections"] == 2
    assert memory_log.get_pending_entries() == [
        e for e in memory_log.get_pending_entries() if e["ticker"] not in ("NVDA", "AAPL")
    ]
    resolved = [e for e in memory_log.load_entries() if not e["pending"]]
    assert len(resolved) == 2

    # Meta-reflection stored a lesson.
    lessons = open(config["lessons_path"], encoding="utf-8").read()
    assert "Momentum entries" in lessons


def test_persistent_bias_requires_two_evals(config, fetcher):
    # AAPL falls but was rated Buy twice -> negative Buy alpha bias.
    ledger = DecisionLedger(config)
    ledger.record_decision("AAPL", "2026-06-01", "Buy", 200.0)
    ledger.record_decision("AAPL", "2026-06-08", "Buy", 195.0)

    evaluator = WeeklyEvaluator(config=config, llm=None, fetcher=fetcher)
    first = evaluator.run(as_of="2026-07-01")
    assert first["biases"], "bias should be detected"
    assert first["persistent_biases"] == []  # first sighting

    second = evaluator.run(as_of="2026-07-10")
    assert [b["code"] for b in second["persistent_biases"]] == [
        b["code"] for b in second["biases"]
    ]
    # Persistent bias lands in the calibration block.
    calibration = open(config["calibration_path"], encoding="utf-8").read()
    assert "WARNING" in calibration
