from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import build_instrument_context, get_language_instruction, get_news
from tradingagents.dataflows.config import get_config


def create_social_media_analyst(llm):
    def social_media_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_news,
        ]

        system_message = (
            "You are a social media and company specific news researcher/analyst tasked with analyzing social media posts, recent company news, and public sentiment for a specific company over the past week."
            + "\n\n**CRITICAL INSTRUCTIONS**:\n1. DO NOT output any \"plan\", \"thoughts\", or \"intentions\" (e.g., \"I will search for social media posts...\").\n2. If you need data, your FIRST and ONLY response must be the tool call(s).\n3. ONLY provide your final analysis report AFTER you have received the tool outputs.\n4. Your report MUST summarize actual public sentiment and social trends found in the data."
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

        outputs["sentiment_report"] = report
        return outputs

    return social_media_analyst_node
