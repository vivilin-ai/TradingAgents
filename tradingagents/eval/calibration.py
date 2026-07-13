"""Calibration block + curated lessons pool (P3).

The calibration block is deterministic text built from scorecard stats and
persistent biases. The evaluate run writes it to ``calibration_path``; the
analysis pipeline reads it at run time and injects it into agent prompts.
Prompts are English, so the block is English.

The lessons pool is a small curated list maintained by weekly
meta-reflection: merged, deduplicated, falsified lessons dropped, capped.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from tradingagents.agents.utils.rating import RATINGS_5_TIER

logger = logging.getLogger(__name__)


def build_calibration_block(
    stats: dict[int, dict[str, dict[str, Any]]],
    persistent_biases: list[dict],
    min_samples: int,
    window_weeks: int,
    as_of: str,
) -> str:
    """English calibration text for prompt injection. Empty string when no
    tier has enough samples (nothing trustworthy to say)."""
    horizons = sorted(stats.keys())
    if not horizons:
        return ""
    tier_lines = []
    for rating in RATINGS_5_TIER:
        cells = []
        for h in horizons:
            s = stats[h][rating]
            if s["n"] >= min_samples:
                hit = f", hit rate {s['hit_rate']:.0%}" if s["hit_rate"] is not None else ""
                cells.append(f"{h}d avg alpha {s['avg_eff_alpha']:+.2%}{hit}")
        n = stats[horizons[0]][rating]["n"]
        if cells:
            tier_lines.append(f"- Your {rating} calls ({n} samples): " + "; ".join(cells))
        elif n:
            tier_lines.append(f"- Your {rating} calls: only {n} samples — insufficient, no conclusion.")
    if not any(stats[h][r]["n"] >= min_samples for h in horizons for r in RATINGS_5_TIER):
        return ""

    lines = [
        f"[Decision calibration data | rolling {window_weeks} weeks as of {as_of}]",
        "Realized performance of your own past rating calls (effective alpha vs "
        "benchmark; bearish tiers sign-flipped so positive = advice was right):",
        *tier_lines,
    ]
    if persistent_biases:
        lines.append("Confirmed systematic biases (recurred across evaluations — correct for these):")
        lines += [f"- WARNING: {b['message']}" for b in persistent_biases]
    return "\n".join(lines)


def write_calibration(path: str, block: str) -> None:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(block, encoding="utf-8")


def load_calibration(path: Optional[str]) -> str:
    if not path:
        return ""
    p = Path(path).expanduser()
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


# ── Lessons pool ─────────────────────────────────────────────────────────────

class LessonsPool:
    """Curated cross-ticker lessons, one markdown bullet per lesson."""

    def __init__(self, path: Optional[str], max_entries: int = 20):
        self._path = Path(path).expanduser() if path else None
        self._max = max_entries

    def load(self) -> list[str]:
        if not self._path or not self._path.exists():
            return []
        lessons = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("- "):
                lessons.append(line[2:].strip())
        return lessons

    def save(self, lessons: list[str]) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        deduped: list[str] = []
        for lesson in lessons:
            lesson = lesson.strip().lstrip("-• ").strip()
            if lesson and lesson not in deduped:
                deduped.append(lesson)
        # Newest lessons are appended last by the meta-reflection; keep the tail.
        deduped = deduped[-self._max:]
        self._path.write_text(
            "\n".join(f"- {lesson}" for lesson in deduped) + "\n", encoding="utf-8"
        )

    def as_prompt_block(self) -> str:
        lessons = self.load()
        if not lessons:
            return ""
        return "[Curated lessons from past outcomes]\n" + "\n".join(
            f"- {lesson}" for lesson in lessons
        )
