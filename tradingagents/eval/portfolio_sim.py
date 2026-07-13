"""Advice-following portfolio replay (P2).

Simulates a user who executes every rating signal from the ledger:
  - Capital is split into equal per-ticker capacity (1/N of NAV for N tickers
    ever seen in the ledger).
  - A rating maps to a target fraction of that capacity via ``weight_map``
    (None = keep the current position).
  - Trades execute at the Open of the first trading day after the signal
    date, paying ``cost_bps`` one-way on turnover.
  - Unallocated capital stays in cash.

Everything is replayed from the ledger, so changing the weight map re-runs
the whole history — this is the engine parameter iteration (P4) uses.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

from .prices import PriceFetcher

logger = logging.getLogger(__name__)


def simulate(
    entries: list[dict],
    weight_map: dict[str, Optional[float]],
    fetcher: PriceFetcher,
    cost_bps: float = 10.0,
    benchmark: str = "SPY",
    as_of: Optional[str] = None,
    window_weeks: int = 12,
) -> Optional[dict[str, Any]]:
    """Replay the ledger. Returns summary stats + NAV series, or None when
    there is not enough data to simulate (no signals or no prices)."""
    if not entries:
        return None
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")
    fetch_end = (
        datetime.strptime(as_of, "%Y-%m-%d") + timedelta(days=1)
    ).strftime("%Y-%m-%d")

    tickers = sorted({e["ticker"] for e in entries})
    start = min(e["trade_date"] for e in entries)

    prices: dict[str, pd.DataFrame] = {}
    for t in tickers:
        df = fetcher.history(t, start, fetch_end)
        if not df.empty:
            prices[t] = df
    if not prices:
        return None
    bench_px = fetcher.history(benchmark, start, fetch_end)

    # Union trading calendar across held tickers.
    calendar = sorted(set().union(*(df.index for df in prices.values())))
    if len(calendar) < 2:
        return None
    calendar = [d for d in calendar if d.strftime("%Y-%m-%d") <= as_of]

    # signal date -> {ticker: target_weight}; executed at first calendar day
    # strictly after trade_date.
    rebalances: dict[pd.Timestamp, dict[str, float]] = {}
    for e in sorted(entries, key=lambda x: x["trade_date"]):
        target = weight_map.get(e.get("rating"))
        if target is None or e["ticker"] not in prices:
            continue
        after = [d for d in calendar if d > pd.Timestamp(e["trade_date"])]
        if not after:
            continue
        rebalances.setdefault(after[0], {})[e["ticker"]] = float(target)

    capacity = 1.0 / len(tickers)
    cost = cost_bps / 10_000.0

    cash = 1.0
    shares: dict[str, float] = {t: 0.0 for t in tickers}
    last_close: dict[str, float] = {}
    nav_points: list[tuple[pd.Timestamp, float]] = []

    def _px(t: str, day: pd.Timestamp, col: str) -> Optional[float]:
        df = prices[t]
        if day in df.index:
            v = df.at[day, col]
            return float(v) if not pd.isna(v) else None
        return None

    for day in calendar:
        # Rebalance at the open.
        for t, w in rebalances.get(day, {}).items():
            open_px = _px(t, day, "Open")
            if open_px is None or open_px <= 0:
                # Ticker not trading this day — push the order to the next day.
                nxt = next((d for d in calendar if d > day and _px(t, d, "Open")), None)
                if nxt is not None:
                    rebalances.setdefault(nxt, {}).setdefault(t, w)
                continue
            nav_open = cash + sum(
                shares[s] * (_px(s, day, "Open") or last_close.get(s, 0.0))
                for s in tickers
            )
            target_value = w * capacity * nav_open
            trade_value = target_value - shares[t] * open_px
            shares[t] += trade_value / open_px
            cash -= trade_value + abs(trade_value) * cost

        # Mark at the close.
        for t in tickers:
            close_px = _px(t, day, "Close")
            if close_px is not None:
                last_close[t] = close_px
        nav = cash + sum(shares[t] * last_close.get(t, 0.0) for t in tickers)
        nav_points.append((day, nav))

    nav_series = pd.Series(
        [v for _, v in nav_points], index=[d for d, _ in nav_points], name="nav"
    )

    # ── Benchmarks ────────────────────────────────────────────────────────────
    bench_series = _buy_and_hold(bench_px, nav_series.index)
    equal_weight = _equal_weight_series(prices, nav_series.index)

    # ── Stats ────────────────────────────────────────────────────────────────
    weekly = nav_series.resample("W-FRI").last().pct_change().dropna()
    if bench_series is not None:
        bench_weekly = bench_series.resample("W-FRI").last().pct_change().dropna()
        weekly_alpha = (weekly - bench_weekly).dropna()
    else:
        weekly_alpha = weekly
    tail = weekly_alpha.tail(window_weeks)

    ir = None
    if len(tail) >= 4 and float(tail.std()) > 1e-12:
        ir = float(tail.mean()) / float(tail.std())

    running_max = nav_series.cummax()
    max_dd = float(((nav_series - running_max) / running_max).min()) if len(nav_series) else None

    return {
        "nav": nav_series,
        "benchmark_nav": bench_series,
        "equal_weight_nav": equal_weight,
        "total_return": float(nav_series.iloc[-1]) - 1.0,
        "benchmark": benchmark,
        "benchmark_return": (
            float(bench_series.iloc[-1]) - 1.0 if bench_series is not None else None
        ),
        "equal_weight_return": (
            float(equal_weight.iloc[-1]) - 1.0 if equal_weight is not None else None
        ),
        "mean_weekly_alpha": float(tail.mean()) if len(tail) else None,
        "ir": ir,
        "max_drawdown": max_dd,
        "weekly_win_rate": (
            float((tail > 0).mean()) if len(tail) else None
        ),
        "n_weeks": len(weekly_alpha),
    }


def _buy_and_hold(
    px: pd.DataFrame, calendar: pd.Index
) -> Optional[pd.Series]:
    if px is None or px.empty:
        return None
    aligned = px["Close"].reindex(calendar).ffill().dropna()
    if aligned.empty:
        return None
    entry = px["Open"].reindex(calendar).ffill().dropna()
    base = float(entry.iloc[0]) if len(entry) else float(aligned.iloc[0])
    if base <= 0 or math.isclose(base, 0.0):
        return None
    return aligned / base


def _equal_weight_series(
    prices: dict[str, pd.DataFrame], calendar: pd.Index
) -> Optional[pd.Series]:
    """1/N in every ticker, bought at each ticker's first available close."""
    parts = []
    for t, df in prices.items():
        aligned = df["Close"].reindex(calendar).ffill()
        first_valid = aligned.first_valid_index()
        if first_valid is None:
            continue
        base = float(aligned.loc[first_valid])
        if base <= 0:
            continue
        norm = aligned / base
        norm = norm.fillna(1.0)  # before a ticker exists it sits in "cash" at 1.0
        parts.append(norm)
    if not parts:
        return None
    return sum(parts) / len(parts)
