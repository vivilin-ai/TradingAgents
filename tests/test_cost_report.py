"""Tests for the weekly token-cost diagnostic (P5).

Tests each measurable driver in isolation: watchlist growth (via ledger
entries per week), bounded-context ramp-then-plateau behaviour, and retry
counts parsed from real scheduler log line formats (both the pre- and
post-backoff-fix wording, since a user's historical logs may predate the fix).
"""

from __future__ import annotations

import json

import pytest

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.eval.cost_report import (
    build_report,
    context_injection_sizes,
    retry_activity_per_week,
    tickers_per_week,
)
from tradingagents.eval.ledger import DecisionLedger

SEP = TradingMemoryLog._SEPARATOR


@pytest.fixture()
def config(tmp_path):
    return {
        "decision_ledger_path": str(tmp_path / "decisions.jsonl"),
        "memory_log_path": str(tmp_path / "trading_memory.md"),
        "lessons_path": str(tmp_path / "lessons.md"),
        "calibration_path": str(tmp_path / "calibration.md"),
        "lessons_max_entries": 20,
    }


def seed_ledger(config, rows):
    ledger = DecisionLedger(config)
    for ticker, date_, rating in rows:
        ledger.record_decision(ticker, date_, rating)


# ── tickers_per_week ─────────────────────────────────────────────────────────

def test_tickers_per_week_reflects_watchlist_growth(config):
    seed_ledger(config, [
        ("NVDA", "2026-07-06", "Hold"),
        ("NVDA", "2026-07-13", "Hold"), ("AAPL", "2026-07-13", "Hold"),
        ("NVDA", "2026-07-20", "Hold"), ("AAPL", "2026-07-20", "Hold"),
        ("GOOG", "2026-07-20", "Hold"),
    ])
    counts = tickers_per_week(config)
    assert list(counts.values()) == [1, 2, 3]


def test_tickers_per_week_deduplicates_same_ticker_same_week(config):
    # Retries can leave multiple entries for the same ticker within a week
    # once merged across attempts; the ledger itself is one-entry-per-day
    # via idempotent record_decision, but guard the aggregation regardless.
    seed_ledger(config, [("NVDA", "2026-07-06", "Hold"), ("NVDA", "2026-07-08", "Hold")])
    counts = tickers_per_week(config)
    assert list(counts.values()) == [1]  # same ISO week


def test_tickers_per_week_empty_ledger(config):
    assert tickers_per_week(config) == {}


# ── context_injection_sizes ──────────────────────────────────────────────────

def _write_memory_entries(config, n: int, ticker="NVDA"):
    blocks = []
    for i in range(n):
        blocks.append(
            f"[2026-0{(i % 9) + 1}-01 | {ticker} | Hold | +1.0% | +0.5% | 5d]\n\n"
            f"DECISION:\n**Rating**: Hold\n\nReasoning number {i}.\n\n"
            f"REFLECTION:\nLesson {i}."
        )
    with open(config["memory_log_path"], "w", encoding="utf-8") as f:
        f.write(SEP.join(blocks) + SEP)


def test_same_ticker_history_ramps_then_caps(config):
    _write_memory_entries(config, n=2)
    ctx = context_injection_sizes(config, "NVDA")
    assert ctx["same_ticker_entries_used"] == 2
    assert ctx["same_ticker_at_cap"] is False

    _write_memory_entries(config, n=5)
    ctx = context_injection_sizes(config, "NVDA")
    assert ctx["same_ticker_entries_used"] == 5
    assert ctx["same_ticker_at_cap"] is True

    # More history beyond the cap does not change the injected amount.
    _write_memory_entries(config, n=9)
    ctx2 = context_injection_sizes(config, "NVDA")
    assert ctx2["same_ticker_entries_used"] == 5
    assert ctx2["past_context_chars"] > 0


def test_lessons_pool_ramp_and_cap_reported(config):
    from tradingagents.eval.calibration import LessonsPool

    pool = LessonsPool(config["lessons_path"], max_entries=20)
    pool.save([f"lesson {i}" for i in range(5)])
    ctx = context_injection_sizes(config, "NVDA")
    assert ctx["lessons_count"] == 5
    assert ctx["lessons_at_cap"] is False

    pool.save([f"lesson {i}" for i in range(25)])  # saturates the cap of 20
    ctx = context_injection_sizes(config, "NVDA")
    assert ctx["lessons_count"] == 20
    assert ctx["lessons_at_cap"] is True


