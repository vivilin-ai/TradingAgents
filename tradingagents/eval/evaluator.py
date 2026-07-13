"""WeeklyEvaluator: orchestrates the full weekly evaluation run.

Steps (each degrades gracefully when its inputs are missing):
  1. Settle all due (entry, horizon) pairs in the ledger against real prices.
  2. Backfill LLM reflections into the markdown memory log for newly settled
     shortest-horizon outcomes (reuses the existing Phase-B machinery).
  3. Compute the scorecard: tier stats, monotonicity, bias detection with the
     two-consecutive-evals persistence rule.
  4. Replay the advice-following portfolio with the active weight map.
  5. Weekly meta-reflection -> curated lessons pool.
  6. Guarded parameter iteration (P4).
  7. Write scorecard.md + calibration block; return a Telegram-sized digest.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.default_config import DEFAULT_CONFIG

from . import calibration as calib
from . import iteration, portfolio_sim, scorecard
from .ledger import DecisionLedger
from .prices import PriceFetcher
from .resolver import OutcomeResolver

logger = logging.getLogger(__name__)


class WeeklyEvaluator:
    def __init__(
        self,
        config: Optional[dict] = None,
        llm: Any = None,
        fetcher: Optional[PriceFetcher] = None,
    ):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.llm = llm
        self.fetcher = fetcher or PriceFetcher()
        self.ledger = DecisionLedger(self.config)
        self.resolver = OutcomeResolver(self.config, fetcher=self.fetcher)
        self.memory_log = TradingMemoryLog(self.config)

    # ── public API ────────────────────────────────────────────────────────────

    def run(self, as_of: Optional[str] = None) -> dict[str, Any]:
        as_of = as_of or datetime.now().strftime("%Y-%m-%d")
        horizons = sorted(int(h) for h in self.config.get("eval_horizons", [5, 10, 21]))
        window_weeks = int(self.config.get("eval_window_weeks", 12))
        min_samples = int(self.config.get("calibration_min_samples", 8))

        # 1. Settle.
        settlements = self.resolver.resolve(self.ledger, as_of=as_of)

        # 2. Backfill markdown reflections for the shortest horizon.
        n_reflections = self._backfill_reflections(settlements, horizons[0])

        entries = self.ledger.load_entries()
        state = iteration.load_state(self.config.get("eval_state_path"))

        # 3. Scorecard.
        stats = scorecard.compute_tier_stats(entries, horizons, as_of, window_weeks)
        monotonic = scorecard.check_monotonicity(stats[horizons[0]], min_samples)
        biases = scorecard.detect_biases(
            stats, min_samples, float(self.config.get("calibration_alpha_threshold", 0.005))
        )
        prev_codes = set(state.get("bias_codes", []))
        persistent = [b for b in biases if b["code"] in prev_codes]
        state["bias_codes"] = [b["code"] for b in biases]

        # 4. Advice-following simulation with the active mapping.
        weight_map = iteration.active_weight_map(state, self.config)
        sim_summary = self._simulate(entries, weight_map, as_of, window_weeks)
        if sim_summary:
            sim_summary["active_params"] = state.get("active_params", "default")

        # 5. Lessons pool.
        n_lessons = self._update_lessons(settlements, horizons[0])

        # 6. Parameter iteration.
        state, iteration_note = iteration.run_iteration(
            entries, state, self.config,
            simulate_fn=lambda wm: self._simulate(entries, wm, as_of, window_weeks),
            as_of=as_of,
        )
        iteration.save_state(self.config.get("eval_state_path"), state)

        # 7. Calibration block + scorecard.md.
        block = calib.build_calibration_block(
            stats, persistent, min_samples, window_weeks, as_of
        )
        if self.config.get("calibration_path"):
            calib.write_calibration(self.config["calibration_path"], block)

        md = scorecard.render_scorecard_md(
            as_of, stats, monotonic, biases, persistent, sim_summary,
            iteration_note, window_weeks, min_samples, entries,
        )
        report_path = self._write_report(md, as_of)

        digest = scorecard.render_telegram_summary(
            as_of, stats, persistent, sim_summary, iteration_note
        )
        if n_reflections or settlements:
            digest += f"\n本次结算 {len(settlements)} 个（决策×周期），回填反思 {n_reflections} 条。"

        return {
            "as_of": as_of,
            "settlements": settlements,
            "n_reflections": n_reflections,
            "n_lessons": n_lessons,
            "stats": stats,
            "monotonic": monotonic,
            "biases": biases,
            "persistent_biases": persistent,
            "sim_summary": sim_summary,
            "iteration_note": iteration_note,
            "report_path": report_path,
            "digest": digest,
        }

    # ── internals ─────────────────────────────────────────────────────────────

    def _simulate(self, entries, weight_map, as_of, window_weeks):
        try:
            return portfolio_sim.simulate(
                entries, weight_map, self.fetcher,
                cost_bps=float(self.config.get("eval_cost_bps", 10)),
                benchmark=self.config.get("eval_benchmark", "SPY"),
                as_of=as_of, window_weeks=window_weeks,
            )
        except Exception as exc:
            logger.warning("Portfolio simulation failed: %s", exc, exc_info=True)
            return None

    def _backfill_reflections(self, settlements: list[dict], horizon: int) -> int:
        """Reflect on newly settled shortest-horizon outcomes and update the
        markdown memory log (same shape as the in-run Phase B)."""
        if self.llm is None:
            return 0
        firsts = [s for s in settlements if s["horizon"] == horizon]
        if not firsts:
            return 0
        from tradingagents.graph.reflection import Reflector

        reflector = Reflector(self.llm)
        pending = {
            (e["ticker"], e["date"]): e for e in self.memory_log.get_pending_entries()
        }
        updates = []
        for s in firsts:
            entry = pending.get((s["ticker"], s["trade_date"]))
            if entry is None:
                continue
            try:
                reflection = reflector.reflect_on_final_decision(
                    final_decision=entry.get("decision", ""),
                    raw_return=s["raw"],
                    alpha_return=s["alpha"],
                )
            except Exception as exc:
                logger.warning("Reflection failed for %s %s: %s", s["ticker"], s["trade_date"], exc)
                continue
            updates.append({
                "ticker": s["ticker"], "trade_date": s["trade_date"],
                "raw_return": s["raw"], "alpha_return": s["alpha"],
                "holding_days": s["horizon"], "reflection": reflection,
            })
        if updates:
            self.memory_log.batch_update_with_outcomes(updates)
        return len(updates)

    def _update_lessons(self, settlements: list[dict], horizon: int) -> int:
        if self.llm is None:
            return 0
        firsts = [s for s in settlements if s["horizon"] == horizon]
        if not firsts:
            return 0
        from tradingagents.graph.reflection import Reflector

        pool = calib.LessonsPool(
            self.config.get("lessons_path"),
            int(self.config.get("lessons_max_entries", 20)),
        )
        ratings = {
            (e["ticker"], e["trade_date"]): e.get("rating", "?")
            for e in self.ledger.load_entries()
        }
        summary = "\n".join(
            f"- {s['trade_date']} {s['ticker']} "
            f"{ratings.get((s['ticker'], s['trade_date']), '?')}: "
            f"raw {s['raw']:+.1%}, alpha {s['alpha']:+.1%} ({s['horizon']}d)"
            for s in firsts
        )
        try:
            reflector = Reflector(self.llm)
            existing = pool.load()
            new_lessons = reflector.weekly_meta_reflection(summary, existing)
        except Exception as exc:
            logger.warning("Meta-reflection failed: %s", exc)
            return 0
        if new_lessons:
            pool.save(existing + new_lessons)
        return len(new_lessons)

    def _write_report(self, md: str, as_of: str) -> Optional[str]:
        root = self.config.get("reports_root")
        if not root:
            return None
        out_dir = Path(root).expanduser() / "evaluation" / as_of
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "scorecard.md"
        path.write_text(md, encoding="utf-8")
        return str(path)
