"""Scorecard: tier stats, monotonicity, bias detection, markdown rendering (P1).

All numbers here are computed deterministically from the ledger — no LLM.
Bearish tiers (Underweight, Sell) are advice to reduce/avoid, so their
"effective alpha" flips sign: a falling stock makes the advice right.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from tradingagents.agents.utils.rating import RATINGS_5_TIER

BULLISH = ("Buy", "Overweight")
BEARISH = ("Underweight", "Sell")


def _in_window(entry: dict, as_of: str, window_weeks: int) -> bool:
    if not window_weeks:
        return True
    cutoff = datetime.strptime(as_of, "%Y-%m-%d") - timedelta(weeks=window_weeks)
    return datetime.strptime(entry["trade_date"], "%Y-%m-%d") >= cutoff


def compute_tier_stats(
    entries: list[dict],
    horizons: list[int],
    as_of: str,
    window_weeks: int = 12,
) -> dict[int, dict[str, dict[str, Any]]]:
    """{horizon: {rating: {n, hit_rate, avg_alpha, avg_raw, avg_eff_alpha}}}.

    hit_rate: fraction of calls whose alpha sign matched the advice direction
    (bullish -> alpha > 0, bearish -> alpha < 0). Hold has no direction, so
    its hit_rate is None.
    """
    windowed = [e for e in entries if _in_window(e, as_of, window_weeks)]
    stats: dict[int, dict[str, dict[str, Any]]] = {}
    for h in horizons:
        key = str(h)
        per_rating: dict[str, dict[str, Any]] = {}
        for rating in RATINGS_5_TIER:
            outcomes = [
                e["outcomes"][key]
                for e in windowed
                if e.get("rating") == rating and key in e.get("outcomes", {})
            ]
            if not outcomes:
                per_rating[rating] = {
                    "n": 0, "hit_rate": None, "avg_alpha": None,
                    "avg_raw": None, "avg_eff_alpha": None,
                }
                continue
            alphas = [o["alpha"] for o in outcomes]
            raws = [o["raw"] for o in outcomes]
            sign = -1.0 if rating in BEARISH else 1.0
            eff = [sign * a for a in alphas]
            if rating == "Hold":
                hit_rate = None
            else:
                hit_rate = sum(1 for a in eff if a > 0) / len(eff)
            per_rating[rating] = {
                "n": len(outcomes),
                "hit_rate": hit_rate,
                "avg_alpha": sum(alphas) / len(alphas),
                "avg_raw": sum(raws) / len(raws),
                "avg_eff_alpha": sum(eff) / len(eff),
            }
        stats[h] = per_rating
    return stats


def check_monotonicity(
    tier_stats: dict[str, dict[str, Any]], min_samples: int
) -> Optional[bool]:
    """Is avg_alpha monotone non-increasing from Buy down to Sell?

    Only tiers with >= min_samples participate. Returns None when fewer than
    two tiers qualify (not enough evidence either way).
    """
    qualified = [
        (rating, s["avg_alpha"])
        for rating, s in ((r, tier_stats[r]) for r in RATINGS_5_TIER)
        if s["n"] >= min_samples and s["avg_alpha"] is not None
    ]
    if len(qualified) < 2:
        return None
    values = [v for _, v in qualified]
    return all(values[i] >= values[i + 1] for i in range(len(values) - 1))


def detect_biases(
    stats: dict[int, dict[str, dict[str, Any]]],
    min_samples: int,
    alpha_threshold: float,
) -> list[dict[str, str]]:
    """Systematic-bias candidates: a tier whose avg effective alpha is
    materially negative on a horizon, with enough samples.

    Returns [{code, message}]. ``code`` is stable across weeks so the
    two-consecutive-evals rule in the evaluator can track persistence.
    """
    biases = []
    for h, per_rating in stats.items():
        for rating, s in per_rating.items():
            if rating == "Hold" or s["n"] < min_samples:
                continue
            if s["avg_eff_alpha"] is not None and s["avg_eff_alpha"] < -alpha_threshold:
                direction = "bearish" if rating in BEARISH else "bullish"
                biases.append({
                    "code": f"{rating.lower()}_{h}d_negative",
                    "message": (
                        f"{rating} calls average {s['avg_eff_alpha']:+.2%} effective alpha "
                        f"at {h}d over {s['n']} samples — the {direction} conviction at this "
                        f"tier is systematically wrong at this horizon."
                    ),
                })
    return biases


def best_and_worst(
    entries: list[dict], horizon: int, as_of: str, window_weeks: int, k: int = 3
) -> tuple[list[dict], list[dict]]:
    """Top/bottom-k decisions by effective alpha at the given horizon."""
    key = str(horizon)
    scored = []
    for e in entries:
        if key not in e.get("outcomes", {}) or not _in_window(e, as_of, window_weeks):
            continue
        sign = -1.0 if e.get("rating") in BEARISH else 1.0
        scored.append((sign * e["outcomes"][key]["alpha"], e))
    scored.sort(key=lambda t: t[0], reverse=True)
    best = [e for _, e in scored[:k]]
    worst = [e for _, e in scored[-k:]][::-1] if len(scored) > k else []
    return best, worst


# ── Rendering ────────────────────────────────────────────────────────────────

def _pct(v: Optional[float]) -> str:
    return f"{v:+.2%}" if v is not None else "—"


def _rate(v: Optional[float]) -> str:
    return f"{v:.0%}" if v is not None else "—"


def render_scorecard_md(
    as_of: str,
    stats: dict[int, dict[str, dict[str, Any]]],
    monotonic: Optional[bool],
    biases: list[dict],
    persistent_biases: list[dict],
    sim_summary: Optional[dict],
    iteration_note: str,
    window_weeks: int,
    min_samples: int,
    entries: list[dict],
) -> str:
    horizons = sorted(stats.keys())
    lines = [
        f"# 周度记分卡 · {as_of}",
        "",
        f"统计窗口：滚动 {window_weeks} 周 · 口径：次日开盘执行、alpha 相对基准 · "
        f"每档最小样本 {min_samples}",
        "",
        "## 评级分档表现",
        "",
    ]
    header = "| 评级 | " + " | ".join(
        f"次数({h}d) | 命中率({h}d) | 有效alpha({h}d)" for h in horizons
    ) + " |"
    sep = "|" + "---|" * (1 + 3 * len(horizons))
    lines += [header, sep]
    for rating in RATINGS_5_TIER:
        cells = [rating]
        for h in horizons:
            s = stats[h][rating]
            cells += [str(s["n"]), _rate(s["hit_rate"]), _pct(s["avg_eff_alpha"])]
        lines.append("| " + " | ".join(cells) + " |")

    lines += ["", "## 评级信息含量（单调性）", ""]
    if monotonic is None:
        lines.append(f"样本不足（不足两个评级档达到 {min_samples} 条），暂不判定。")
    elif monotonic:
        lines.append("✅ 各档平均 alpha 满足 Buy ≥ Overweight ≥ Hold ≥ Underweight ≥ Sell 的单调排序。")
    else:
        lines.append("⚠️ 档位单调性不成立 — 评级信息含量存疑，优先排查下方偏差。")

    lines += ["", "## 系统性偏差", ""]
    if persistent_biases:
        lines.append("连续两次评估复现（已注入校准块）：")
        lines += [f"- ⚠️ {b['message']}" for b in persistent_biases]
    new_only = [b for b in biases if b["code"] not in {p["code"] for p in persistent_biases}]
    if new_only:
        lines.append("本次新检出（下次复现才会告警）：")
        lines += [f"- {b['message']}" for b in new_only]
    if not biases and not persistent_biases:
        lines.append("未检出达到阈值的系统性偏差。")

    if sim_summary:
        lines += ["", "## 建议跟随模拟组合", ""]
        lines += [
            f"- 组合累计收益：{_pct(sim_summary.get('total_return'))}"
            f"（基准 {sim_summary.get('benchmark', 'SPY')}：{_pct(sim_summary.get('benchmark_return'))}，"
            f"等权持有：{_pct(sim_summary.get('equal_weight_return'))}）",
            f"- 滚动 {window_weeks} 周周均 alpha：{_pct(sim_summary.get('mean_weekly_alpha'))}",
            f"- 滚动 {window_weeks} 周信息比率（北极星）：" + (
                f"{sim_summary['ir']:.2f}" if sim_summary.get("ir") is not None else "—"
            ),
            f"- 最大回撤：{_pct(sim_summary.get('max_drawdown'))}"
            f" · 周胜率：{_rate(sim_summary.get('weekly_win_rate'))}",
            f"- 现役评级→仓位映射：{sim_summary.get('active_params', 'default')}",
        ]

    if horizons:
        h0 = horizons[0]
        best, worst = best_and_worst(entries, h0, as_of, window_weeks)
        if best:
            lines += ["", f"## 最好 / 最差决策（{h0}d 有效 alpha）", ""]
            for e in best:
                o = e["outcomes"][str(h0)]
                lines.append(f"- ✅ {e['trade_date']} {e['ticker']} {e['rating']}: alpha {_pct(o['alpha'])}")
            for e in worst:
                o = e["outcomes"][str(h0)]
                lines.append(f"- ❌ {e['trade_date']} {e['ticker']} {e['rating']}: alpha {_pct(o['alpha'])}")

    if iteration_note:
        lines += ["", "## 参数迭代", "", iteration_note]

    lines.append("")
    return "\n".join(lines)


def render_telegram_summary(
    as_of: str,
    stats: dict[int, dict[str, dict[str, Any]]],
    persistent_biases: list[dict],
    sim_summary: Optional[dict],
    iteration_note: str,
) -> str:
    """Short plain-text digest for the Telegram push."""
    lines = [f"📈 周度评估完成 · {as_of}"]
    if sim_summary:
        ir = sim_summary.get("ir")
        lines.append(
            f"模拟组合累计 {_pct(sim_summary.get('total_return'))}"
            f" vs 基准 {_pct(sim_summary.get('benchmark_return'))}"
            + (f" · IR {ir:.2f}" if ir is not None else "")
        )
    h = sorted(stats.keys())[0] if stats else None
    if h is not None:
        parts = []
        for rating in RATINGS_5_TIER:
            s = stats[h][rating]
            if s["n"]:
                parts.append(f"{rating} {s['n']}次 {_pct(s['avg_eff_alpha'])}")
        if parts:
            lines.append(f"{h}d 有效alpha：" + "；".join(parts))
    for b in persistent_biases:
        lines.append(f"⚠️ {b['message']}")
    if iteration_note:
        lines.append(iteration_note)
    return "\n".join(lines)