def test_calibration_reported_active_only_when_file_has_content(config):
    ctx = context_injection_sizes(config, "NVDA")
    assert ctx["calibration_active"] is False

    from tradingagents.eval.calibration import write_calibration
    write_calibration(config["calibration_path"], "[Decision calibration data]\n- Your Buy calls...")
    ctx = context_injection_sizes(config, "NVDA")
    assert ctx["calibration_active"] is True
    assert ctx["calibration_chars"] > 0


# ── retry_activity_per_week ───────────────────────────────────────────────────

def test_parses_pre_fix_retry_wording(tmp_path):
    (tmp_path / "weekly.log").write_text(
        "2026-09-07 09:58:04,974 INFO tradingagents.batch.runner: "
        "Retry attempt 1/2 (non-rate-limit) for: MSFT, MU, ALAB, 0100.HK\n",
        encoding="utf-8",
    )
    result = retry_activity_per_week(tmp_path)
    assert result["2026-W37"]["retried_tickers"] == 4


def test_parses_post_fix_backoff_wording(tmp_path):
    (tmp_path / "weekly.log").write_text(
        "2026-09-14 09:20:00,000 INFO tradingagents.batch.runner: "
        "Rate limit or connection failure on attempt 1 — workers 3→2, "
        "waiting 30s, retrying: GOOG, NVDA\n",
        encoding="utf-8",
    )
    result = retry_activity_per_week(tmp_path)
    assert result["2026-W38"]["retried_tickers"] == 2


def test_counts_hard_failures_separately(tmp_path):
    (tmp_path / "weekly_error.log").write_text(
        "2026-09-14 09:18:31,140 ERROR tradingagents.batch.runner: "
        "Failed to analyse MSFT: Connection error.\n"
        "2026-09-14 09:18:45,513 ERROR tradingagents.batch.runner: "
        "Failed to analyse MU: Connection error.\n",
        encoding="utf-8",
    )
    result = retry_activity_per_week(tmp_path)
    assert result["2026-W38"]["hard_failures"] == 2
    assert result["2026-W38"]["retried_tickers"] == 0


def test_aggregates_across_weeks_and_files(tmp_path):
    (tmp_path / "weekly.log").write_text(
        "2026-08-31 09:00:00,000 INFO x: Retry attempt 1/2 (non-rate-limit) for: A\n",
        encoding="utf-8",
    )
    (tmp_path / "weekly_eval.log").write_text(
        "2026-09-07 09:00:00,000 INFO x: Retry attempt 1/2 (non-rate-limit) for: B, C\n",
        encoding="utf-8",
    )
    result = retry_activity_per_week(tmp_path)
    assert result["2026-W36"]["retried_tickers"] == 1
    assert result["2026-W37"]["retried_tickers"] == 2


def test_no_log_dir_returns_empty(tmp_path):
    assert retry_activity_per_week(tmp_path / "does-not-exist") == {}


def test_lines_without_timestamp_are_ignored(tmp_path):
    (tmp_path / "weekly.log").write_text(
        "scheduled-run: weekly (target=watchlist)\n"  # no leading timestamp
        "Retry attempt 1/2 (non-rate-limit) for: A\n",
        encoding="utf-8",
    )
    assert retry_activity_per_week(tmp_path) == {}


# ── build_report ──────────────────────────────────────────────────────────────

def test_build_report_defaults_sample_ticker_to_most_recent(config, tmp_path):
    seed_ledger(config, [("NVDA", "2026-07-06", "Hold"), ("AAPL", "2026-07-13", "Hold")])
    report = build_report(config, log_dir=tmp_path)
    assert report["context"]["sample_ticker"] == "AAPL"


def test_build_report_handles_empty_state(config, tmp_path):
    report = build_report(config, log_dir=tmp_path)
    assert report["weekly_tickers"] == {}
    assert report["context"] is None
    assert report["retries"] == {}
