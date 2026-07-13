"""Daily price access with per-ticker caching and an injectable fetcher.

Every eval module that needs prices takes a ``PriceFetcher`` so tests can
inject deterministic synthetic frames instead of hitting yfinance.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# A fetch function returns a DataFrame with columns Open/Close and a
# tz-naive normalized DatetimeIndex, or an empty frame on failure.
FetchFn = Callable[[str, str, str], pd.DataFrame]


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["Open", "Close"], index=pd.DatetimeIndex([]))


def _yfinance_fetch(ticker: str, start: str, end: str) -> pd.DataFrame:
    import yfinance as yf

    try:
        df = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
    except Exception as exc:
        logger.warning("Price fetch failed for %s: %s", ticker, exc)
        return _empty_frame()
    if df.empty:
        return _empty_frame()
    df = df[["Open", "Close"]].copy()
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    return df


class PriceFetcher:
    """Caches daily Open/Close frames per (ticker, start, end) request span.

    The cache is widened per ticker: a request inside an already-fetched span
    is served from cache; a wider request refetches the union span once.
    """

    def __init__(self, fetch_fn: Optional[FetchFn] = None):
        self._fetch = fetch_fn or _yfinance_fetch
        self._cache: dict[str, tuple[str, str, pd.DataFrame]] = {}

    def history(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """Daily Open/Close for [start, end) — normalized tz-naive index."""
        cached = self._cache.get(ticker)
        if cached and cached[0] <= start and cached[1] >= end:
            df = cached[2]
            return df[(df.index >= start) & (df.index < end)]
        fetch_start = min(start, cached[0]) if cached else start
        fetch_end = max(end, cached[1]) if cached else end
        df = self._fetch(ticker, fetch_start, fetch_end)
        self._cache[ticker] = (fetch_start, fetch_end, df)
        return df[(df.index >= start) & (df.index < end)]


def make_fake_fetcher(frames: dict[str, pd.DataFrame]) -> PriceFetcher:
    """Test helper: PriceFetcher backed by in-memory frames."""

    def fetch(ticker: str, start: str, end: str) -> pd.DataFrame:
        df = frames.get(ticker)
        if df is None:
            return _empty_frame()
        return df[(df.index >= start) & (df.index < end)]

    return PriceFetcher(fetch_fn=fetch)
