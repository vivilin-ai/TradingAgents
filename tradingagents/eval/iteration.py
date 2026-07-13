"""Guarded walk-forward iteration of the rating->weight mapping (P4).

The LLM layer is never auto-tuned. The only thing iterated is the
deterministic mapping from ratings to target weights, validated by replaying
the full ledger through the portfolio simulator.

Guards:
  - fewer than ``iteration_min_decisions`` settled decisions -> no iteration;
  - a candidate must beat the active mapping's trailing IR by
    ``iteration_switch_margin`` for ``iteration_switch_streak`` consecutive
    evaluations before it is adopted (hysteresis);
  - every switch is recorded in state history and reported to the user.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

CANDIDATE_MAPS: dict[str, dict[str, Optional[float]]] = {
    "conservative": {"Buy": 0.8, "Overweight": 0.5, "Hold": None, "Underweight": 0.2, "Sell": 0.0},
    "default":      {"Buy": 1.0, "Overweight": 0.7, "Hold": None, "Underweight": 0.3, "Sell": 0.0},
    "aggressive":   {"Buy": 1.0, "Overweight": 0.9, "Hold": None, "Underweight": 0.1, "Sell": 0.0},
}


# ── Persistent eval state ────────────────────────────────────────────────────

def load_state(path: Optional[str]) -> dict[str, Any]:
    default = {
        "active_params": "default",
        "candidate_streak": {"name": None, "count": 0},
        "bias_codes": [],
        "history": [],
    }
    if not path:
        return default
    p = Path(path).expanduser()
    if not p.exists():
        return default
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Corrupt eval state at %s — starting fresh", p)
        return default
    for key, value in default.items():
        state.setdefault(key, value)
    return state


def save_state(path: Optional[str], state: dict[str, Any]) -> None:
    if not path:
        return
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def active_weight_map(state: dict[str, Any], config: dict) -> dict[str, Optional[float]]:
    name = state.get("active_params", "default")
    if name == "default":
        # "default" always follows the configurable map so users can tune it.
        return dict(config.get("rating_weight_map", CANDIDATE_MAPS["default"]))
    return dict(CANDIDATE_MAPS.get(name, CANDIDATE_MAPS["default"]))


# ── Iteration step ───────────────────────────────────────────────────────────

def run_iteration(
    entries: list[dict],
    state: dict[str, Any],
    config: dict,
    simulate_fn: Callable[[dict[str, Optional[float]]], Optional[dict]],
    as_of: str,
) -> tuple[dict[str, Any], str]:
    """One weekly iteration step. Returns (updated_state, note_for_report).

    ``simulate_fn`` maps a weight map to sim summary (injectable for tests).
    """
    min_decisions = int(config.get("iteration_min_decisions", 30))
    margin = float(config.get("iteration_switch_margin", 0.003))
    needed_streak = int(config.get("iteration_switch_streak", 2))

    settled = [e for e in entries if e.get("outcomes")]
    if len(settled) < min_decisions:
        return state, (
            f"已结算决策 {len(settled)}/{min_decisions} 条，未达参数迭代启动门槛，"
            f"沿用现役映射 [{state.get('active_params', 'default')}]。"
        )

    candidates = dict(CANDIDATE_MAPS)
    candidates["default"] = dict(config.get("rating_weight_map", CANDIDATE_MAPS["default"]))

    scores: dict[str, Optional[float]] = {}
    for name, weight_map in candidates.items():
        summary = simulate_fn(weight_map)
        # Rank by trailing IR; fall back to mean weekly alpha when IR undefined.
        if summary is None:
            scores[name] = None
        elif summary.get("ir") is not None:
            scores[name] = summary["ir"]
        else:
            scores[name] = summary.get("mean_weekly_alpha")

    active = state.get("active_params", "default")
    active_score = scores.get(active)
    ranked = sorted(
        ((n, s) for n, s in scores.items() if s is not None),
        key=lambda t: t[1], reverse=True,
    )
    if not ranked or active_score is None:
        return state, "价格数据不足，本周跳过参数迭代。"

    best_name, best_score = ranked[0]
    score_line = " / ".join(f"{n}:{s:.3f}" for n, s in ranked)

    if best_name == active or best_score - active_score <= margin:
        state["candidate_streak"] = {"name": None, "count": 0}
        return state, f"现役映射 [{active}] 仍最优或差距未超阈值（{score_line}），不切换。"

    streak = state.get("candidate_streak", {"name": None, "count": 0})
    if streak.get("name") == best_name:
        streak["count"] += 1
    else:
        streak = {"name": best_name, "count": 1}

    if streak["count"] >= needed_streak:
        state["active_params"] = best_name
        state["candidate_streak"] = {"name": None, "count": 0}
        state.setdefault("history", []).append({
            "date": as_of, "from": active, "to": best_name,
            "scores": {n: s for n, s in ranked},
        })
        note = (
            f"🔁 评级→仓位映射切换：[{active}] → [{best_name}]"
            f"（连续 {needed_streak} 周跑赢，IR {score_line}）。"
            f"如需回退，将 eval_state.json 的 active_params 改回 \"{active}\"。"
        )
    else:
        state["candidate_streak"] = streak
        note = (
            f"候选映射 [{best_name}] 本周跑赢现役 [{active}]（{score_line}），"
            f"连续第 {streak['count']}/{needed_streak} 周 — 再次确认后才切换。"
        )
    return state, note
