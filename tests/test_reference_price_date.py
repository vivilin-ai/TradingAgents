"""The price sanity baseline must match the date being analysed.

reference_price used to be the live quote regardless of --date, so a run for a
past date was validated against today's price. Once the stock had moved beyond
the tolerance, every correctly-priced report was rejected as a hallucination
and — now that exhausted retries raise — the whole run failed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from tradingagents.graph.propagation import Propagator


def history_frame(start: str, days: int, base: float, daily: float) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=days)
    px = base * (1 + daily) ** np.arange(days)
    return pd.DataFrame({"Open": px, "Close": px}, index=idx)


@pytest.fixture()
def fake_yf():
    """Patch yfinance so no network call happens, and record the query window."""
    calls: list[dict] = []

    def history(start=None, end=None, auto_adjust=None):
        calls.append({"start": start, "end": end})
        # Mirror yfinance: [start, end) — end is exclusive.
        frame = history_frame("2026-06-01", 40, 100.0, 0.01)
        return frame[(frame.index >= start) & (frame.index < end)]

    ticker = MagicMock()
    ticker.history.side_effect = history
    with patch("yfinance.Ticker", return_value=ticker) as factory:
        yield factory, calls


def test_reference_price_follows_the_requested_date(fake_yf):
    _, calls = fake_yf
    prop = Propagator()

    state = prop.create_initial_state("NVDA", "2026-06-10")

    # The window ends the day after the requested date, never "today".
    assert calls[0]["end"] == "2026-06-11"
    frame = history_frame("2026-06-01", 40, 100.0, 0.01)
    expected = float(frame[frame.index <= "2026-06-10"]["Close"].iloc[-1])
    assert state["reference_price"] == pytest.approx(expected)
    # Not the latest price in the series — that is what the bug used to return.
    assert state["reference_price"] < float(frame["Close"].iloc[-1])


def test_two_dates_give_different_baselines(fake_yf):
    prop = Propagator()
    early = prop.create_initial_state("NVDA", "2026-06-05")["reference_price"]
    later = prop.create_initial_state("NVDA", "2026-06-25")["reference_price"]
    assert early < later, "a rising stock must have a lower baseline earlier"


def test_lookback_covers_weekends(fake_yf):
    """A Saturday run still resolves to the preceding trading day's close."""
    _, calls = fake_yf
    prop = Propagator()
    state = prop.create_initial_state("NVDA", "2026-06-13")  # Saturday
    assert state["reference_price"] > 0
    # 10 days of lookback is requested so a holiday week cannot come up empty.
    assert calls[0]["start"] == "2026-06-04"


def test_missing_data_degrades_to_skipping_the_check():
    ticker = MagicMock()
    ticker.history.return_value = pd.DataFrame()
    with patch("yfinance.Ticker", return_value=ticker):
        state = Propagator().create_initial_state("GONE", "2026-06-10")
    # 0 disables the strict price comparison rather than failing the run.
    assert state["reference_price"] == 0.0


def test_fetch_error_degrades_to_skipping_the_check():
    with patch("yfinance.Ticker", side_effect=RuntimeError("network down")):
        state = Propagator().create_initial_state("NVDA", "2026-06-10")
    assert state["reference_price"] == 0.0


def test_reference_price_is_not_the_live_quote(fake_yf):
    """fast_info must not be consulted: it is today's price by definition."""
    factory, _ = fake_yf
    Propagator().create_initial_state("NVDA", "2026-06-10")
    ticker = factory.return_value
    assert not ticker.fast_info.get.called
