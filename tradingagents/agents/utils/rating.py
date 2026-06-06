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

# Matches "Rating: X" / "评级: X" / "rating - X" / "Rating: **X**"
# Tolerates markdown bold wrappers, colon or hyphen, full-width colon.
_RATING_LABEL_RE = re.compile(
    r"(?:rating|评级)\s*\*{0,2}\s*[:\-：]\s*\*{0,2}(\w+)",
    re.IGNORECASE,
)


def parse_rating(text: str, default: str = "Hold") -> str:
    """Heuristically extract a 5-tier rating from prose text.

    Two-pass strategy:
    1. Look for an explicit "Rating: X" / "评级: X" label line.
    2. Fall back to the first 5-tier rating word (English or Chinese) in the text.

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
                return en_rating

    return default
