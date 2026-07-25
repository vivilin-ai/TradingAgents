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

    # ── Weekly evaluation loop (see docs/weekly_iteration_plan.md) ────────────
    # Structured decision ledger consumed by the evaluate command.
    "decision_ledger_path": os.getenv(
        "TRADINGAGENTS_DECISION_LEDGER_PATH",
        os.path.join(_TRADINGAGENTS_HOME, "memory", "decisions.jsonl"),
    ),
    # Curated cross-ticker lessons maintained by weekly meta-reflection.
    "lessons_path": os.path.join(_TRADINGAGENTS_HOME, "memory", "lessons.md"),
    # Latest calibration block injected into agent prompts at analysis time.
    "calibration_path": os.path.join(_TRADINGAGENTS_HOME, "memory", "calibration.md"),
    # Evaluation state: active strategy params, candidate streaks, bias flags.
    "eval_state_path": os.path.join(_TRADINGAGENTS_HOME, "memory", "eval_state.json"),
    # Settlement horizons in trading days.
    "eval_horizons": [5, 10, 21],
    # Benchmark ticker for alpha computation.
    "eval_benchmark": "SPY",
    # Calendar days after which a decision with no price data at all is
    # abandoned instead of retried every week (delisted or mistyped symbol).
    "eval_abandon_after_days": 45,
    # One-way transaction cost in basis points for the advice-following sim.
    "eval_cost_bps": 10,
    # Rolling window (weeks) for scorecard stats and the north-star IR.
    "eval_window_weeks": 12,
    # Rating -> target weight (fraction of the per-ticker capacity).
    # None means "keep current position unchanged".
    "rating_weight_map": {
        "Buy": 1.0, "Overweight": 0.7, "Hold": None,
        "Underweight": 0.3, "Sell": 0.0,
    },
    # Minimum settled samples per rating tier before calibration draws conclusions.
    "calibration_min_samples": 8,
    # |avg effective alpha| beyond which a tier is flagged as a systematic bias.
    "calibration_alpha_threshold": 0.005,
    # Minimum settled decisions before parameter iteration (P4) activates.
    "iteration_min_decisions": 30,
    # Weekly-IR margin a candidate mapping must beat the active one by.
    "iteration_switch_margin": 0.003,
    # Consecutive winning evals required before switching mappings (hysteresis).
    "iteration_switch_streak": 2,
    # Cap on curated lessons kept in lessons.md.
    "lessons_max_entries": 20,

    # Max concurrent tickers in run_batch().
    # 1 = sequential (safe, slower); 3 = parallel (faster, higher API load)
    "batch_max_workers": 3,
    # Max retries per failed ticker. Rate-limit failures wait before retry;
    # other failures retry immediately.
    "batch_max_retries": 2,
    # Base wait seconds before the first rate-limit retry. Each subsequent
    # retry waits 2x longer (30s → 60s).
    "batch_retry_wait": 30,

    # ── Telegram Bot ──────────────────────────────────────────────────────────
    "bot_poll_interval": 2,  # seconds between getUpdates calls
}
