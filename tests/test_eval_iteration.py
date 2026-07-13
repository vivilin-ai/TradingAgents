"""Tests for guarded parameter iteration (P4) and calibration/lessons (P3)."""

import pytest

from tradingagents.eval import iteration
from tradingagents.eval.calibration import (
    LessonsPool,
    build_calibration_block,
    load_calibration,
    write_calibration,
)


def settled(n):
    return [
        {"ticker": "A", "trade_date": "2026-07-01", "rating": "Buy",
         "outcomes": {"5": {"raw": 0.01, "alpha": 0.01, "benchmark": 0.0}}}
        for _ in range(n)
    ]


BASE_CONFIG = {
    "iteration_min_decisions": 30,
    "iteration_switch_margin": 0.003,
    "iteration_switch_streak": 2,
    "rating_weight_map": iteration.CANDIDATE_MAPS["default"],
}


def scores_fn(scores: dict):
    """simulate_fn stub keyed by candidate weight map identity."""
    def fn(weight_map):
        for name, candidate in iteration.CANDIDATE_MAPS.items():
            if weight_map == candidate:
                return {"ir": scores.get(name)}
        return {"ir": scores.get("default")}
    return fn


def test_below_min_decisions_no_iteration():
    state = iteration.load_state(None)
    new_state, note = iteration.run_iteration(
        settled(5), state, BASE_CONFIG, scores_fn({}), "2026-07-13",
    )
    assert new_state["active_params"] == "default"
    assert "门槛" in note


def test_switch_requires_two_consecutive_wins():
    state = iteration.load_state(None)
    scores = {"default": 0.10, "conservative": 0.20, "aggressive": 0.05}

    # Week 1: conservative wins -> streak 1, no switch yet.
    state, note1 = iteration.run_iteration(
        settled(40), state, BASE_CONFIG, scores_fn(scores), "2026-07-06",
    )
    assert state["active_params"] == "default"
    assert state["candidate_streak"] == {"name": "conservative", "count": 1}

    # Week 2: conservative wins again -> switch.
    state, note2 = iteration.run_iteration(
        settled(40), state, BASE_CONFIG, scores_fn(scores), "2026-07-13",
    )
    assert state["active_params"] == "conservative"
    assert state["candidate_streak"] == {"name": None, "count": 0}
    assert state["history"][-1]["to"] == "conservative"
    assert "切换" in note2


def test_streak_resets_when_active_reclaims_lead():
    state = iteration.load_state(None)
    state, _ = iteration.run_iteration(
        settled(40), state, BASE_CONFIG,
        scores_fn({"default": 0.1, "conservative": 0.2, "aggressive": 0.0}), "2026-07-06",
    )
    assert state["candidate_streak"]["count"] == 1
    # Active is best again -> streak resets.
    state, _ = iteration.run_iteration(
        settled(40), state, BASE_CONFIG,
        scores_fn({"default": 0.3, "conservative": 0.2, "aggressive": 0.0}), "2026-07-13",
    )
    assert state["candidate_streak"] == {"name": None, "count": 0}
    assert state["active_params"] == "default"


def test_margin_blocks_marginal_winner():
    state = iteration.load_state(None)
    state, note = iteration.run_iteration(
        settled(40), state, BASE_CONFIG,
        scores_fn({"default": 0.100, "conservative": 0.102, "aggressive": 0.0}), "2026-07-06",
    )
    assert state["candidate_streak"] == {"name": None, "count": 0}
    assert "不切换" in note


def test_state_roundtrip(tmp_path):
    path = str(tmp_path / "eval_state.json")
    state = iteration.load_state(path)
    state["active_params"] = "aggressive"
    iteration.save_state(path, state)
    assert iteration.load_state(path)["active_params"] == "aggressive"


def test_active_weight_map_follows_config():
    custom = {"Buy": 0.5, "Overweight": 0.4, "Hold": None, "Underweight": 0.2, "Sell": 0.0}
    config = {"rating_weight_map": custom}
    assert iteration.active_weight_map({"active_params": "default"}, config) == custom
    assert (
        iteration.active_weight_map({"active_params": "aggressive"}, config)
        == iteration.CANDIDATE_MAPS["aggressive"]
    )


# ── Calibration block ────────────────────────────────────────────────────────

def tier_stats(n_buy=10, alpha=0.012, hit=0.6):
    from tradingagents.agents.utils.rating import RATINGS_5_TIER
    empty = {"n": 0, "hit_rate": None, "avg_alpha": None, "avg_raw": None, "avg_eff_alpha": None}
    per = {r: dict(empty) for r in RATINGS_5_TIER}
    per["Buy"] = {"n": n_buy, "hit_rate": hit, "avg_alpha": alpha, "avg_raw": alpha, "avg_eff_alpha": alpha}
    return {5: per}


def test_calibration_block_contents_and_guard():
    block = build_calibration_block(tier_stats(), [], min_samples=8, window_weeks=12, as_of="2026-07-13")
    assert "Buy calls (10 samples)" in block
    assert "+1.20%" in block
    # Below min samples everywhere -> empty block.
    assert build_calibration_block(tier_stats(n_buy=3), [], 8, 12, "2026-07-13") == ""


def test_calibration_block_includes_persistent_biases():
    biases = [{"code": "buy_5d_negative", "message": "Buy calls average -1.0% ..."}]
    block = build_calibration_block(tier_stats(), biases, 8, 12, "2026-07-13")
    assert "WARNING" in block


def test_calibration_write_and_load(tmp_path):
    path = str(tmp_path / "calibration.md")
    write_calibration(path, "hello block")
    assert load_calibration(path) == "hello block"
    assert load_calibration(str(tmp_path / "missing.md")) == ""
    assert load_calibration(None) == ""


# ── Lessons pool ─────────────────────────────────────────────────────────────

def test_lessons_pool_dedupe_and_cap(tmp_path):
    pool = LessonsPool(str(tmp_path / "lessons.md"), max_entries=3)
    pool.save(["a", "b", "a", "c", "d"])  # dedupe then keep tail 3
    assert pool.load() == ["b", "c", "d"]
    block = pool.as_prompt_block()
    assert block.startswith("[Curated lessons")
    assert "- d" in block


def test_lessons_pool_empty(tmp_path):
    pool = LessonsPool(str(tmp_path / "lessons.md"))
    assert pool.load() == []
    assert pool.as_prompt_block() == ""
