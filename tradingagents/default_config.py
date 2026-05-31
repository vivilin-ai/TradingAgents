import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    "memory_log_max_entries": None,

    # ── LLM settings ──────────────────────────────────────────────────────────
    # Env-var overrides let the bot / scheduled tasks pick a provider without
    # touching source code.
    "llm_provider": os.getenv("TRADINGAGENTS_LLM_PROVIDER", "openai"),
    "deep_think_llm": os.getenv("TRADINGAGENTS_DEEP_THINK_LLM", "gpt-5.4"),
    "quick_think_llm": os.getenv("TRADINGAGENTS_QUICK_THINK_LLM", "gpt-5.4-mini"),
    # When None each provider client falls back to its own default endpoint.
    "backend_url": None,

    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"

    # Checkpoint/resume
    "checkpoint_enabled": False,

    # Output language for analyst reports and final decision
    "output_language": "Chinese",

    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,

    # ── Data vendor configuration ─────────────────────────────────────────────
    "data_vendors": {
        "core_stock_apis": "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data": "yfinance",
        "news_data": "yfinance",
    },
    "tool_vendors": {},

    # ── Reports ───────────────────────────────────────────────────────────────
    # Root directory for all analysis reports.  Sub-structure:
    #   manual/<DATE>_<TICKER>/    — single-stock via CLI or bot /analyze
    #   batch/<DATE>/              — multi-ticker via CLI or bot /batch
    #   scheduled/<task>/<DATE>/   — scheduled task output
    "reports_root": os.getenv("TRADINGAGENTS_REPORTS_ROOT", "reports"),

    # ── Watchlist ─────────────────────────────────────────────────────────────
    "watchlist_path": os.getenv(
        "TRADINGAGENTS_WATCHLIST_PATH",
        os.path.join(_TRADINGAGENTS_HOME, "watchlist.yaml"),
    ),

    # Include LLM cross-ticker narrative in batch summary.md
    "weekly_summary_narrative": True,

    # Max concurrent tickers in run_batch().
    # 1 = sequential (safe, slower); 3 = parallel (faster, higher API load)
    "batch_max_workers": 3,

    # ── Telegram Bot ──────────────────────────────────────────────────────────
    "bot_poll_interval": 2,  # seconds between getUpdates calls
}
