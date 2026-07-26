"""Tests for re-deriving stored ratings from the original decision text."""

from __future__ import annotations

import json

import pytest

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.eval.ledger import DecisionLedger
from tradingagents.eval.rating_recheck import (
    apply_rating_corrections,
    is_confident,
    plan_rating_corrections,
    week_start,
)

SEP = TradingMemoryLog._SEPARATOR

# Prose that the old parser mislabelled Hold because 持有成本 precedes 卖出.
BEARISH = (
    "综合评估，持有成本偏高，基本面持续恶化，估值透支，"
    "短期不建议买入，建议卖出并规避风险。"
)
BULLISH_LABELLED = "**Rating**: Buy\n\n**Investment Thesis**: 增长强劲，建议买入。"
NO_RATING = "本周成交量下降，波动率上升，方向不明。"


@pytest.fixture()
def config(tmp_path):
    return {
        "memory_log_path": str(tmp_path / "trading_memory.md"),
        "decision_ledger_path": str(tmp_path / "decisions.jsonl"),
    }


def seed(config, blocks: list[str], ledger_rows: list[dict]) -> None:
    with open(config["memory_log_path"], "w", encoding="utf-8") as f:
        f.write(SEP.join(blocks) + SEP)
    with open(config["decision_ledger_path"], "w", encoding="utf-8") as f:
        for row in ledger_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def row(ticker, date, rating, outcomes=None):
    return {
        "ticker": ticker, "trade_date": date, "rating": rating,
        "decision_price": 10.0, "exec_price": None, "exec_date": None,
        "outcomes": outcomes or {},
    }


def test_detects_mislabelled_bearish_decision(config):
    seed(
        config,
        [f"[2026-07-24 | 0100.HK | Hold | pending]\n\nDECISION:\n{BEARISH}"],
        [row("0100.HK", "2026-07-24", "Hold")],
    )
    corrections = plan_rating_corrections(config)
    assert len(corrections) == 1
    c = corrections[0]
    assert (c["ticker"], c["old"], c["old_ledger"], c["new"]) == (
        "0100.HK", "Hold", "Hold", "Sell",
    )


def test_correctly_labelled_decision_is_left_alone(config):
    seed(
        config,
        [f"[2026-07-24 | NVDA | Buy | pending]\n\nDECISION:\n{BULLISH_LABELLED}"],
        [row("NVDA", "2026-07-24", "Buy")],
    )
    assert plan_rating_corrections(config) == []


def test_unparseable_decision_is_reported_but_never_changed(config):
    seed(
        config,
        [f"[2026-07-24 | ARM | Hold | pending]\n\nDECISION:\n{NO_RATING}"],
        [row("ARM", "2026-07-24", "Hold")],
    )
    corrections = plan_rating_corrections(config)
    assert corrections[0]["new"] is None
    assert corrections[0]["unparseable"] is True

    counts = apply_rating_corrections(config, corrections)
    assert counts == {"memory_log": 0, "ledger": 0, "skipped": 1}
    assert TradingMemoryLog(config).load_entries()[0]["rating"] == "Hold"


def test_ledger_drift_from_the_log_is_detected(config):
    """The two stores are written by different paths and can disagree."""
    seed(
        config,
        [f"[2026-07-24 | 0100.HK | Sell | pending]\n\nDECISION:\n{BEARISH}"],
        [row("0100.HK", "2026-07-24", "Hold")],
    )
    corrections = plan_rating_corrections(config)
    assert len(corrections) == 1
    assert corrections[0]["new"] == "Sell"


def test_apply_updates_both_stores_and_preserves_outcomes(config):
    seed(
        config,
        [
            f"[2026-07-24 | 0100.HK | Hold | +1.5% | +0.6% | 5d]\n\n"
            f"DECISION:\n{BEARISH}\n\nREFLECTION:\n方向判断失误。",
            f"[2026-07-24 | NVDA | Buy | pending]\n\nDECISION:\n{BULLISH_LABELLED}",
        ],
        [
            row("0100.HK", "2026-07-24", "Hold",
                {"5": {"raw": 0.015, "alpha": 0.006, "benchmark": 0.009}}),
            row("NVDA", "2026-07-24", "Buy"),
        ],
    )
    # BEARISH carries no explicit rating line, so this is an opt-in correction.
    counts = apply_rating_corrections(
        config, plan_rating_corrections(config), include_uncertain=True
    )
    assert counts["memory_log"] == 1 and counts["ledger"] == 1

    entries = {e["ticker"]: e for e in TradingMemoryLog(config).load_entries()}
    corrected = entries["0100.HK"]
    assert corrected["rating"] == "Sell"
    # Everything else about the entry survives untouched.
    assert corrected["raw"] == "+1.5%"
    assert corrected["alpha"] == "+0.6%"
    assert corrected["holding"] == "5d"
    assert corrected["reflection"] == "方向判断失误。"
    assert corrected["decision"] == BEARISH
    assert entries["NVDA"]["rating"] == "Buy"

    led = {e["ticker"]: e for e in DecisionLedger(config).load_entries()}
    assert led["0100.HK"]["rating"] == "Sell"
    assert led["0100.HK"]["outcomes"]["5"]["alpha"] == 0.006
    assert led["NVDA"]["rating"] == "Buy"


