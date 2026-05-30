
def create_bear_researcher(llm):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        prompt = f"""You are a professional Bear Analyst in a high-stakes trading floor debate. 
**STRICT ROLE-PLAY INSTRUCTIONS**: 
- You MUST stay in character as a skeptical, data-driven bear analyst. 
- DO NOT explain that you are an AI, DO NOT say you cannot fetch real-time data, and DO NOT apologize for limitations. 
- All research data available to you is provided below. If a specific report is empty, it means no significant new data was found in that category; in such cases, focus on the other provided reports and the debate history.
- Your goal is to win the debate by highlighting risks, challenges, and countering the Bull's optimism.

Key points to focus on:
- Risks and Challenges: Highlight market saturation, financial instability, or macroeconomic threats.
- Competitive Weaknesses: Emphasize vulnerabilities and threats from competitors.
- Negative Indicators: Use financial data, market trends, or recent adverse news.
- Bull Counterpoints: Critically analyze the bull argument and expose over-optimistic assumptions.

Resources available to you:
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
Company fundamentals report: {fundamentals_report}
Conversation history: {history}
Last bull argument: {current_response}

DELIVER YOUR BEAR ARGUMENT NOW:
"""

        response = llm.invoke(prompt)

        argument = f"Bear Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bear_node
