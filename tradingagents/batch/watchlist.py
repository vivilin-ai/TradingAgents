"""Watchlist persistence: load/save a YAML file of tickers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_ANALYSTS = ["market", "social", "news", "fundamentals"]


def load_watchlist(path: str) -> dict[str, Any]:
    """Load the watchlist file, returning defaults when it does not exist."""
    p = Path(path).expanduser()
    if not p.exists():
        return {"tickers": [], "analysts": DEFAULT_ANALYSTS}
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("tickers", [])
    data.setdefault("analysts", DEFAULT_ANALYSTS)
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
    """Remove tickers and return the updated list."""
    data = load_watchlist(path)
    remove_set = {t.upper() for t in tickers}
    data["tickers"] = [t for t in data["tickers"] if t.upper() not in remove_set]
    save_watchlist(path, data)
    return data["tickers"]
