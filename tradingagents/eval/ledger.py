"""Structured JSONL decision ledger (P0).

One line per decision.  The markdown memory log stays the LLM-facing record;
this ledger is the quant-facing record that settlement, scorecard, portfolio
simulation and parameter iteration all consume.

Entry schema:
    {
      "ticker": "NVDA",
      "trade_date": "2026-07-13",
      "rating": "Overweight",
      "decision_price": 182.34,        # close/last price at decision time (0 if unknown)
      "exec_price": null,              # next-trading-day open, filled at settlement
      "exec_date": null,               # date of that open
      "outcomes": {                    # filled per horizon at settlement
        "5":  {"raw": 0.012, "alpha": 0.004, "benchmark": 0.008},
        "21": {...}
      }
    }

A horizon is resolved iff its key is present in ``outcomes``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DecisionLedger:
    """Append-mostly JSONL ledger with atomic rewrite for settlements."""

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self._path: Optional[Path] = None
        path = cfg.get("decision_ledger_path")
        if path:
            self._path = Path(path).expanduser()
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._horizons = [int(h) for h in cfg.get("eval_horizons", [5, 10, 21])]

    @property
    def path(self) -> Optional[Path]:
        return self._path

    @property
    def horizons(self) -> list[int]:
        return list(self._horizons)

    # ── Write path ────────────────────────────────────────────────────────────

    def record_decision(
        self,
        ticker: str,
        trade_date: str,
        rating: str,
        decision_price: float = 0.0,
    ) -> bool:
        """Append one decision. Idempotent on (ticker, trade_date).

        Returns True if written, False if skipped (duplicate or no path).
        """
        if not self._path:
            return False
        for entry in self.load_entries():
            if entry["ticker"] == ticker and entry["trade_date"] == trade_date:
                return False
        record = {
            "ticker": ticker,
            "trade_date": trade_date,
            "rating": rating,
            "decision_price": float(decision_price or 0.0),
            "exec_price": None,
            "exec_date": None,
            "outcomes": {},
        }
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True

    # ── Read path ─────────────────────────────────────────────────────────────

    def load_entries(self) -> list[dict[str, Any]]:
        """All entries in file order. Malformed lines are skipped with a warning."""
        if not self._path or not self._path.exists():
            return []
        entries = []
        for i, line in enumerate(self._path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed ledger line %d", i + 1)
                continue
            if "ticker" in entry and "trade_date" in entry:
                entry.setdefault("outcomes", {})
                entries.append(entry)
        return entries

    def pending_entries(self) -> list[dict[str, Any]]:
        """Entries with at least one unresolved horizon, excluding abandoned ones.

        Entries marked unresolvable (no price data long after every horizon
        came due) are skipped so a delisted or mistyped symbol is not retried
        — and re-logged — on every weekly run forever.
        """
        return [
            e for e in self.load_entries()
            if not e.get("unresolvable")
            and any(str(h) not in e.get("outcomes", {}) for h in self._horizons)
        ]

    def resolved_entries(self, horizon: int) -> list[dict[str, Any]]:
        """Entries whose given horizon is settled."""
        key = str(horizon)
        return [e for e in self.load_entries() if key in e.get("outcomes", {})]

    def update_ratings(self, updates: dict) -> int:
        """Rewrite the ``rating`` of existing entries.

        ``updates`` maps (ticker, trade_date) -> new rating. Settled outcomes
        are untouched: only the label changes, so a corrected rating is
        immediately reflected in tier stats without refetching prices.
        """
        if not self._path or not self._path.exists() or not updates:
            return 0
        entries = self.load_entries()
        changed = 0
        for entry in entries:
            key = (entry["ticker"], entry["trade_date"])
            new_rating = updates.get(key)
            if new_rating and new_rating != entry.get("rating"):
                entry["rating"] = new_rating
                changed += 1
        if changed:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        return changed

    def mark_unresolvable(self, keys: list[tuple[str, str]], reason: str) -> int:
        """Flag (ticker, trade_date) entries as permanently unsettleable."""
        if not self._path or not self._path.exists() or not keys:
            return 0
        wanted = set(keys)
        entries = self.load_entries()
        marked = 0
        for entry in entries:
            key = (entry["ticker"], entry["trade_date"])
            if key in wanted and not entry.get("unresolvable"):
                entry["unresolvable"] = True
                entry["unresolvable_reason"] = reason
                marked += 1
        if marked:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        return marked

    # ── Update path ───────────────────────────────────────────────────────────

    def apply_settlements(self, settlements: list[dict[str, Any]]) -> int:
        """Merge settlement results into entries with a single atomic rewrite.

        Each settlement dict needs: ticker, trade_date, horizon, raw, alpha,
        benchmark, exec_price, exec_date.  Returns the number applied.
        """
        if not self._path or not self._path.exists() or not settlements:
            return 0

        entries = self.load_entries()
        index = {(e["ticker"], e["trade_date"]): e for e in entries}
        applied = 0
        for s in settlements:
            entry = index.get((s["ticker"], s["trade_date"]))
            if entry is None:
                continue
            entry["outcomes"][str(int(s["horizon"]))] = {
                "raw": round(float(s["raw"]), 6),
                "alpha": round(float(s["alpha"]), 6),
                "benchmark": round(float(s["benchmark"]), 6),
            }
            if entry.get("exec_price") is None and s.get("exec_price") is not None:
                entry["exec_price"] = round(float(s["exec_price"]), 4)
                entry["exec_date"] = s.get("exec_date")
            applied += 1

        if applied:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        return applied
