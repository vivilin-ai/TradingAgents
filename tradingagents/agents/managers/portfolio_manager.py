"""Portfolio Manager: synthesises the risk-analyst debate into the final decision.

Uses LangChain's ``with_structured_output`` so the LLM produces a typed
``PortfolioDecision`` directly, in a single call.  The result is rendered
back to markdown for storage in ``final_trade_decision`` so memory log,
CLI display, and saved reports continue to consume the same shape they do
today.

The rating therefore comes from a schema enum, not from prose.  If the model
cannot return a validated decision the node raises rather than improvising:
this is the agent that issues the recommendation the user acts on, so a
failed run must look like a failure.
"""

from __future__ import annotations

import logging

from tradingagents.agents.schemas import PortfolioDecision, render_pm_decision
from tradingagents.agents.utils.rating import parse_rating_or_none
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    ensure_rating_line,
    invoke_structured,
)

logger = logging.getLogger(__name__)


def create_portfolio_manager(llm):
    structured_llm = bind_structured(llm, PortfolioDecision, "Portfolio Manager")

    def portfolio_manager_node(state) -> dict:
        instrument_context = build_instrument_context(state["company_of_interest"])

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        research_plan = state["investment_plan"]
        trader_plan = state["trader_investment_plan"]

        past_context = state.get("past_context", "")
        lessons_line = (
            f"- Lessons from prior decisions and outcomes:\n{past_context}\n"
            if past_context
            else ""
        )

        prompt = f"""As the Portfolio Manager, synthesize the risk analysts' debate and deliver the final trading decision.

{instrument_context}

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction to enter or add to position
- **Overweight**: Favorable outlook, gradually increase exposure
- **Hold**: Maintain current position, no action needed
- **Underweight**: Reduce exposure, take partial profits
- **Sell**: Exit position or avoid entry

**Context:**
- Research Manager's investment plan: **{research_plan}**
- Trader's transaction proposal: **{trader_plan}**
{lessons_line}
**Risk Analysts Debate History:**
{history}

---

Be decisive and ground every conclusion in specific evidence from the analysts.{get_language_instruction()}"""

        final_trade_decision = invoke_structured(
            structured_llm,
            llm,
            prompt,
            render_pm_decision,
            "Portfolio Manager",
            schema=PortfolioDecision,
        )

        # Every stored decision must carry an explicit rating: an inferred one
        # can contradict the reasoning it was read from, and it silently
        # becomes Hold when nothing parses.
        final_trade_decision = ensure_rating_line(
            final_trade_decision, llm, "Portfolio Manager"
        )
        if parse_rating_or_none(final_trade_decision) is None:
            logger.warning(
                "Portfolio Manager produced no parseable rating for %s; "
                "downstream consumers will fall back to Hold",
                state.get("company_of_interest", "?"),
            )

        from tradingagents.agents.utils.agent_utils import verify_report_hallucination
        ref_price = state.get("reference_price", 0.0)
        ticker = state.get("company_of_interest", "")
        
        # In final report, we perform strict price check
        if verify_report_hallucination(final_trade_decision, ref_price, ticker=ticker, strict=True):
            retry_val = 0
        else:
            final_trade_decision = ""
            retry_val = state.get("retry_count", 0) + 1

        new_risk_debate_state = {
            "judge_decision": final_trade_decision,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_trade_decision,
            "retry_count": retry_val
        }

    return portfolio_manager_node
