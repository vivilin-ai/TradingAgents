"""Watchlist persistence: load/save a YAML file of tickers with optional positions.

YAML format:
    tickers: [NVDA, AAPL, MSFT]
    analysts: [market, social, news, fundamentals]
    positions:
      NVDA: {cost: 125.50, qty: 100}
      # tickers absent from positions are treated as "not held" (NA)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

DEFAULT_ANALYSTS = ["market", "social", "news", "fundamentals"]

_SUFFIX_TO_CURRENCY: dict[str, tuple[str, str]] = {
    "HK": ("HK$", "HKD"),
    "TO": ("CA$", "CAD"),
    "AX": ("A$",  "AUD"),
    "L":  ("£",   "GBP"),
    "T":  ("¥",   "JPY"),
    "SS": ("¥",   "CNY"),
    "SZ": ("¥",   "CNY"),
}

def _position_currency(ticker: str) -> tuple[str, str]:
    """Return (symbol, currency_code) for a ticker based on exchange suffix."""
    parts = ticker.upper().rsplit(".", 1)
    if len(parts) == 2:
        return _SUFFIX_TO_CURRENCY.get(parts[1], ("$", "USD"))
    return ("$", "USD")


def load_watchlist(path: str) -> dict[str, Any]:
    """Load the watchlist file, returning defaults when it does not exist."""
    p = Path(path).expanduser()
    if not p.exists():
        return {"tickers": [], "analysts": DEFAULT_ANALYSTS, "positions": {}}
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("tickers", [])
    data.setdefault("analysts", DEFAULT_ANALYSTS)
    data.setdefault("positions", {})
    return data


def save_watchlist(path: str, data: dict[str, Any]) -> None:
    """Persist the watchlist, creating parent directories as needed."""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def add_tickers(path: str, tickers: list[str]) -> list[str]:
    """Add tickers (uppercased, deduplicated) and return the updated list."""
    data = load_watchlist(path)
    existing = {t.upper() for t in data["tickers"]}
    for t in tickers:
        u = t.upper()
        if u not in existing:
            data["tickers"].append(u)
            existing.add(u)
    save_watchlist(path, data)
    return data["tickers"]


def remove_tickers(path: str, tickers: list[str]) -> list[str]:
    """Remove tickers and their position data, return the updated list."""
    data = load_watchlist(path)
    remove_set = {t.upper() for t in tickers}
    data["tickers"] = [t for t in data["tickers"] if t.upper() not in remove_set]
    for t in remove_set:
        data["positions"].pop(t, None)
    save_watchlist(path, data)
    return data["tickers"]


def update_position(
    path: str,
    ticker: str,
    cost: Optional[float],
    qty: Optional[float],
) -> None:
    """Set or clear the position for a ticker.

    Pass cost=None, qty=None to mark as "not held" (removes the entry).
    """
    data = load_watchlist(path)
    ticker = ticker.upper()
    if cost is None or qty is None:
        data["positions"].pop(ticker, None)
    else:
        data["positions"][ticker] = {"cost": float(cost), "qty": float(qty)}
    save_watchlist(path, data)


def get_position(path: str, ticker: str) -> Optional[dict]:
    """Return {cost, qty} for ticker, or None if not held."""
    data = load_watchlist(path)
    return data["positions"].get(ticker.upper())


def format_position_context(ticker: str, position: Optional[dict]) -> str:
    """Format position info as a context string for the Portfolio Manager.

    This string is injected into the PM prompt so it adapts recommendations
    to the user's actual holding status.
    """
    if position and position.get("cost") and position.get("qty"):
        cost = float(position["cost"])
        qty = float(position["qty"])
        total = cost * qty
        cur, currency_name = _position_currency(ticker)
        return (
            f"[Current Position]\n"
            f"The user currently holds {qty:,.0f} shares of {ticker} "
            f"at an average cost of {cur}{cost:,.2f} {currency_name} per share "
            f"(total cost basis: {cur}{total:,.2f} {currency_name}). "
            f"Factor this into your position sizing and risk management recommendations. "
            f"Consider whether to add, hold, reduce, or exit the position."
        )
    else:
        return (
            f"[Position Status]\n"
            f"The user does NOT currently hold any shares of {ticker}. "
            f"Do NOT recommend reducing or selling a position. "
            f"Instead, focus on the specific conditions, price levels, and catalysts "
            f"under which the user should consider initiating a new position."
        )
