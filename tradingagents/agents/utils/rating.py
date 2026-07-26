"""Shared 5-tier rating vocabulary and a deterministic heuristic parser.

The same five-tier scale (Buy, Overweight, Hold, Underweight, Sell) is used by:
- The Research Manager (investment plan recommendation)
- The Portfolio Manager (final position decision)
- The signal processor (rating extracted for downstream consumers)
- The memory log (rating tag stored alongside each decision entry)

Centralising it here avoids drift between those call sites.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple


# Canonical, ordered 5-tier scale (most bullish to most bearish).
RATINGS_5_TIER: Tuple[str, ...] = (
    "Buy", "Overweight", "Hold", "Underweight", "Sell",
)

_RATING_SET = {r.lower() for r in RATINGS_5_TIER}

# Chinese equivalents mapped to canonical English ratings.
_CHINESE_RATING_MAP: dict[str, str] = {
    "买入": "Buy",
    "增持": "Overweight",
    "持有": "Hold",
    "中性": "Hold",
    "减持": "Underweight",
    "卖出": "Sell",
}

# Matches rating labels in English and Chinese, including free-text PM output.
# Handles: "Rating: X", "评级: X", "最终交易决策: X", "最终决策: X", "交易决策: X"
_RATING_LABEL_RE = re.compile(
    r"(?:rating|评级|最终交易决策|最终决策|交易决策)\s*\*{0,2}\s*[:\-：]\s*\*{0,2}(\w+)",
    re.IGNORECASE,
)

# ── Fallback scanning ────────────────────────────────────────────────────────
# Terms are located by position in the text, never by dict order: a bearish
# sentence like "持有成本偏高，建议卖出" must resolve to Sell, and iterating a
# mapping would have returned whichever key happened to come first.

# "持有" also heads ordinary noun phrases (持有成本 / 持有者 / 持有100股) that say
# nothing about the recommendation, so those compounds are excluded.
_HOLD_NOT_A_RATING = r"(?!\s*\d|成本|者|人|量|比例|市值|份额|价值|期限|收益)"

_ZH_TERM_PATTERNS: tuple[tuple[str, str], ...] = (
    ("买入", "Buy"),
    ("增持", "Overweight"),
    (f"持有{_HOLD_NOT_A_RATING}", "Hold"),
    ("中性", "Hold"),
    ("减持", "Underweight"),
    ("卖出", "Sell"),
    ("清仓", "Sell"),
)

_ZH_SCAN_RE = re.compile(
    "|".join(f"(?P<zh{i}>{pat})" for i, (pat, _) in enumerate(_ZH_TERM_PATTERNS))
)
_ZH_GROUP_TO_RATING = {
    f"zh{i}": rating for i, (_, rating) in enumerate(_ZH_TERM_PATTERNS)
}

_EN_SCAN_RE = re.compile(
    r"\b(buy|overweight|hold|underweight|sell)\b", re.IGNORECASE
)

# A recommendation that is being ruled out ("不建议买入", "avoid buying") must
# not be read as that recommendation.
_ZH_NEGATIONS = ("不", "未", "勿", "别", "避免", "谨慎", "无需", "切忌", "切勿")
_EN_NEGATIONS = ("not", "avoid", "no", "never", "without", "rather than", "instead of")


# Negation scope ends at the clause boundary: in "不建议买入，建议卖出" the 不
# governs 买入 only, and letting it leak forward would discard the real call.
_CLAUSE_BREAK_RE = re.compile(r"[，。；、！？：,.;!?:\n]")


def _is_negated(text: str, start: int) -> bool:
    """Whether the term at ``start`` sits inside a negation in its own clause."""
    window = text[max(0, start - 12):start]
    window = _CLAUSE_BREAK_RE.split(window)[-1]
    if any(neg in window for neg in _ZH_NEGATIONS):
        return True
    lowered = window.lower()
    return any(neg in lowered for neg in _EN_NEGATIONS)


def _scan_first_rating(text: str) -> Optional[str]:
    """Earliest non-negated rating term in ``text``, or None."""
    hits: list[tuple[int, str]] = []

    for match in _ZH_SCAN_RE.finditer(text):
        group = match.lastgroup
        if group and not _is_negated(text, match.start()):
            hits.append((match.start(), _ZH_GROUP_TO_RATING[group]))

    for match in _EN_SCAN_RE.finditer(text):
        if not _is_negated(text, match.start()):
            hits.append((match.start(), match.group(1).capitalize()))

    if not hits:
        return None
    hits.sort(key=lambda h: h[0])
    return hits[0][1]


def parse_rating_or_none(text: str) -> Optional[str]:
    """Extract a 5-tier rating from prose, or None when the text carries none.

    Two-pass strategy:
    1. An explicit rating label (English or Chinese decision label) always wins;
       structured-output agents render one, so this is the normal path.
    2. Otherwise scan the prose and take the earliest rating term that is not
       negated and not part of an unrelated compound.

    Returning None lets callers distinguish "the model said Hold" from "no
    rating could be found" — conflating the two silently relabels a bearish
    write-up as Hold.
    """
    if not text:
        return None

    # Pass 1: explicit label
    for line in text.splitlines():
        m = _RATING_LABEL_RE.search(line)
        if m:
            word = m.group(1)
            if word.lower() in _RATING_SET:
                return word.capitalize()
            if word in _CHINESE_RATING_MAP:
                return _CHINESE_RATING_MAP[word]

    # Pass 2: earliest non-negated rating term in the prose
    return _scan_first_rating(text)


def parse_rating(text: str, default: str = "Hold") -> str:
    """Like :func:`parse_rating_or_none` but substitutes ``default`` for None."""
    rating = parse_rating_or_none(text)
    return rating if rating is not None else default
