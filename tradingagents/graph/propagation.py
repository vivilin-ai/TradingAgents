# TradingAgents/graph/propagation.py

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)

logger = logging.getLogger(__name__)


class Propagator:
    """Handles state initialization and propagation through the graph."""

    def __init__(self, max_recur_limit=100):
        """Initialize with configuration parameters."""
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self,
        company_name: str,
        trade_date: str,
        past_context: str = "",
        researcher_context: str = "",
    ) -> Dict[str, Any]:
        """Create the initial state for the agent graph."""
        return {
            "messages": [("human", company_name)],
            "company_of_interest": company_name,
            "trade_date": str(trade_date),
            "past_context": past_context,
            "researcher_context": researcher_context,
            "investment_debate_state": InvestDebateState(
                {
                    "bull_history": "",
                    "bear_history": "",
                    "history": "",
                    "current_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "risk_debate_state": RiskDebateState(
                {
                    "aggressive_history": "",
                    "conservative_history": "",
                    "neutral_history": "",
                    "history": "",
                    "latest_speaker": "",
                    "current_aggressive_response": "",
                    "current_conservative_response": "",
                    "current_neutral_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "market_report": "",
            "fundamentals_report": "",
            "sentiment_report": "",
            "news_report": "",
            "retry_count": 0,
            "reference_price": self._fetch_reference_price(
                company_name, str(trade_date)
            ),
        }

    def _fetch_reference_price(self, ticker: str, trade_date: str) -> float:
        """Close of the last trading day at or before ``trade_date``.

        This is the baseline the hallucination check compares reported prices
        against, so it has to match the date being analysed. Using the live
        quote instead meant a run for a past date was validated against
        today's price: once the stock had moved more than the tolerance, every
        correctly-priced report was rejected and the run failed.
        """
        import yfinance as yf

        try:
            end = datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=1)
            # 10 days back covers weekends and holiday runs.
            start = end - timedelta(days=10)
            hist = yf.Ticker(ticker).history(
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                auto_adjust=True,
            )
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
            logger.warning(
                "No price for %s on or before %s; skipping the price sanity check",
                ticker, trade_date,
            )
        except Exception as exc:
            logger.warning("Could not fetch reference price for %s: %s", ticker, exc)
        return 0.0

    def get_graph_args(self, callbacks: Optional[List] = None) -> Dict[str, Any]:
        """Get arguments for the graph invocation.

        Args:
            callbacks: Optional list of callback handlers for tool execution tracking.
                       Note: LLM callbacks are handled separately via LLM constructor.
        """
        config = {"recursion_limit": self.max_recur_limit}
        if callbacks:
            config["callbacks"] = callbacks
        return {
            "stream_mode": "values",
            "config": config,
        }
