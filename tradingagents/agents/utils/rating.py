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
from typing import NamedTuple, Optional, Tuple


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


# Phrases that introduce the verdict. A long write-up often quotes an earlier
# call before revising it ("上周给出卖出评级 … 本次上调至增持"), so the earliest
# term in the text is not the conclusion; a term in a concluding clause is.
_CONCLUSION_MARKERS = (
    "综上", "综合", "因此", "所以", "结论", "最终", "建议", "总结", "评级",
    "维持", "上调", "下调", "给予", "给出", "决策", "调整为", "我们认为",
    "therefore", "conclusion", "recommend", "maintain", "overall",
    "in sum", "we rate", "downgrade", "upgrade", "verdict",
)


def _clause_spans(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for match in _CLAUSE_BREAK_RE.finditer(text):
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, len(text)))
    return spans


def _clause_index(pos: int, spans: list[tuple[int, int]]) -> int:
    for i, (start, end) in enumerate(spans):
        if start <= pos <= end:
            return i
    return len(spans) - 1


def _has_marker(text: str, span: tuple[int, int]) -> bool:
    window = text[span[0]:span[1]].lower()
    return any(marker in window for marker in _CONCLUSION_MARKERS)


def _in_conclusion_context(
    text: str, pos: int, spans: list[tuple[int, int]], hit_clauses: set[int]
) -> bool:
    """Whether the term at ``pos`` sits in (or right after) a concluding clause.

    A marker in the preceding clause carries over ("综合以上因素，增持"), but only
    when that clause states no rating of its own — otherwise "维持持有评级，等待
    卖出时机" would lend 维持 to 卖出 and invert the verdict.
    """
    i = _clause_index(pos, spans)
    if _has_marker(text, spans[i]):
        return True
    if i and (i - 1) not in hit_clauses:
        return _has_marker(text, spans[i - 1])
    return False


def _scan_prose_rating(text: str) -> tuple[Optional[str], str, int]:
    """Best-effort rating from prose.

    Returns (rating, method, position). ``method`` is ``"conclusion"`` when the
    term was found in a concluding clause — the last one wins, since a revised
    call comes after the one it replaces — or ``"prose"`` for the weaker
    earliest-term guess, which callers should treat as low confidence.
    """
    hits: list[tuple[int, str]] = []

    for match in _ZH_SCAN_RE.finditer(text):
        group = match.lastgroup
        if group and not _is_negated(text, match.start()):
            hits.append((match.start(), _ZH_GROUP_TO_RATING[group]))

    for match in _EN_SCAN_RE.finditer(text):
        if not _is_negated(text, match.start()):
            hits.append((match.start(), match.group(1).capitalize()))

    if not hits:
        return None, "none", -1
    hits.sort(key=lambda h: h[0])

    spans = _clause_spans(text)
    hit_clauses = {_clause_index(pos, spans) for pos, _ in hits}
    concluding = [
        h for h in hits if _in_conclusion_context(text, h[0], spans, hit_clauses)
    ]
    if concluding:
        pos, rating = concluding[-1]
        return rating, "conclusion", pos
    pos, rating = hits[0]
    return rating, "prose", pos


class RatingEvidence(NamedTuple):
    """A rating plus how it was determined, so callers can judge confidence.

    ``method``:
      ``"label"``      — an explicit rating label; authoritative.
      ``"conclusion"`` — a term in a concluding clause; usually right.
      ``"prose"``      — earliest term anywhere; a guess, treat with suspicion.
      ``"none"``       — the text states no rating.
    """

    rating: Optional[str]
    method: str
    snippet: str

    @property
    def is_authoritative(self) -> bool:
        return self.method == "label"


def _snippet(text: str, pos: int, width: int = 40) -> str:
    if pos < 0:
        return ""
    start, end = max(0, pos - width), min(len(text), pos + width)
    return ("…" if start else "") + text[start:end].replace("\n", " ") + ("…" if end < len(text) else "")


def analyze_rating(text: str) -> RatingEvidence:
    """Extract a rating and report how it was found.

    1. An explicit rating label always wins; structured-output agents render
       one, so this is the normal path and the only authoritative one.
    2. Otherwise fall back to scanning the prose, preferring a term in a
       concluding clause over the earliest term in the document.
    """
    if not text:
        return RatingEvidence(None, "none", "")

    for line in text.splitlines():
        m = _RATING_LABEL_RE.search(line)
        if m:
            word = m.group(1)
            rating = None
            if word.lower() in _RATING_SET:
                rating = word.capitalize()
            elif word in _CHINESE_RATING_MAP:
                rating = _CHINESE_RATING_MAP[word]
            if rating:
                return RatingEvidence(rating, "label", line.strip()[:120])

    rating, method, pos = _scan_prose_rating(text)
    return RatingEvidence(rating, method, _snippet(text, pos))


def parse_rating_or_none(text: str) -> Optional[str]:
    """Extract a 5-tier rating from prose, or None when the text carries none.

    Returning None lets callers distinguish "the model said Hold" from "no
    rating could be found" — conflating the two silently relabels a bearish
    write-up as Hold.
    """
    return analyze_rating(text).rating


def parse_rating(text: str, default: str = "Hold") -> str:
    """Like :func:`parse_rating_or_none` but substitutes ``default`` for None."""
    rating = parse_rating_or_none(text)
    return rating if rating is not None else default
