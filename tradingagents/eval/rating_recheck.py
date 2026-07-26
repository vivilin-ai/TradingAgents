"""Re-derive stored ratings from the decision text that produced them.

The rating attached to a past decision was extracted by the heuristic parser
at the time it ran. When that parser is corrected, already-stored decisions
keep the old label — and a mislabelled decision quietly corrupts the tier
statistics the whole evaluation loop is built on.

The full Portfolio Manager text lives in the markdown decision log, so the
rating can be recomputed from the original source without re-running any
analysis or spending any tokens. Corrections are planned first and applied
only on request, so the user sees exactly what would change.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.agents.utils.rating import parse_rating_or_none

from .ledger import DecisionLedger

logger = logging.getLogger(__name__)


def plan_rating_corrections(
    config: dict, since: Optional[str] = None
) -> list[dict[str, Any]]:
    """Decisions whose stored rating disagrees with a re-parse of their text.

    The decision text is the single source of truth, and it is checked against
    both stores: the markdown log's tag and the ledger's ``rating``. Those two
    are written by separate code paths and can drift apart, so a mismatch in
    either one is reported.

    ``since`` limits the scan to decisions on or after that date (YYYY-MM-DD).
    Entries whose text yields no rating at all are reported with ``new=None``
    and never auto-changed — there is nothing better to put there, and
    guessing is what caused the problem in the first place.
    """
    memory_log = TradingMemoryLog(config)
    ledger_ratings = {
        (e["ticker"], e["trade_date"]): e.get("rating")
        for e in DecisionLedger(config).load_entries()
    }
    corrections: list[dict[str, Any]] = []

    for entry in memory_log.load_entries():
        if since and entry["date"] < since:
            continue
        decision = entry.get("decision", "")
        if not decision:
            continue
        key = (entry["ticker"], entry["date"])
        logged = entry["rating"]
        in_ledger = ledger_ratings.get(key)
        reparsed = parse_rating_or_none(decision)

        if reparsed is None:
            corrections.append({
                "ticker": entry["ticker"], "date": entry["date"],
                "old": logged, "old_ledger": in_ledger,
                "new": None, "unparseable": True,
            })
        elif reparsed != logged or (in_ledger is not None and reparsed != in_ledger):
            corrections.append({
                "ticker": entry["ticker"], "date": entry["date"],
                "old": logged, "old_ledger": in_ledger,
                "new": reparsed, "unparseable": False,
            })
    corrections.sort(key=lambda c: (c["date"], c["ticker"]))
    return corrections


def apply_rating_corrections(
    config: dict, corrections: list[dict[str, Any]]
) -> dict[str, int]:
    """Write the actionable corrections to both stores.

    Returns counts for the markdown log and the JSONL ledger. Entries whose
    text yields no rating are skipped.
    """
    actionable = {
        (c["ticker"], c["date"]): c["new"]
        for c in corrections
        if c.get("new")
    }
    if not actionable:
        return {"memory_log": 0, "ledger": 0, "skipped": len(corrections)}

    memory_changed = TradingMemoryLog(config).update_ratings(actionable)
    ledger_changed = DecisionLedger(config).update_ratings(actionable)
    logger.info(
        "Corrected %d memory-log and %d ledger ratings",
        memory_changed, ledger_changed,
    )
    return {
        "memory_log": memory_changed,
        "ledger": ledger_changed,
        "skipped": len(corrections) - len(actionable),
    }


def week_start(as_of: Optional[str] = None) -> str:
    """Monday of the week containing ``as_of`` (default today), YYYY-MM-DD."""
    day = (
        datetime.strptime(as_of, "%Y-%m-%d") if as_of else datetime.now()
    )
    return (day - timedelta(days=day.weekday())).strftime("%Y-%m-%d")
