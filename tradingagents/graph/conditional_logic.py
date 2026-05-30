# TradingAgents/graph/conditional_logic.py

from tradingagents.agents.utils.agent_states import AgentState


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(self, max_debate_rounds=1, max_risk_discuss_rounds=1):
        """Initialize with configuration parameters."""
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds

    def should_continue_market(self, state: AgentState):
        """Determine if market analysis should continue."""
        messages = state["messages"]
        if not messages:
            return "Msg Clear Market"
        
        last_message = messages[-1]
        
        # If the model called a tool, go to tools
        if getattr(last_message, "tool_calls", []):
            return "tools_market"
        
        # If the model didn't call a tool, check if it produced a valid report
        # If report is empty (from our check in market_analyst_node), it's a plan/hallucination.
        # We force it to retry the node, but only up to 3 times.
        if not state.get("market_report"):
            if state.get("retry_count", 0) < 3:
                return "Market Analyst"
            else:
                # Max retries reached, skip this analyst to avoid infinite loop
                return "Msg Clear Market"
            
        return "Msg Clear Market"

    def should_continue_social(self, state: AgentState):
        """Determine if social media analysis should continue."""
        messages = state["messages"]
        if not messages:
            return "Msg Clear Social"
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", []):
            return "tools_social"
        if not state.get("sentiment_report"):
            if state.get("retry_count", 0) < 3:
                return "Social Analyst"
            else:
                return "Msg Clear Social"
        return "Msg Clear Social"

    def should_continue_news(self, state: AgentState):
        """Determine if news analysis should continue."""
        messages = state["messages"]
        if not messages:
            return "Msg Clear News"
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", []):
            return "tools_news"
        if not state.get("news_report"):
            if state.get("retry_count", 0) < 3:
                return "News Analyst"
            else:
                return "Msg Clear News"
        return "Msg Clear News"

    def should_continue_fundamentals(self, state: AgentState):
        """Determine if fundamentals analysis should continue."""
        messages = state["messages"]
        if not messages:
            return "Msg Clear Fundamentals"
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", []):
            return "tools_fundamentals"
        if not state.get("fundamentals_report"):
            if state.get("retry_count", 0) < 3:
                return "Fundamentals Analyst"
            else:
                return "Msg Clear Fundamentals"
        return "Msg Clear Fundamentals"

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue."""

        if (
            state["investment_debate_state"]["count"] >= 2 * self.max_debate_rounds
        ):  # 3 rounds of back-and-forth between 2 agents
            return "Research Manager"
        if state["investment_debate_state"]["current_response"].startswith("Bull"):
            return "Bear Researcher"
        return "Bull Researcher"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue."""
        if (
            state["risk_debate_state"]["count"] >= 3 * self.max_risk_discuss_rounds
        ):  # 3 rounds of back-and-forth between 3 agents
            return "Portfolio Manager"
        if state["risk_debate_state"]["latest_speaker"].startswith("Aggressive"):
            return "Conservative Analyst"
        if state["risk_debate_state"]["latest_speaker"].startswith("Conservative"):
            return "Neutral Analyst"
        return "Aggressive Analyst"

    def should_continue_portfolio(self, state: AgentState) -> str:
        """Determine if the portfolio manager needs to retry due to hallucination."""
        from langgraph.graph import END
        if not state.get("final_trade_decision"):
            if state.get("retry_count", 0) < 3:
                return "Portfolio Manager"
            else:
                return END
        return END
