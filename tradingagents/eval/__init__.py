"""Weekly outcome-driven evaluation loop.

Modules:
    ledger        — structured JSONL decision ledger (P0)
    prices        — cached daily price access with an injectable fetcher
    resolver      — multi-horizon settlement against real prices (P1)
    scorecard     — tier stats, monotonicity, bias detection, rendering (P1)
    portfolio_sim — advice-following portfolio replay vs benchmarks (P2)
    calibration   — calibration block + curated lessons pool (P3)
    iteration     — guarded walk-forward parameter iteration (P4)
    evaluator     — WeeklyEvaluator orchestrating the full weekly run
"""

from .ledger import DecisionLedger

__all__ = ["DecisionLedger"]
