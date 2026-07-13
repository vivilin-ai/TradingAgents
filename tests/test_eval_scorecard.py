"""Tests for scorecard stats, monotonicity, bias detection and rendering (P1)."""

import pytest

from tradingagents.eval import scorecard


def entry(ticker, date, rating, alpha_5d=None, raw_5d=None):
    outcomes = {}
    if alpha_5d is not None:
        outcomes["5"] = {
            "raw": raw_5d if raw_5d is not None else alpha_5d,
            "alpha": alpha_5d,
            "benchmark": 0.0,
        }
    return {"ticker": ticker, "trade_date": date, "rating": rating, "outcomes": outcomes}


AS_OF = "2026-07-13"


def test_tier_stats_and_bearish_flip():
    entries = [
        entry("A", "2026-07-01", "Buy", alpha_5d=0.02),
        entry("B", "2026-07-01", "Buy", alpha_5d=-0.01),
        entry("C", "2026-07-01", "Sell", alpha_5d=-0.03),  # stock fell -> advice right
        entry("D", "2026-07-01", "Hold", alpha_5d=0.005),
        entry("E", "2026-07-01", "Overweight"),            # unsettled -> excluded
    ]
    stats = scorecard.compute_tier_stats(entries, [5], AS_OF, window_weeks=12)
    buy = stats[5]["Buy"]
    assert buy["n"] == 2
    assert buy["hit_rate"] == pytest.approx(0.5)
    assert buy["avg_alpha"] == pytest.approx(0.005)
    assert buy["avg_eff_alpha"] == pytest.approx(0.005)

    sell = stats[5]["Sell"]
    assert sell["n"] == 1
    assert sell["avg_eff_alpha"] == pytest.approx(0.03)  # sign flipped
    assert sell["hit_rate"] == pytest.approx(1.0)

    hold = stats[5]["Hold"]
    assert hold["hit_rate"] is None  # no direction

    assert stats[5]["Overweight"]["n"] == 0


def test_window_excludes_old_entries():
    entries = [
        entry("A", "2026-01-05", "Buy", alpha_5d=0.5),   # far outside 12w window
        entry("B", "2026-07-01", "Buy", alpha_5d=0.01),
    ]
    stats = scorecard.compute_tier_stats(entries, [5], AS_OF, window_weeks=12)
    assert stats[5]["Buy"]["n"] == 1
    assert stats[5]["Buy"]["avg_alpha"] == pytest.approx(0.01)


def test_monotonicity():
    entries = (
        [entry("A", "2026-07-01", "Buy", alpha_5d=0.02)] * 8
        + [entry("B", "2026-07-01", "Hold", alpha_5d=0.0)] * 8
        + [entry("C", "2026-07-01", "Sell", alpha_5d=-0.02)] * 8
    )
    stats = scorecard.compute_tier_stats(entries, [5], AS_OF, window_weeks=12)
    assert scorecard.check_monotonicity(stats[5], min_samples=8) is True

    # Inverted: Sell outperforms Buy.
    entries_bad = (
        [entry("A", "2026-07-01", "Buy", alpha_5d=-0.02)] * 8
        + [entry("C", "2026-07-01", "Sell", alpha_5d=0.02)] * 8
    )
    stats_bad = scorecard.compute_tier_stats(entries_bad, [5], AS_OF, window_weeks=12)
    assert scorecard.check_monotonicity(stats_bad[5], min_samples=8) is False

    # Not enough qualified tiers -> None.
    few = [entry("A", "2026-07-01", "Buy", alpha_5d=0.01)] * 3
    stats_few = scorecard.compute_tier_stats(few, [5], AS_OF, window_weeks=12)
    assert scorecard.check_monotonicity(stats_few[5], min_samples=8) is None


def test_bias_detection_thresholds():
    # Overweight persistently negative beyond threshold, with enough samples.
    entries = [entry("A", "2026-07-01", "Overweight", alpha_5d=-0.02)] * 8
    stats = scorecard.compute_tier_stats(entries, [5], AS_OF, window_weeks=12)
    biases = scorecard.detect_biases(stats, min_samples=8, alpha_threshold=0.005)
    assert len(biases) == 1
    assert biases[0]["code"] == "overweight_5d_negative"

    # Below min samples -> no bias.
    few = [entry("A", "2026-07-01", "Overweight", alpha_5d=-0.02)] * 3
    stats_few = scorecard.compute_tier_stats(few, [5], AS_OF, window_weeks=12)
    assert scorecard.detect_biases(stats_few, min_samples=8, alpha_threshold=0.005) == []

    # Bearish tier: negative effective alpha means the stock ROSE against a Sell call.
    sells = [entry("A", "2026-07-01", "Sell", alpha_5d=0.02)] * 8
    stats_sell = scorecard.compute_tier_stats(sells, [5], AS_OF, window_weeks=12)
    biases_sell = scorecard.detect_biases(stats_sell, min_samples=8, alpha_threshold=0.005)
    assert [b["code"] for b in biases_sell] == ["sell_5d_negative"]


def test_render_scorecard_smoke():
    entries = [
        entry("NVDA", "2026-07-01", "Buy", alpha_5d=0.02),
        entry("AAPL", "2026-07-02", "Sell", alpha_5d=-0.01),
    ]
    stats = scorecard.compute_tier_stats(entries, [5], AS_OF, window_weeks=12)
    md = scorecard.render_scorecard_md(
        as_of=AS_OF, stats=stats, monotonic=None,
        biases=[], persistent_biases=[],
        sim_summary={
            "total_return": 0.05, "benchmark": "SPY", "benchmark_return": 0.03,
            "equal_weight_return": 0.04, "mean_weekly_alpha": 0.002,
            "ir": 0.4, "max_drawdown": -0.06, "weekly_win_rate": 0.6,
            "active_params": "default",
        },
        iteration_note="沿用现役映射。",
        window_weeks=12, min_samples=8, entries=entries,
    )
    assert "周度记分卡" in md
    assert "NVDA" in md
    assert "0.40" in md or "IR" in md

    digest = scorecard.render_telegram_summary(
        AS_OF, stats, [], {
            "total_return": 0.05, "benchmark_return": 0.03, "ir": 0.4,
        }, "note",
    )
    assert "周度评估完成" in digest
