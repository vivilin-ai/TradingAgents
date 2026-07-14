"""Backfill the structured ledger from the markdown decision log.

Every past ``propagate()`` run appended a decision (ticker, date, rating tag)
to ``trading_memory.md`` — decisions genuinely made at those past dates.
Importing them lets the evaluation loop settle weeks of real history
immediately instead of accumulating from zero.

What this deliberately does NOT do: generate "historical" decisions by
re-running the analysis pipeline as of past dates. Those runs would see
today's news/sentiment data and a model that knows what happened next —
look-ahead bias that inflates every metric downstream.
"""

from __future__ import annotations

import logging

from tradingagents.agents.utils.memory import TradingMemoryLog

from .ledger import DecisionLedger

logger = logging.getLogger(__name__)


def backfill_from_memory_log(config: dict) -> dict[str, int]:
    """Import all markdown-log decisions into the JSONL ledger.

    Idempotent: entries already in the ledger are skipped, so it is safe to
    run repeatedly. Returns {"imported": n, "skipped": n}.
    """
    memory_log = TradingMemoryLog(config)
    ledger = DecisionLedger(config)

    imported = skipped = 0
    for entry in memory_log.load_entries():
        rating = entry.get("rating") or "Hold"
        if ledger.record_decision(entry["ticker"], entry["date"], rating):
            imported += 1
        else:
            skipped += 1

    if imported:
        logger.info(
            "Backfilled %d decisions from the memory log (%d already present)",
            imported, skipped,
        )
    return {"imported": imported, "skipped": skipped}
