"""Regression tests: the extracted rating must match what the prose argues.

A bearish write-up used to come back tagged Hold (or even Buy) because the
fallback scanner walked a mapping in dict order, ignored negation, and
matched 持有 inside ordinary noun phrases such as 持有成本.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tradingagents.agents.schemas import (
    PortfolioDecision,
    PortfolioRating,
    ResearchPlan,
    TraderProposal,
)
from tradingagents.agents.utils.rating import parse_rating, parse_rating_or_none
from tradingagents.agents.utils.structured import (
    build_format_instructions,
    invoke_structured,
)


# ── the reported contradiction ───────────────────────────────────────────────

@pytest.mark.parametrize(
    "text,expected",
    [
        # 持有成本 is a cost, not a Hold rating; the call is 卖出.
        ("综合来看，持有成本偏高，估值透支，建议卖出并规避风险。", "Sell"),
        ("当前持有者应尽快离场，卖出为宜。", "Sell"),
        ("鉴于长期持有价值有限，我们给出卖出评级。", "Sell"),
        ("持有比例过高，建议减持。", "Underweight"),
        # Negation must not turn a rejected option into the verdict.
        ("短期不建议买入，中期建议卖出。", "Sell"),
        ("不宜增持，建议卖出。", "Sell"),
        ("We do not recommend buying; sell into strength.", "Sell"),
        # …but a negation in a later clause must not eat the real call.
        ("维持持有评级，不建议卖出。", "Hold"),
        ("Maintain hold; avoid selling here.", "Hold"),
        # Genuine ratings still parse.
        ("建议买入，目标价上调。", "Buy"),
        ("基本面稳健，建议增持。", "Overweight"),
        ("风险显著，建议清仓离场。", "Sell"),
        ("维持持有评级，等待更好的卖出时机。", "Hold"),
        # A real holding line is not a rating.
        ("用户持有100股，建议卖出。", "Sell"),
    ],
)
def test_prose_rating_matches_the_argument(text, expected):
    assert parse_rating(text) == expected


def test_explicit_label_always_wins_over_prose():
    text = "**Rating**: Hold\n\n估值透支，建议卖出并规避风险。"
    assert parse_rating(text) == "Hold"


@pytest.mark.parametrize(
    "label,expected",
    [
        ("评级：减持", "Underweight"),
        ("最终交易决策: Sell", "Sell"),
        ("**Rating**: Overweight", "Overweight"),
        ("交易决策：卖出", "Sell"),
    ],
)
def test_explicit_labels_parse(label, expected):
    assert parse_rating(label) == expected


# ── missing rating must be distinguishable from a real Hold ──────────────────

def test_missing_rating_returns_none_instead_of_silent_hold():
    assert parse_rating_or_none("本周成交量下降，波动率上升。") is None
    assert parse_rating_or_none("") is None
    # The compatibility wrapper still defaults, but callers can now tell.
    assert parse_rating("本周成交量下降。") == "Hold"


# ── opted-in free-text path keeps the rating line ────────────────────────────

def test_format_instructions_enumerate_enum_choices():
    text = build_format_instructions(PortfolioDecision)
    assert "**Rating**: exactly one of Buy / Overweight / Hold / Underweight / Sell" in text
    assert "**Executive Summary**" in text
    assert "omit this line" in text  # optional fields flagged as such


def test_format_instructions_for_other_schemas():
    assert "**Recommendation**: exactly one of" in build_format_instructions(ResearchPlan)
    assert "**Action**: exactly one of Buy / Hold / Sell" in build_format_instructions(
        TraderProposal
    )


def test_fallback_prompt_carries_format_instructions(lenient_structured_output):
    """Without the schema's field descriptions the fallback produced
    unlabelled prose, which is what forced the rating to be guessed.
    Reachable only when structured output has been explicitly waived."""
    plain = MagicMock()
    plain.invoke.return_value = MagicMock(content="**Rating**: Sell\n\n估值透支。")

    out = invoke_structured(
        None, plain, "analyse 0100.HK", lambda d: "", "Portfolio Manager",
        schema=PortfolioDecision,
    )

    sent = plain.invoke.call_args[0][0]
    assert "**Rating**: exactly one of" in sent
    assert "analyse 0100.HK" in sent
    assert parse_rating(out) == "Sell"


def test_fallback_appends_instructions_to_message_lists(lenient_structured_output):
    plain = MagicMock()
    plain.invoke.return_value = MagicMock(content="**Action**: Sell")
    invoke_structured(
        None, plain, [("human", "go")], lambda d: "", "Trader", schema=TraderProposal,
    )
    sent = plain.invoke.call_args[0][0]
    assert sent[0] == ("human", "go")
    assert "**Action**: exactly one of" in sent[-1][1]


def test_structured_path_is_unchanged_and_authoritative():
    """When structured output works the enum is the rating — no prose parsing."""
    structured = MagicMock()
    structured.invoke.return_value = PortfolioDecision(
        rating=PortfolioRating.SELL,
        executive_summary="持有成本偏高，建议离场。",
        investment_thesis="估值透支。",
    )
    from tradingagents.agents.schemas import render_pm_decision

    out = invoke_structured(
        structured, MagicMock(), "p", render_pm_decision, "Portfolio Manager",
        schema=PortfolioDecision,
    )
    assert "**Rating**: Sell" in out
    assert parse_rating(out) == "Sell"
