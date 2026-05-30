from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Only applied to user-facing agents (analysts, portfolio manager).
    Internal debate agents stay in English for reasoning quality.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def build_instrument_context(ticker: str) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`)."
    )

def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


def verify_report_hallucination(content: str, reference_price: float, ticker: str = "", strict: bool = True) -> bool:
    """Verify if the report content is valid.
    
    Args:
        content: The report text to check.
        reference_price: The baseline price to compare against.
        ticker: The company of interest ticker to anchor price checks.
        strict: If True, performs strict price comparison near "current price" keywords.
    """
    import re
    
    # 1. Length check (minimum 80 characters for a substantive report)
    if len(content) < 80:
        return False
        
    # 2. Price hallucination check (only if strict is requested and we have a reference)
    if strict and reference_price > 0:
        # Keywords that indicate the "current price"
        current_price_keywords = [
            r'现价', r'当前股价', r'目前价格', r'当前价格', 
            r'current price', r'now trading at', r'currently at', r'latest price',
            r'at \$', r'price of \$'
        ]
        
        # Look for numbers near these keywords
        for kw in current_price_keywords:
            for match in re.finditer(kw, content, re.IGNORECASE):
                # Context before (50 chars) and after (40 chars)
                pre_context = content[max(0, match.start()-50):match.start()]
                start = match.end()
                post_context = content[start:start+40]
                
                # REJECTION CRITERIA 1: Other tickers mentioned nearby (Comparison Check)
                if ticker:
                    # Clean ticker for regex (remove exchange suffix)
                    base_ticker = ticker.split('.')[0]
                    # Find all uppercase sequences of 2-5 chars
                    other_tickers = re.findall(r'\b([A-Z]{2,5})\b', pre_context + " " + post_context)
                    # If other tickers are found and target ticker is NOT clearly the subject, skip this check
                    if other_tickers:
                        # If the price is preceded by another ticker, it's a comparison
                        # e.g., "AAPL is at $170"
                        if any(t != ticker and t != base_ticker for t in other_tickers):
                            continue

                # REJECTION CRITERIA 2: Historical/Temporal context
                historical_keywords = [
                    'last year', 'history', 'historical', 'ago', 'previously', 
                    '去年', '历史', '之前', '曾', '过去', '当时'
                ]
                if any(h_kw in (pre_context + post_context).lower() for h_kw in historical_keywords):
                    continue

                # REJECTION CRITERIA 3: Limit/Target context
                target_keywords = [
                    'target', 'high', 'low', 'resistance', 'support', 'stop', 
                    '目标', '最高', '最低', '阻力', '支撑', '止损', '预测'
                ]
                if any(t_kw in (pre_context + post_context).lower() for t_kw in target_keywords):
                    continue

                # Extract potential price: $178.50 or 178.50
                price_match = re.search(r'\$?\s?(\d+(?:\.\d+)?)', post_context)
                if price_match:
                    price_str = price_match.group(1)
                    try:
                        price = float(price_str)
                        
                        # IGNORE if followed by billion/million units (it's a financial metric)
                        following_text = post_context[price_match.end():price_match.end()+15].lower()
                        if any(unit in following_text for unit in ['b', 'billion', 'm', 'million', '亿', '千万', 'kw']):
                            continue
                            
                        # If price deviates more than 10% from reference
                        if abs(price - reference_price) / reference_price > 0.10:
                            return False
                    except ValueError:
                        continue
                        
    return True


        