def test_uncertain_corrections_carry_evidence_and_are_not_auto_applied(config):
    """Prose-based corrections replace one guess with another, so they must be
    shown with their evidence and left alone until the user opts in."""
    seed(
        config,
        [f"[2026-07-24 | ALAB | Overweight | pending]\n\nDECISION:\n{BEARISH}"],
        [row("ALAB", "2026-07-24", "Overweight")],
    )
    corrections = plan_rating_corrections(config)
    c = corrections[0]
    assert c["new"] == "Sell"
    assert c["method"] == "conclusion"
    assert c["authoritative"] is False
    assert is_confident(c) is False
    assert "建议卖出" in c["snippet"]

    # Default apply leaves it untouched.
    counts = apply_rating_corrections(config, corrections)
    assert counts["memory_log"] == 0 and counts["skipped"] == 1
    assert TradingMemoryLog(config).load_entries()[0]["rating"] == "Overweight"

    # Opting in writes it.
    counts = apply_rating_corrections(config, corrections, include_uncertain=True)
    assert counts["memory_log"] == 1 and counts["ledger"] == 1
    assert TradingMemoryLog(config).load_entries()[0]["rating"] == "Sell"


def test_label_backed_correction_is_confident_and_auto_applied(config):
    seed(
        config,
        [f"[2026-07-24 | COHR | Buy | pending]\n\nDECISION:\n"
         f"**Rating**: Overweight\n\n光模块需求强劲，逐步增持。"],
        [row("COHR", "2026-07-24", "Buy")],
    )
    corrections = plan_rating_corrections(config)
    assert is_confident(corrections[0]) is True
    assert corrections[0]["method"] == "label"

    counts = apply_rating_corrections(config, corrections)
    assert counts["memory_log"] == 1
    assert TradingMemoryLog(config).load_entries()[0]["rating"] == "Overweight"


def test_correction_links_the_saved_report(config, tmp_path):
    report_dir = tmp_path / "reports" / "scheduled" / "weekly" / "2026-07-24"
    report_dir.mkdir(parents=True)
    (report_dir / "ALAB.md").write_text("# ALAB", encoding="utf-8")
    config["reports_root"] = str(tmp_path / "reports")

    seed(
        config,
        [f"[2026-07-24 | ALAB | Overweight | pending]\n\nDECISION:\n{BEARISH}"],
        [row("ALAB", "2026-07-24", "Overweight")],
    )
    assert plan_rating_corrections(config)[0]["report"].endswith("ALAB.md")


def test_apply_is_idempotent(config):
    seed(
        config,
        [f"[2026-07-24 | 0100.HK | Hold | pending]\n\nDECISION:\n{BEARISH}"],
        [row("0100.HK", "2026-07-24", "Hold")],
    )
    apply_rating_corrections(
        config, plan_rating_corrections(config), include_uncertain=True
    )
    assert plan_rating_corrections(config) == []
    counts = apply_rating_corrections(
        config, plan_rating_corrections(config), include_uncertain=True
    )
    assert counts["memory_log"] == 0 and counts["ledger"] == 0


def test_since_limits_the_scope(config):
    seed(
        config,
        [
            f"[2026-06-01 | OLD | Hold | pending]\n\nDECISION:\n{BEARISH}",
            f"[2026-07-24 | NEW | Hold | pending]\n\nDECISION:\n{BEARISH}",
        ],
        [row("OLD", "2026-06-01", "Hold"), row("NEW", "2026-07-24", "Hold")],
    )
    scoped = plan_rating_corrections(config, since="2026-07-20")
    assert [c["ticker"] for c in scoped] == ["NEW"]
    assert len(plan_rating_corrections(config)) == 2


def test_week_start_is_monday():
    assert week_start("2026-07-25") == "2026-07-20"   # Saturday -> Monday
    assert week_start("2026-07-20") == "2026-07-20"   # Monday -> itself
    assert week_start("2026-07-26") == "2026-07-20"   # Sunday -> same Monday


def test_missing_stores_are_handled(config):
    assert plan_rating_corrections(config) == []
    assert apply_rating_corrections(config, []) == {
        "memory_log": 0, "ledger": 0, "skipped": 0,
    }
