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

from pathlib import Path

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.agents.utils.rating import analyze_rating

from .ledger import DecisionLedger

logger = logging.getLogger(__name__)


def find_report(config: dict, ticker: str, date: str) -> Optional[str]:
    """Locate the saved report for a decision so the original can be read."""
    root = config.get("reports_root")
    if not root:
        return None
    base = Path(root).expanduser()
    if not base.exists():
        return None
    for pattern in (
        f"*/{date}/{ticker}.md",
        f"*/*/{date}/{ticker}.md",
        f"manual/{date}_{ticker}/*.md",
    ):
        for match in sorted(base.glob(pattern)):
            return str(match)
    return None


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
        evidence = analyze_rating(decision)

        disagrees = evidence.rating is not None and (
            evidence.rating != logged
            or (in_ledger is not None and evidence.rating != in_ledger)
        )
        if evidence.rating is None or disagrees:
            corrections.append({
                "ticker": entry["ticker"], "date": entry["date"],
                "old": logged, "old_ledger": in_ledger,
                "new": evidence.rating,
                "unparseable": evidence.rating is None,
                # method/snippet let the user judge the change instead of
                # trusting a heuristic they cannot see the input for.
                "method": evidence.method,
                "snippet": evidence.snippet,
                "authoritative": evidence.is_authoritative,
                "report": find_report(config, entry["ticker"], entry["date"]),
                "decision": decision,
            })
    corrections.sort(key=lambda c: (c["date"], c["ticker"]))
    return corrections


def is_confident(correction: dict[str, Any]) -> bool:
    """Whether a correction rests on an explicit rating label in the text.

    Only ``method == "label"`` is authoritative: the stored rating simply
    failed to read a label that was there. Everything else is one heuristic
    disagreeing with another, which is not grounds for silently rewriting
    recorded history.
    """
    return bool(correction.get("new")) and correction.get("method") == "label"


def apply_rating_corrections(
    config: dict,
    corrections: list[dict[str, Any]],
    include_uncertain: bool = False,
) -> dict[str, int]:
    """Write the actionable corrections to both stores.

    By default only label-backed corrections are written. Prose-based ones
    require ``include_uncertain`` — they replace one guess with another, so the
    user has to opt in after reviewing the evidence.
    """
    actionable = {
        (c["ticker"], c["date"]): c["new"]
        for c in corrections
        if c.get("new") and (include_uncertain or is_confident(c))
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
