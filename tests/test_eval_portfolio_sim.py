"""Deterministic tests for the advice-following portfolio replay (P2)."""

import numpy as np
import pandas as pd
import pytest

from tradingagents.eval import portfolio_sim
from tradingagents.eval.prices import make_fake_fetcher

WEIGHT_MAP = {"Buy": 1.0, "Overweight": 0.7, "Hold": None, "Underweight": 0.3, "Sell": 0.0}


def flat_frame(start: str, days: int, price: float) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=days)
    return pd.DataFrame({"Open": [price] * days, "Close": [price] * days}, index=idx)


def trending_frame(start: str, days: int, base: float, daily: float) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=days)
    px = base * (1 + daily) ** np.arange(days)
    return pd.DataFrame({"Open": px, "Close": px}, index=idx)


def test_buy_signal_captures_upside_single_ticker():
    # One ticker rising 1%/day, flat benchmark, zero cost.
    frames = {
        "NVDA": trending_frame("2026-06-01", 30, 100.0, 0.01),
        "SPY": flat_frame("2026-06-01", 30, 500.0),
    }
    entries = [{"ticker": "NVDA", "trade_date": "2026-06-01", "rating": "Buy", "outcomes": {}}]
    result = portfolio_sim.simulate(
        entries, WEIGHT_MAP, make_fake_fetcher(frames), cost_bps=0.0, as_of="2026-07-10",
    )
    assert result is not None
    # Full capacity (1 ticker -> 100%) invested at 06-02 open; NAV tracks the stock.
    nav = result["nav"]
    px = frames["NVDA"]
    expected = float(px["Close"].iloc[-1] / px["Open"].iloc[1])
    assert float(nav.iloc[-1]) == pytest.approx(expected, rel=1e-9)
    assert result["benchmark_return"] == pytest.approx(0.0, abs=1e-9)
    assert result["total_return"] > 0.2


def test_sell_signal_moves_to_cash():
    frames = {
        "NVDA": trending_frame("2026-06-01", 30, 100.0, -0.01),  # falling stock
        "SPY": flat_frame("2026-06-01", 30, 500.0),
    }
    entries = [
        {"ticker": "NVDA", "trade_date": "2026-06-01", "rating": "Buy", "outcomes": {}},
        {"ticker": "NVDA", "trade_date": "2026-06-05", "rating": "Sell", "outcomes": {}},
    ]
    result = portfolio_sim.simulate(
        entries, WEIGHT_MAP, make_fake_fetcher(frames), cost_bps=0.0, as_of="2026-07-10",
    )
    nav = result["nav"]
    # After the sell executes (06-08 open), NAV must be flat to the end.
    tail = nav[nav.index >= "2026-06-08"]
    assert float(tail.max()) == pytest.approx(float(tail.min()), rel=1e-12)
    # And better than holding the falling stock the whole way.
    buy_hold = float(frames["NVDA"]["Close"].iloc[-1] / frames["NVDA"]["Open"].iloc[1]) - 1
    assert result["total_return"] > buy_hold


def test_costs_reduce_nav():
    frames = {
        "NVDA": flat_frame("2026-06-01", 20, 100.0),
        "SPY": flat_frame("2026-06-01", 20, 500.0),
    }
    entries = [{"ticker": "NVDA", "trade_date": "2026-06-01", "rating": "Buy", "outcomes": {}}]
    no_cost = portfolio_sim.simulate(
        entries, WEIGHT_MAP, make_fake_fetcher(frames), cost_bps=0.0, as_of="2026-06-26",
    )
    with_cost = portfolio_sim.simulate(
        entries, WEIGHT_MAP, make_fake_fetcher(frames), cost_bps=10.0, as_of="2026-06-26",
    )
    assert no_cost["total_return"] == pytest.approx(0.0, abs=1e-12)
    # 100% turnover at 10 bps -> exactly -0.1% NAV.
    assert with_cost["total_return"] == pytest.approx(-0.001, rel=1e-6)


def test_capacity_split_across_tickers():
    frames = {
        "NVDA": trending_frame("2026-06-01", 20, 100.0, 0.01),
        "AAPL": flat_frame("2026-06-01", 20, 200.0),
        "SPY": flat_frame("2026-06-01", 20, 500.0),
    }
    entries = [
        {"ticker": "NVDA", "trade_date": "2026-06-01", "rating": "Buy", "outcomes": {}},
        {"ticker": "AAPL", "trade_date": "2026-06-01", "rating": "Sell", "outcomes": {}},
    ]
    result = portfolio_sim.simulate(
        entries, WEIGHT_MAP, make_fake_fetcher(frames), cost_bps=0.0, as_of="2026-06-26",
    )
    # Only half the NAV rides NVDA (2 tickers -> 50% capacity each).
    px = frames["NVDA"]
    stock_gain = float(px["Close"].iloc[-1] / px["Open"].iloc[1]) - 1
    assert result["total_return"] == pytest.approx(stock_gain / 2, rel=1e-9)


def test_hold_keeps_position():
    frames = {
        "NVDA": trending_frame("2026-06-01", 20, 100.0, 0.01),
        "SPY": flat_frame("2026-06-01", 20, 500.0),
    }
    entries = [
        {"ticker": "NVDA", "trade_date": "2026-06-01", "rating": "Buy", "outcomes": {}},
        {"ticker": "NVDA", "trade_date": "2026-06-08", "rating": "Hold", "outcomes": {}},
    ]
    with_hold = portfolio_sim.simulate(
        entries, WEIGHT_MAP, make_fake_fetcher(frames), cost_bps=0.0, as_of="2026-06-26",
    )
    only_buy = portfolio_sim.simulate(
        entries[:1], WEIGHT_MAP, make_fake_fetcher(frames), cost_bps=0.0, as_of="2026-06-26",
    )
    assert with_hold["total_return"] == pytest.approx(only_buy["total_return"], rel=1e-12)


def test_empty_entries_returns_none():
    assert portfolio_sim.simulate([], WEIGHT_MAP, make_fake_fetcher({})) is None
