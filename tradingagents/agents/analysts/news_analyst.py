from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_global_news,
    get_language_instruction,
    get_news,
)
from tradingagents.dataflows.config import get_config


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_news,
            get_global_news,
        ]

        system_message = (
            "You are a news researcher tasked with analyzing recent news and trends over the past week. Please write a comprehensive report of the current state of the world that is relevant for trading and macroeconomics. Use the available tools: get_news(query, start_date, end_date) for company-specific or targeted news searches, and get_global_news(curr_date, look_back_days, limit) for broader macroeconomic news. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
            + "\n\n**CRITICAL INSTRUCTIONS**:\n1. DO NOT output any \"plan\", \"thoughts\", or \"intentions\" (e.g., \"I will first fetch news...\").\n2. If you need data, your FIRST and ONLY response must be the tool call(s).\n3. ONLY provide your final analysis report AFTER you have received the tool outputs.\n4. Your report MUST contain specific factual data points found in the news."
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""
        outputs = {"messages": [result], "retry_count": 0}

        if len(getattr(result, "tool_calls", [])) == 0:
            from tradingagents.agents.utils.agent_utils import verify_report_hallucination
            ref_price = state.get("reference_price", 0.0)
            ticker = state.get("company_of_interest", "")
            
            if verify_report_hallucination(result.content, ref_price, ticker=ticker, strict=False):
                report = result.content
            else:
                report = ""
                # Drop this "plan" message by returning an empty list to avoid state pollution
                outputs["messages"] = []
                outputs["retry_count"] = state.get("retry_count", 0) + 1

        outputs["news_report"] = report
        return outputs

    return news_analyst_node
