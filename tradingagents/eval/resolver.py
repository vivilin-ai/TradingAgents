"""Multi-horizon settlement of ledger decisions against real prices (P1).

Execution convention (matches what a user following the advice experiences):
    - Entry:  Open of the first trading day strictly after ``trade_date``.
    - Exit:   Close of the h-th trading day of the holding period
              (the entry day counts as day 1).
    - Alpha:  raw return minus the benchmark (SPY) return over the same span.

A horizon settles only once enough trading days exist; otherwise it stays
pending and is retried on the next evaluate run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

from .ledger import DecisionLedger
from .prices import PriceFetcher

logger = logging.getLogger(__name__)


class OutcomeResolver:
    def __init__(self, config: dict, fetcher: Optional[PriceFetcher] = None):
        self.horizons = sorted(int(h) for h in config.get("eval_horizons", [5, 10, 21]))
        self.benchmark = config.get("eval_benchmark", "SPY")
        self.fetcher = fetcher or PriceFetcher()
        # Calendar days after which an entry that still has no price data is
        # abandoned. Must comfortably exceed the longest horizon so a genuine
        # data outage is retried, not written off.
        self.abandon_after_days = int(config.get("eval_abandon_after_days", 45))

    def resolve(
        self, ledger: DecisionLedger, as_of: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Settle every due (entry, horizon) pair. Returns the new settlements
        (already applied to the ledger)."""
        pending = ledger.pending_entries()
        if not pending:
            return []
        as_of = as_of or datetime.now().strftime("%Y-%m-%d")

        settlements: list[dict[str, Any]] = []
        by_ticker: dict[str, list[dict]] = {}
        for e in pending:
            by_ticker.setdefault(e["ticker"], []).append(e)

        # Fetch the benchmark once over the widest needed span.
        earliest = min(e["trade_date"] for e in pending)
        fetch_end = (
            datetime.strptime(as_of, "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")
        bench = self.fetcher.history(self.benchmark, earliest, fetch_end)

        abandon_cutoff = (
            datetime.strptime(as_of, "%Y-%m-%d")
            - timedelta(days=self.abandon_after_days)
        ).strftime("%Y-%m-%d")
        abandon: list[tuple[str, str]] = []

        for ticker, entries in by_ticker.items():
            start = min(e["trade_date"] for e in entries)
            prices = self.fetcher.history(ticker, start, fetch_end)
            if prices.empty:
                stale = [e for e in entries if e["trade_date"] < abandon_cutoff]
                if stale:
                    # Long past due with no data at all: a delisted or mistyped
                    # symbol. Retrying it every week only produces noise.
                    logger.warning(
                        "Abandoning %d unsettleable %s decision(s) older than %d days",
                        len(stale), ticker, self.abandon_after_days,
                    )
                    abandon.extend((e["ticker"], e["trade_date"]) for e in stale)
                else:
                    logger.warning(
                        "No price data for %s — skipping settlement (will retry)", ticker
                    )
                continue
            for entry in entries:
                settlements.extend(self._settle_entry(entry, prices, bench))

        applied = ledger.apply_settlements(settlements)
        if applied:
            logger.info("Settled %d (entry, horizon) pairs", applied)
        if abandon:
            ledger.mark_unresolvable(
                abandon, f"no price data {self.abandon_after_days}+ days after decision"
            )
        return settlements

    # ── internals ─────────────────────────────────────────────────────────────

    def _settle_entry(
        self, entry: dict, prices: pd.DataFrame, bench: pd.DataFrame
    ) -> list[dict[str, Any]]:
        trade_date = entry["trade_date"]
        after = prices[prices.index > trade_date]
        if after.empty:
            return []
        exec_date = after.index[0]
        exec_open = float(after["Open"].iloc[0])
        if exec_open <= 0:
            return []

        bench_after = bench[bench.index >= exec_date] if not bench.empty else bench
        results = []
        for h in self.horizons:
            if str(h) in entry.get("outcomes", {}):
                continue
            if len(after) < h:
                continue  # horizon not due yet
            settle_date = after.index[h - 1]
            raw = float(after["Close"].iloc[h - 1]) / exec_open - 1.0

            bench_ret = self._benchmark_return(bench_after, settle_date)
            if bench_ret is None:
                continue  # benchmark data lagging — retry next run

            results.append({
                "ticker": entry["ticker"],
                "trade_date": trade_date,
                "horizon": h,
                "raw": raw,
                "alpha": raw - bench_ret,
                "benchmark": bench_ret,
                "exec_price": exec_open,
                "exec_date": exec_date.strftime("%Y-%m-%d"),
            })
        return results

    @staticmethod
    def _benchmark_return(
        bench_after: pd.DataFrame, settle_date: pd.Timestamp
    ) -> Optional[float]:
        """Benchmark open->close return from its first row to settle_date.

        Uses .asof so a one-day calendar mismatch (holiday) doesn't block
        settlement, but requires the benchmark to have reached settle_date.
        """
        if bench_after.empty or bench_after.index[-1] < settle_date:
            return None
        open_px = float(bench_after["Open"].iloc[0])
        close_px = bench_after["Close"].asof(settle_date)
        if open_px <= 0 or pd.isna(close_px):
            return None
        return float(close_px) / open_px - 1.0
