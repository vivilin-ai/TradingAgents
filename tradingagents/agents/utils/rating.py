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
from typing import Tuple


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

# "持有X股" means "currently holding X shares" — not a Hold rating.
_HOLD_AS_POSITION_RE = re.compile(r"持有\s*\d")


def parse_rating(text: str, default: str = "Hold") -> str:
    """Heuristically extract a 5-tier rating from prose text.

    Two-pass strategy:
    1. Look for an explicit rating label (English or Chinese decision label).
    2. Fall back to the first 5-tier rating word (English or Chinese) in the text,
       skipping "持有X股" which means "currently holding X shares", not a Hold rating.

    Returns a canonical English rating string, or ``default`` if none found.
    """
    # Pass 1: explicit label
    for line in text.splitlines():
        m = _RATING_LABEL_RE.search(line)
        if m:
            word = m.group(1)
            if word.lower() in _RATING_SET:
                return word.capitalize()
            if word in _CHINESE_RATING_MAP:
                return _CHINESE_RATING_MAP[word]

    # Pass 2: first rating word anywhere in text
    for line in text.splitlines():
        for word in line.lower().split():
            clean = word.strip("*:.,（）()【】")
            if clean in _RATING_SET:
                return clean.capitalize()
        for zh_word, en_rating in _CHINESE_RATING_MAP.items():
            if zh_word in line:
                # Skip "持有X股" (currently holding X shares) — not a rating signal
                if zh_word == "持有" and _HOLD_AS_POSITION_RE.search(line):
                    continue
                return en_rating

    return default
