"""Every decision must carry an explicit rating, and re-runs must agree.

Two guarantees are tested here:
  1. A decision whose text has no ``**Rating**:`` line gets one, so the rating
     is never inferred from prose that may argue the opposite.
  2. Temperature is pinned, so the same ticker on the same day does not
     produce a different decision on each run.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tradingagents.agents.schemas import PortfolioDecision, ResearchPlan, TraderProposal
from tradingagents.agents.utils.rating import analyze_rating
from tradingagents.agents.utils.structured import (
    build_json_instructions,
    ensure_rating_line,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client


# ── guaranteed rating line ───────────────────────────────────────────────────

# Long enough to clear the substantive-report length check in the PM node.
UNLABELLED = (
    "估值处于高位，客户集中度风险上升，前两大客户占营收比重超过六成。"
    "光模块价格竞争加剧，毛利率连续两个季度环比下滑，库存周转天数上升。"
    "管理层对下半年指引偏保守，且解禁窗口临近。"
    "综合来看，建议卖出锁定收益，待估值回落至合理区间再评估。"
)


def test_unlabelled_decision_gets_an_explicit_rating():
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="Sell")

    out = ensure_rating_line(UNLABELLED, llm, "Portfolio Manager")

    assert out.startswith("**Rating**: Sell")
    assert UNLABELLED in out
    # The rating is now authoritative rather than inferred from prose.
    assert analyze_rating(out).method == "label"


def test_already_labelled_decision_is_untouched():
    text = "**Rating**: Hold\n\n估值透支，建议卖出。"
    llm = MagicMock()
    assert ensure_rating_line(text, llm, "Portfolio Manager") == text
    llm.invoke.assert_not_called()


@pytest.mark.parametrize("answer", ["卖出", "garbage", "", "Maybe Sell or Hold"])
def test_unusable_repair_answer_leaves_text_unchanged(answer):
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=answer)
    out = ensure_rating_line(UNLABELLED, llm, "Portfolio Manager")
    if answer == "卖出":
        # Chinese is not one of the canonical words; the call is rejected.
        assert out == UNLABELLED
    else:
        assert out == UNLABELLED


@pytest.mark.parametrize("answer,expected", [
    ("Sell", "Sell"), ("  sell  ", "Sell"), ("**Buy**", "Buy"),
    ("Overweight.", "Overweight"), ("underweight", "Underweight"),
])
def test_repair_answer_is_normalised(answer, expected):
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=answer)
    out = ensure_rating_line(UNLABELLED, llm, "Portfolio Manager")
    assert out.startswith(f"**Rating**: {expected}")


def test_repair_failure_does_not_break_the_pipeline():
    llm = MagicMock()
    llm.invoke.side_effect = RuntimeError("provider down")
    assert ensure_rating_line(UNLABELLED, llm, "Portfolio Manager") == UNLABELLED


def test_empty_text_is_passed_through():
    llm = MagicMock()
    assert ensure_rating_line("", llm, "PM") == ""
    llm.invoke.assert_not_called()


def test_portfolio_manager_emits_a_labelled_decision_on_freetext_fallback():
    """The full node path: structured output unavailable, prose reply, and the
    stored decision still carries an authoritative rating."""
    from tradingagents.agents.managers.portfolio_manager import (
        create_portfolio_manager,
    )

    llm = MagicMock()
    llm.with_structured_output.side_effect = NotImplementedError("unsupported")
    llm.invoke.side_effect = [
        MagicMock(content=UNLABELLED),   # the decision itself
        MagicMock(content="Sell"),       # the rating repair call
    ]
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
        "past_context": "",
        "researcher_context": "",
        "reference_price": 0.0,
        "retry_count": 0,
    }
    result = create_portfolio_manager(llm)(state)
    decision = result["final_trade_decision"]
    assert decision.startswith("**Rating**: Sell")
    assert analyze_rating(decision).method == "label"


# ── an absent decision is a failure, not a Hold ──────────────────────────────

def test_empty_decision_is_not_stored_as_hold(tmp_path):
    """The PM ends with an empty decision after exhausting its retries, and
    parse_rating("") yields Hold — a call no analysis ever made."""
    from tradingagents.agents.utils.memory import TradingMemoryLog

    log = TradingMemoryLog({"memory_log_path": str(tmp_path / "m.md")})
    log.store_decision("0100.HK", "2026-07-24", "")
    log.store_decision("0100.HK", "2026-07-24", "   \n  ")
    assert log.load_entries() == []

    log.store_decision("0100.HK", "2026-07-24", "**Rating**: Sell\n\n理由充分。")
    assert [e["rating"] for e in log.load_entries()] == ["Sell"]


def test_run_reports_failure_when_no_decision_was_produced(tmp_path):
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = MagicMock(spec=TradingAgentsGraph)
    graph.config = {"checkpoint_enabled": False}
    graph.debug = False
    graph.memory_log = MagicMock()
    graph.memory_log.get_past_context.return_value = ""
    graph._build_researcher_context.return_value = ""
    graph.propagator = MagicMock()
    graph.propagator.create_initial_state.return_value = {}
    graph.propagator.get_graph_args.return_value = {}
    graph.graph = MagicMock()
    graph.graph.invoke.return_value = {
        "final_trade_decision": "", "retry_count": 3,
    }

    with pytest.raises(RuntimeError, match="produced no decision"):
        TradingAgentsGraph._run_graph(graph, "0100.HK", "2026-07-24")

    graph.memory_log.store_decision.assert_not_called()


# ── JSON-mode contract ───────────────────────────────────────────────────────

def test_json_instructions_enumerate_enum_values():
    text = build_json_instructions(PortfolioDecision)
    assert '"rating": one of "Buy", "Overweight", "Hold", "Underweight", "Sell"' in text
    assert '"executive_summary": string' in text
    assert '"price_target": number or null' in text


def test_json_instructions_for_other_schemas():
    assert '"recommendation": one of' in build_json_instructions(ResearchPlan)
    assert '"action": one of "Buy", "Hold", "Sell"' in build_json_instructions(
        TraderProposal
    )


def test_reasoning_models_use_json_mode_instead_of_losing_structure():
    """Falling back to free text forces the rating to be guessed, so a model
    that rejects tool calling gets JSON mode rather than nothing."""
    llm = create_llm_client(
        provider="deepseek", model="deepseek-v4-pro", api_key="x",
    ).get_llm()
    bound = llm.with_structured_output(PortfolioDecision)
    assert type(bound).__name__ == "_JsonModeStructured"


def test_json_mode_appends_the_contract_to_the_prompt():
    from tradingagents.llm_clients.openai_client import _JsonModeStructured

    inner = MagicMock()
    wrapper = _JsonModeStructured(inner, PortfolioDecision)

    wrapper.invoke("analyse 0100.HK")
    sent = inner.invoke.call_args[0][0]
    assert "analyse 0100.HK" in sent
    assert '"rating": one of' in sent

    inner.reset_mock()
    wrapper.invoke([("human", "go")])
    sent = inner.invoke.call_args[0][0]
    assert sent[0] == ("human", "go")
    assert '"rating": one of' in sent[-1][1]


# ── reproducibility ──────────────────────────────────────────────────────────

def test_temperature_defaults_to_zero():
    assert DEFAULT_CONFIG["llm_temperature"] == 0.0


def test_temperature_reaches_the_client():
    llm = create_llm_client(
        provider="deepseek", model="deepseek-v4-pro", api_key="x", temperature=0.0,
    ).get_llm()
    assert llm.temperature == 0.0


@pytest.mark.parametrize("model", ["gpt-5.4", "o1", "o3", "deepseek-reasoner"])
def test_temperature_not_forced_on_models_that_reject_it(model):
    """Reasoning families fix temperature internally and 400 on an explicit
    value, so ours must not be sent (langchain may still fill in its own)."""
    provider = "deepseek" if "deepseek" in model else "openai"
    llm = create_llm_client(
        provider=provider, model=model, api_key="x", temperature=0.0,
    ).get_llm()
    assert llm.temperature != 0.0


def test_graph_forwards_configured_temperature():
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    config = {**DEFAULT_CONFIG, "llm_temperature": 0.0}
    kwargs = TradingAgentsGraph._get_provider_kwargs(
        MagicMock(config=config)
    )
    assert kwargs["temperature"] == 0.0
