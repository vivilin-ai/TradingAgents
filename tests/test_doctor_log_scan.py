"""Tests for doctor's log scanning: current problems only, no false positives."""

from __future__ import annotations

import re

from cli.tasks import _last_run_segment, _scan_log_problems


def scan(text: str, name: str = "weekly") -> list[str]:
    return _scan_log_problems(name, text, re)


def joined(problems: list[str]) -> str:
    return "\n".join(problems)


# ── run segmentation ─────────────────────────────────────────────────────────

def test_last_run_segment_starts_at_newest_marker():
    text = (
        "scheduled-run: weekly (target=watchlist)\nold boom\n"
        "scheduled-run: weekly (target=watchlist)\nfresh line\n"
    )
    seg = _last_run_segment(text)
    assert "fresh line" in seg
    assert "old boom" not in seg


def test_last_run_segment_falls_back_to_tail():
    text = "\n".join(f"line {i}" for i in range(500))
    seg = _last_run_segment(text, fallback_lines=10)
    assert "line 499" in seg
    assert "line 100" not in seg


def test_evaluate_marker_is_recognised():
    text = "🚀 定时任务启动\nold\n🧮 周度评估启动\nnew\n"
    assert "old" not in _last_run_segment(text)


# ── stale problems must not be reported ──────────────────────────────────────

def test_errors_from_an_earlier_run_are_not_reported():
    text = (
        "scheduled-run: weekly (target=watchlist)\n"
        "Error: [Errno 24] Too many open files\n"
        "Traceback (most recent call last):\n"
        "openai.APIStatusError: Error code: 402 Insufficient Balance\n"
        "✅ 0/11 完成\n"
        "scheduled-run: weekly (target=watchlist)\n"
        "📊 定时任务完成：weekly\n"
        "✅ 11/11 完成\n"
    )
    assert scan(text) == []


def test_failure_in_the_latest_run_is_reported():
    text = (
        "scheduled-run: weekly (target=watchlist)\n"
        "✅ 11/11 完成\n"
        "scheduled-run: weekly (target=watchlist)\n"
        "openai.APIStatusError: Error code: 402 Insufficient Balance\n"
        "✅ 0/11 完成\n"
    )
    out = joined(scan(text))
    assert "全部失败（0/11）" in out
    assert "余额不足" in out


def test_partial_failure_is_reported():
    text = "scheduled-run: weekly\n✅ 9/11 完成\n"
    assert "部分失败（9/11）" in joined(scan(text))


# ── ticker false positives ───────────────────────────────────────────────────

def test_transient_yfinance_warnings_do_not_flag_tickers():
    """yfinance says "possibly delisted" on any hiccup, including for tickers
    a retry then fetches fine — flagging those spams a healthy watchlist."""
    text = (
        "scheduled-run: weekly (target=watchlist)\n"
        "$AVGO: possibly delisted; no timezone found\n"
        "$GOOG: possibly delisted; no timezone found\n"
        "$0100.HK: possibly delisted; no timezone found\n"
        "📊 定时任务完成：weekly\n"
        "✅ 11/11 完成\n"
    )
    assert scan(text) == []


def test_resolver_verdict_flags_the_ticker_once():
    text = (
        "scheduled-run: weekly_eval (target=evaluate)\n"
        "$MARVELL: possibly delisted; no timezone found\n"
        "No price data for MARVELL — skipping settlement\n"
    )
    problems = scan(text, "weekly_eval")
    assert len(problems) == 1
    assert "MARVELL" in problems[0]
    assert "MRVL" in problems[0]


def test_multiple_unresolvable_tickers_collapse_into_one_line():
    text = (
        "scheduled-run: weekly_eval\n"
        "No price data for MARVELL — skipping settlement\n"
        "No price data for FOO — skipping settlement\n"
    )
    problems = scan(text, "weekly_eval")
    assert len(problems) == 1
    assert "FOO" in problems[0] and "MARVELL" in problems[0]


# ── signatures still fire when current ───────────────────────────────────────

def test_current_fd_exhaustion_and_poisoned_cache_are_reported():
    text = (
        "scheduled-run: weekly\n"
        "Error: [Errno 24] Too many open files\n"
        "No columns to parse from file\n"
    )
    out = joined(scan(text))
    assert "文件描述符耗尽" in out
    assert "价格缓存" in out


def test_clean_log_reports_nothing():
    text = "scheduled-run: weekly\n📊 定时任务完成：weekly\n✅ 11/11 完成\n"
    assert scan(text) == []
