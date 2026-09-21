"""Diagnose why weekly token spend is trending up (P5).

Token cost per scheduled run is driven by things a user cannot see from the
Telegram summary alone: how many tickers get analysed, how much historical
context gets injected into every agent call, and how many times a ticker's
entire agent pipeline gets re-run due to retries. This module reads the
user's own local state (decision ledger, lessons pool, calibration block,
scheduler logs) to make each of those visible and quantified, instead of
guessing at the cause.

Two of the context-injection components (same-ticker history, the curated
lessons pool) are bounded and ramp up only until they hit a fixed cap — see
TradingMemoryLog.get_past_context (n_same/n_cross) and LessonsPool
(max_entries). Once at the cap they stop growing. The calibration block
(build_calibration_block) turns on as a one-time step the first time a
rating tier crosses calibration_min_samples in the rolling window, then
grows only slowly as more tiers/horizons cross that bar. None of these
explain unbounded growth; retries and watchlist size can.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from tradingagents.agents.utils.memory import TradingMemoryLog

from .calibration import LessonsPool, load_calibration
from .ledger import DecisionLedger


def tickers_per_week(config: dict) -> dict[str, int]:
    """Distinct tickers analysed per ISO week, from the decision ledger.

    A rising count here directly explains rising cost — more tickers means
    more full agent pipelines per run — independent of any per-call context
    growth. Uses the ledger (not the current watchlist) so past weeks with a
    smaller watchlist show their true, smaller count.
    """
    entries = DecisionLedger(config).load_entries()
    by_week: dict[str, set[str]] = defaultdict(set)
    for e in entries:
        try:
            d = date.fromisoformat(e["trade_date"])
        except ValueError:
            continue
        iso = d.isocalendar()
        week = f"{iso[0]}-W{iso[1]:02d}"
        by_week[week].add(e["ticker"])
    return {week: len(tickers) for week, tickers in sorted(by_week.items())}


def context_injection_sizes(config: dict, sample_ticker: str) -> dict[str, Any]:
    """Current size of every history/context block injected into agent
    prompts, for one representative ticker. Reported in characters, with a
    rough token estimate (chars / 3, a conservative blend for mixed
    CJK/English prose) since exact tokenization depends on the model.

    Also reports whether the bounded components (same-ticker history,
    lessons pool) are still ramping toward their cap or have plateaued —
    the key fact for telling "this will keep growing" from "this already
    stopped growing."
    """
    memory_log = TradingMemoryLog(config)
    past_context = memory_log.get_past_context(sample_ticker)

    lessons_cap = int(config.get("lessons_max_entries", 20) or 20)
    lessons_pool = LessonsPool(config.get("lessons_path"), lessons_cap)
    lessons_entries = lessons_pool.load()
    lessons_block = lessons_pool.as_prompt_block()

    calibration_block = load_calibration(config.get("calibration_path"))

    same_entries = [
        e for e in memory_log.load_entries()
        if not e.get("pending") and e["ticker"] == sample_ticker
    ]
    same_cap = 5  # TradingMemoryLog.get_past_context's n_same default

    return {
        "sample_ticker": sample_ticker,
        "past_context_chars": len(past_context),
        "past_context_tokens_est": len(past_context) // 3,
        "same_ticker_entries_used": min(len(same_entries), same_cap),
        "same_ticker_cap": same_cap,
        "same_ticker_at_cap": len(same_entries) >= same_cap,
        "lessons_chars": len(lessons_block),
        "lessons_tokens_est": len(lessons_block) // 3,
        "lessons_count": len(lessons_entries),
        "lessons_cap": lessons_cap,
        "lessons_at_cap": len(lessons_entries) >= lessons_cap,
        "calibration_chars": len(calibration_block),
        "calibration_tokens_est": len(calibration_block) // 3,
        "calibration_active": bool(calibration_block),
    }


# ── Scheduler log parsing ────────────────────────────────────────────────────

_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2},\d{3}")
# Covers both the pre- and post-backoff-fix log wording, since a user may not
# have pulled the newer code for every past week's run.
_RETRY_BATCH_RE = re.compile(
    r"(?:Retry attempt \d+/\d+ \((?:non-rate-limit|no backoff needed)\) for: |"
    r"retrying: )(.+)$"
)
_FAILED_ANALYSE_RE = re.compile(r"Failed to analyse (\S+):")


def retry_activity_per_week(log_dir: str | Path) -> dict[str, dict[str, int]]:
    """Count retried-ticker-attempts and hard failures per ISO week, from
    every ``*.log``/``*_error.log`` file in the scheduler's log directory.

    Each entry in a "Retry attempt ... for: A, B, C" line is one ticker whose
    entire agent pipeline is about to be re-run from scratch — that is a
    full re-spend of that ticker's weekly token cost, not a cheap retry.
    """
    log_dir = Path(log_dir).expanduser()
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"retried_tickers": 0, "hard_failures": 0})
    if not log_dir.exists():
        return {}

    for log_file in sorted(log_dir.glob("*.log")):
        try:
            text = log_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            m = _TIMESTAMP_RE.match(line)
            if not m:
                continue
            d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            iso = d.isocalendar()
            week = f"{iso[0]}-W{iso[1]:02d}"

            retry_m = _RETRY_BATCH_RE.search(line)
            if retry_m:
                tickers = [t.strip() for t in retry_m.group(1).split(",") if t.strip()]
                counts[week]["retried_tickers"] += len(tickers)
            if _FAILED_ANALYSE_RE.search(line):
                counts[week]["hard_failures"] += 1

    return dict(sorted(counts.items()))


def build_report(
    config: dict, log_dir: Optional[str] = None, sample_ticker: Optional[str] = None
) -> dict[str, Any]:
    """Assemble the full cost diagnostic. ``sample_ticker`` defaults to the
    most recently analysed ticker in the ledger, if any."""
    from tradingagents.scheduler.installer import _LOG_DIR

    weekly_tickers = tickers_per_week(config)

    if sample_ticker is None:
        entries = DecisionLedger(config).load_entries()
        sample_ticker = entries[-1]["ticker"] if entries else None

    context = context_injection_sizes(config, sample_ticker) if sample_ticker else None
    retries = retry_activity_per_week(log_dir or _LOG_DIR)

    return {
        "weekly_tickers": weekly_tickers,
        "context": context,
        "retries": retries,
    }
