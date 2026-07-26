"""Structured output is mandatory for decision-making agents.

These agents issue the recommendation the user acts on. If the model cannot
return a validated, schema-typed decision, the run must fail — substituting
prose means the rating gets inferred from text that may argue the opposite.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tradingagents.agents.schemas import (
    PortfolioDecision,
    PortfolioRating,
    render_pm_decision,
)
from tradingagents.agents.utils.structured import (
    StructuredOutputUnavailable,
    bind_structured,
    invoke_structured,
)
from tradingagents.default_config import DEFAULT_CONFIG


def _decision(rating=PortfolioRating.SELL) -> PortfolioDecision:
    return PortfolioDecision(
        rating=rating,
        executive_summary="估值透支，分批离场。",
        investment_thesis="毛利率连续下滑，指引偏保守。",
    )


# ── the requirement is on by default ────────────────────────────────────────

def test_strict_mode_is_the_default():
    assert DEFAULT_CONFIG["require_structured_output"] is True


def test_bind_raises_when_the_model_cannot_do_structured_output():
    llm = MagicMock()
    llm.with_structured_output.side_effect = NotImplementedError("no tools")
    with pytest.raises(StructuredOutputUnavailable) as exc:
        bind_structured(llm, PortfolioDecision, "Portfolio Manager")
    # The message has to tell the user how to resolve it.
    assert "Portfolio Manager" in str(exc.value)
    assert "require_structured_output" in str(exc.value)


def test_invoke_raises_after_exhausting_attempts():
    structured = MagicMock()
    structured.invoke.side_effect = ValueError("malformed json")
    plain = MagicMock()

    with pytest.raises(StructuredOutputUnavailable, match="failed 3 times"):
        invoke_structured(
            structured, plain, "p", render_pm_decision, "Portfolio Manager",
            schema=PortfolioDecision,
        )
    assert structured.invoke.call_count == 3
    # Crucially, the prose path was never used.
    plain.invoke.assert_not_called()


def test_invoke_raises_when_no_binding_is_available():
    plain = MagicMock()
    with pytest.raises(StructuredOutputUnavailable, match="no structured-output"):
        invoke_structured(
            None, plain, "p", render_pm_decision, "PM", schema=PortfolioDecision,
        )
    plain.invoke.assert_not_called()


def test_none_result_counts_as_a_failure():
    structured = MagicMock()
    structured.invoke.return_value = None
    plain = MagicMock()
    with pytest.raises(StructuredOutputUnavailable):
        invoke_structured(
            structured, plain, "p", render_pm_decision, "PM",
            schema=PortfolioDecision,
        )
    plain.invoke.assert_not_called()


# ── transient failures are retried, not surrendered to ──────────────────────

def test_transient_failure_is_retried_with_the_same_prompt():
    structured = MagicMock()
    structured.invoke.side_effect = [ValueError("truncated"), _decision()]
    plain = MagicMock()

    out = invoke_structured(
        structured, plain, "analyse 0100.HK", render_pm_decision,
        "Portfolio Manager", schema=PortfolioDecision,
    )

    assert "**Rating**: Sell" in out
    assert structured.invoke.call_count == 2
    # Retries must not mutate the prompt — a different prompt is a different question.
    assert {c[0][0] for c in structured.invoke.call_args_list} == {"analyse 0100.HK"}
    plain.invoke.assert_not_called()


def test_success_on_the_final_attempt():
    structured = MagicMock()
    structured.invoke.side_effect = [
        ValueError("a"), ValueError("b"), _decision(PortfolioRating.BUY),
    ]
    out = invoke_structured(
        structured, MagicMock(), "p", render_pm_decision, "PM",
        schema=PortfolioDecision, max_attempts=3,
    )
    assert "**Rating**: Buy" in out


def test_max_attempts_is_configurable():
    structured = MagicMock()
    structured.invoke.side_effect = ValueError("boom")
    with pytest.raises(StructuredOutputUnavailable, match="failed 5 times"):
        invoke_structured(
            structured, MagicMock(), "p", render_pm_decision, "PM",
            schema=PortfolioDecision, max_attempts=5,
        )
    assert structured.invoke.call_count == 5


# ── the opt-out still exists, and is loud ───────────────────────────────────

def test_opt_out_allows_prose(lenient_structured_output):
    plain = MagicMock()
    plain.invoke.return_value = MagicMock(content="**Rating**: Hold\n\n观望。")
    out = invoke_structured(
        None, plain, "p", render_pm_decision, "PM", schema=PortfolioDecision,
    )
    assert out == "**Rating**: Hold\n\n观望。"


def test_opt_out_still_retries_structured_output_first(lenient_structured_output):
    structured = MagicMock()
    structured.invoke.side_effect = ValueError("bad")
    plain = MagicMock()
    plain.invoke.return_value = MagicMock(content="prose")

    invoke_structured(
        structured, plain, "p", render_pm_decision, "PM",
        schema=PortfolioDecision,
    )
    assert structured.invoke.call_count == 3
    plain.invoke.assert_called_once()


def test_opt_out_bind_returns_none_instead_of_raising(lenient_structured_output):
    llm = MagicMock()
    llm.with_structured_output.side_effect = NotImplementedError("no tools")
    assert bind_structured(llm, PortfolioDecision, "PM") is None


# ── the failure reaches the caller as a failed run ──────────────────────────

def test_portfolio_manager_node_propagates_the_failure():
    """The batch runner records a per-ticker error, so a failed decision shows
    up as a failure instead of a fabricated Hold."""
    from tradingagents.agents.managers.portfolio_manager import (
        create_portfolio_manager,
    )

    structured = MagicMock()
    structured.invoke.side_effect = ValueError("malformed json")
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    state = {
        "company_of_interest": "0100.HK",
        "investment_plan": "plan",
        "trader_investment_plan": "proposal",
        "risk_debate_state": {
            "history": "h", "aggressive_history": "a",
            "conservative_history": "c", "neutral_history": "n",
            "current_aggressive_response": "", "current_conservative_response": "",
            "current_neutral_response": "", "count": 1,
        },
        "past_context": "", "researcher_context": "",
        "reference_price": 0.0, "retry_count": 0,
    }
    with pytest.raises(StructuredOutputUnavailable):
        create_portfolio_manager(llm)(state)
