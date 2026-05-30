<p align="center">
  <img src="assets/TauricResearch.png" style="width: 60%; height: auto;">
</p>

<div align="center" style="line-height: 1;">
  <a href="https://arxiv.org/abs/2412.20138" target="_blank"><img alt="arXiv" src="https://img.shields.io/badge/arXiv-2412.20138-B31B1B?logo=arxiv"/></a>
  <a href="https://discord.com/invite/hk9PGKShPK" target="_blank"><img alt="Discord" src="https://img.shields.io/badge/Discord-TradingResearch-7289da?logo=discord&logoColor=white&color=7289da"/></a>
  <a href="./assets/wechat.png" target="_blank"><img alt="WeChat" src="https://img.shields.io/badge/WeChat-TauricResearch-brightgreen?logo=wechat&logoColor=white"/></a>
  <a href="https://x.com/TauricResearch" target="_blank"><img alt="X Follow" src="https://img.shields.io/badge/X-TauricResearch-white?logo=x&logoColor=white"/></a>
  <br>
  <a href="https://github.com/TauricResearch/" target="_blank"><img alt="Community" src="https://img.shields.io/badge/Join_GitHub_Community-TauricResearch-14C290?logo=discourse"/></a>
</div>

<div align="center">
  <!-- Keep these links. Translations will automatically update with the README. -->
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=de">Deutsch</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=es">Español</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=fr">français</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ja">日本語</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ko">한국어</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=pt">Português</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ru">Русский</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=zh">中文</a>
</div>

---

# TradingAgents: Multi-Agents LLM Financial Trading Framework

## News
- [2026-04] **TradingAgents v0.2.4** released with structured-output agents (Research Manager, Trader, Portfolio Manager), LangGraph checkpoint resume, persistent decision log, DeepSeek/Qwen/GLM/Azure/Bailian provider support, Docker, and a Windows UTF-8 encoding fix. See [CHANGELOG.md](CHANGELOG.md) for the full list.
- [2026-03] **TradingAgents v0.2.3** released with multi-language output, GPT-5.4 family models, unified model catalog, backtesting date fidelity, and proxy support.
- [2026-03] **TradingAgents v0.2.2** released with GPT-5.4/Gemini 3.1/Claude 4.6 model coverage, five-tier rating scale, OpenAI Responses API, Anthropic effort control, and cross-platform stability.
- [2026-02] **TradingAgents v0.2.0** released with multi-provider LLM support (GPT-5.x, Gemini 3.x, Claude 4.x, Grok 4.x) and improved system architecture.
- [2026-01] **Trading-R1** [Technical Report](https://arxiv.org/abs/2509.11420) released, with [Terminal](https://github.com/TauricResearch/Trading-R1) expected to land soon.

<div align="center">
<a href="https://www.star-history.com/#TauricResearch/TradingAgents&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date" />
   <img alt="TradingAgents Star History" src="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date" style="width: 80%; height: auto;" />
 </picture>
</a>
</div>

> 🎉 **TradingAgents** officially released! We have received numerous inquiries about the work, and we would like to express our thanks for the enthusiasm in our community.
>
> So we decided to fully open-source the framework. Looking forward to building impactful projects with you!

<div align="center">

🚀 [Framework](#tradingagents-framework) | ⚡ [Installation](#installation) | 🎬 [Demo](https://www.youtube.com/watch?v=90gr5lwjIho) | 🔑 [API Keys](#required-api-keys) | 📦 [Python Usage](#python-usage) | ⚙️ [Configuration](#configuration-reference) | 🤝 [Contributing](#contributing) | 📄 [Citation](#citation)

</div>

## TradingAgents Framework

TradingAgents is a multi-agent trading framework that mirrors the dynamics of real-world trading firms. By deploying specialized LLM-powered agents — from fundamental analysts, sentiment experts, and technical analysts, to a trader, risk management team, and portfolio manager — the platform collaboratively evaluates market conditions and produces trading decisions. Agents engage in structured debates to identify the optimal strategy.

<p align="center">
  <img src="assets/schema.png" style="width: 100%; height: auto;">
</p>

> TradingAgents framework is designed for research purposes. Trading performance may vary based on many factors, including the chosen backbone language models, model temperature, trading periods, the quality of data, and other non-deterministic factors. [It is not intended as financial, investment, or trading advice.](https://tauric.ai/disclaimer/)

### Agent Pipeline

A single `propagate(ticker, date)` call runs the following pipeline in order:

```
Analyst Team  →  Researcher Team  →  Trader  →  Risk Management  →  Portfolio Manager
```

Each stage passes its output as context to the next, so the final decision reflects every layer of analysis.

### Analyst Team

Four independent analysts produce reports in parallel. You can select any subset when initializing the graph.

| Analyst | Role | Data sources |
|---|---|---|
| **Market Analyst** | OHLCV price action, technical indicators (MACD, RSI, Bollinger Bands, …) | yfinance / Alpha Vantage |
| **Sentiment Analyst** | Social media buzz, short-term mood signals | yfinance news |
| **News Analyst** | Macro news, global events, insider transactions | yfinance news / Alpha Vantage |
| **Fundamentals Analyst** | Balance sheet, cash flow, income statement, key ratios | yfinance / Alpha Vantage |

<p align="center">
  <img src="assets/analyst.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

### Researcher Team

Bull and bear researchers critically assess the analyst reports. They conduct structured multi-round debates (configurable via `max_debate_rounds`), and a Research Manager synthesises a final investment thesis.

<p align="center">
  <img src="assets/researcher.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Trader Agent

The Trader reads all analyst reports and the research debate summary to produce a concrete trade proposal (Buy / Hold / Sell) with sizing and rationale.

<p align="center">
  <img src="assets/trader.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Risk Management & Portfolio Manager

Three risk analysts (Aggressive, Conservative, Neutral) debate the trade proposal over configurable rounds (`max_risk_discuss_rounds`), then the Portfolio Manager issues the final verdict on a five-tier scale: **Buy / Overweight / Hold / Underweight / Sell**.

<p align="center">
  <img src="assets/risk.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

---

## Installation

### Prerequisites

- Python 3.10 or higher
- API key for at least one LLM provider (see [Required API Keys](#required-api-keys))

### pip / conda

```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents

# Create a virtual environment
conda create -n tradingagents python=3.13
conda activate tradingagents

# Install
pip install .
```

### uv (recommended for fast installs)

```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents

uv sync          # creates .venv and installs from uv.lock
uv run tradingagents
```

### Docker

```bash
cp .env.example .env      # fill in your API keys
docker compose run --rm tradingagents
```

For local models via Ollama:

```bash
docker compose --profile ollama run --rm tradingagents-ollama
```

---

## Required API Keys

### LLM Providers

Set the environment variable for your chosen provider. Only **one** provider key is required to run the framework.

| Provider | Environment variable | Notes |
|---|---|---|
| OpenAI (GPT) | `OPENAI_API_KEY` | Default provider |
| Google (Gemini) | `GOOGLE_API_KEY` | |
| Anthropic (Claude) | `ANTHROPIC_API_KEY` | |
| xAI (Grok) | `XAI_API_KEY` | |
| DeepSeek | `DEEPSEEK_API_KEY` | |
| Qwen / Alibaba DashScope | `DASHSCOPE_API_KEY` | |
| GLM / Zhipu | `ZHIPU_API_KEY` | |
| OpenRouter | `OPENROUTER_API_KEY` | Dynamic model list |
| Alibaba Bailian | `DASHSCOPE_API_KEY` | Uses DashScope key |
| Ollama (local) | _(none)_ | No key needed |
| Azure OpenAI | See `.env.enterprise.example` | |

For Azure OpenAI, copy `.env.enterprise.example` to `.env.enterprise` and fill in `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, and `AZURE_OPENAI_DEPLOYMENT_NAME`.

### Data Provider (optional)

| Provider | Environment variable | Notes |
|---|---|---|
| Alpha Vantage | `ALPHA_VANTAGE_API_KEY` | Optional; yfinance is used by default |

### Using a `.env` file

```bash
cp .env.example .env
# Edit .env and fill in your keys
```

---

## CLI Usage

Launch the interactive CLI:

```bash
tradingagents            # installed command
python -m cli.main       # run directly from source
uv run tradingagents     # via uv
```

The CLI guides you through selecting ticker, analysis date, LLM provider, model tier, analyst subset, research depth, and output language.

<p align="center">
  <img src="assets/cli/cli_init.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

Results stream in real time as each agent completes its analysis.

<p align="center">
  <img src="assets/cli/cli_news.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

<p align="center">
  <img src="assets/cli/cli_transaction.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

### CLI flags

```bash
tradingagents analyze --checkpoint          # enable crash-resume for this run
tradingagents analyze --clear-checkpoints   # wipe all checkpoints before running
```

---

## Python Usage

### Quickstart

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())
_, decision = ta.propagate("NVDA", "2026-01-15")
print(decision)
```

### Choosing a provider and models

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "anthropic"           # see provider list below
config["deep_think_llm"] = "claude-opus-4-6"   # complex reasoning tasks
config["quick_think_llm"] = "claude-sonnet-4-6" # fast tasks

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("NVDA", "2026-01-15")
print(decision)
```

### Selecting analysts

Pass any non-empty subset of `["market", "social", "news", "fundamentals"]`:

```python
ta = TradingAgentsGraph(
    selected_analysts=["market", "news", "fundamentals"],
    config=config,
)
```

### Enabling checkpoints

```python
config["checkpoint_enabled"] = True
ta = TradingAgentsGraph(config=config)
_, decision = ta.propagate("NVDA", "2026-01-15")
```

---

## Supported LLM Providers and Models

| Provider | `llm_provider` value | Example models |
|---|---|---|
| OpenAI | `"openai"` | `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano`, `gpt-5.4-pro` |
| Anthropic | `"anthropic"` | `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5` |
| Google | `"google"` | `gemini-3.1-pro-preview`, `gemini-3-flash-preview`, `gemini-2.5-pro` |
| xAI | `"xai"` | `grok-4-0709`, `grok-4-1-fast-reasoning` |
| DeepSeek | `"deepseek"` | `deepseek-chat`, `deepseek-reasoner`, `deepseek-ai/DeepSeek-V4-Flash` |
| Qwen (DashScope) | `"qwen"` | `qwen3.5-flash`, `qwen3.6-plus`, `qwen3-max` |
| GLM (Zhipu) | `"glm"` | `glm-4.7`, `glm-5`, `glm-5.1` |
| OpenRouter | `"openrouter"` | Dynamic — all models available on OpenRouter |
| Ollama (local) | `"ollama"` | `qwen3:latest`, `glm-4.7-flash:latest`, `gpt-oss:latest` |
| Alibaba Bailian | `"bailian"` | `deepseek-v4-pro`, `kimi-2.6`, `qwen-max` |
| Azure OpenAI | `"azure"` | Any deployed model name |

Each provider supports a `deep_think_llm` (complex reasoning) and a `quick_think_llm` (fast tasks). The CLI lets you select both interactively.

### Provider-specific thinking controls

```python
# Google: "high", "minimal", etc.
config["google_thinking_level"] = "high"

# OpenAI: "low", "medium", "high"
config["openai_reasoning_effort"] = "medium"

# Anthropic: "low", "medium", "high"
config["anthropic_effort"] = "high"
```

---

## Data Vendors

TradingAgents supports two data providers: **yfinance** (default, community-friendly) and **Alpha Vantage** (higher data quality, API key required). You can configure vendors per category or per tool:

```python
config["data_vendors"] = {
    "core_stock_apis": "yfinance",      # Options: "yfinance", "alpha_vantage"
    "technical_indicators": "yfinance",
    "fundamental_data": "yfinance",
    "news_data": "yfinance",
}

# Override at tool level (takes precedence over category)
config["tool_vendors"] = {
    "get_stock_data": "alpha_vantage",
}
```

---

## Persistence and Recovery

TradingAgents persists two kinds of state across runs.

### Decision log

The decision log is always on. Each completed run appends its decision to `~/.tradingagents/memory/trading_memory.md`. On the next run for the same ticker, TradingAgents:

1. Fetches the realised return (raw and alpha vs SPY) for each pending entry.
2. Generates a one-paragraph reflection on what worked and what didn't.
3. Injects the most recent same-ticker decisions and cross-ticker lessons into the Portfolio Manager prompt.

Override the path:

```bash
export TRADINGAGENTS_MEMORY_LOG_PATH=/your/path/trading_memory.md
```

Cap the number of resolved entries (pending entries are never pruned):

```python
config["memory_log_max_entries"] = 50
```

### Checkpoint resume

Checkpoint resume is opt-in via `--checkpoint`. LangGraph saves state after each node so a crashed or interrupted run resumes from the last successful step on the next invocation.

```bash
tradingagents analyze --checkpoint           # enable for this run
tradingagents analyze --clear-checkpoints    # reset all checkpoints before running
```

```python
config["checkpoint_enabled"] = True
```

Checkpoints are stored as per-ticker SQLite databases:

```
~/.tradingagents/cache/checkpoints/<TICKER>.db
```

Override the base directory:

```bash
export TRADINGAGENTS_CACHE_DIR=/your/cache/dir
```

Checkpoints are cleared automatically on successful completion to avoid stale state.

---

## Configuration Reference

Full list of `DEFAULT_CONFIG` keys:

| Key | Default | Description |
|---|---|---|
| `llm_provider` | `"openai"` | LLM provider (see [Providers](#supported-llm-providers-and-models)) |
| `deep_think_llm` | `"gpt-5.4"` | Model for complex reasoning (researchers, portfolio manager) |
| `quick_think_llm` | `"gpt-5.4-mini"` | Model for lightweight tasks (analysts) |
| `backend_url` | `None` | Custom API endpoint; defaults to each provider's standard URL |
| `max_debate_rounds` | `1` | Research debate rounds between bull and bear researchers |
| `max_risk_discuss_rounds` | `1` | Risk debate rounds among risk analysts |
| `max_recur_limit` | `100` | LangGraph recursion limit |
| `output_language` | `"English"` | Language for analyst reports and final decision |
| `checkpoint_enabled` | `False` | Enable LangGraph checkpoint resume |
| `data_vendors` | see above | Data vendor per category |
| `tool_vendors` | `{}` | Data vendor override per tool |
| `results_dir` | `~/.tradingagents/logs` | Directory for run output logs |
| `data_cache_dir` | `~/.tradingagents/cache` | Directory for cached data and checkpoints |
| `memory_log_path` | `~/.tradingagents/memory/trading_memory.md` | Decision log path |
| `memory_log_max_entries` | `None` | Max resolved log entries (None = unlimited) |
| `google_thinking_level` | `None` | Gemini thinking budget |
| `openai_reasoning_effort` | `None` | OpenAI reasoning effort |
| `anthropic_effort` | `None` | Anthropic thinking effort |

### Environment variable overrides

| Variable | Overrides config key |
|---|---|
| `TRADINGAGENTS_RESULTS_DIR` | `results_dir` |
| `TRADINGAGENTS_CACHE_DIR` | `data_cache_dir` |
| `TRADINGAGENTS_MEMORY_LOG_PATH` | `memory_log_path` |
| `TRADINGAGENTS_WATCHLIST_PATH` | `watchlist_path` |
| `TRADINGAGENTS_WEEKLY_REPORTS_DIR` | `weekly_reports_dir` |

---

## Output and Reports

Each completed run writes:

- **`~/.tradingagents/logs/<TICKER>/TradingAgentsStrategy_logs/full_states_log_<DATE>.json`** — full agent state (all reports, debate histories, final decision)
- **`~/.tradingagents/memory/trading_memory.md`** — persistent decision log

---

## Watchlist & Weekly Batch Analysis

Run TradingAgents over a curated list of tickers every week, collect individual reports, and receive a unified summary with cross-ticker insights.

### Managing your watchlist

```bash
tradingagents watchlist list
tradingagents watchlist add NVDA AAPL MSFT GOOG TSM
tradingagents watchlist remove TSLA
tradingagents watchlist edit          # opens $EDITOR
```

The watchlist is stored as YAML at `~/.tradingagents/watchlist.yaml` by default. You can optionally specify which analyst subset to run per-watchlist:

```yaml
# ~/.tradingagents/watchlist.yaml
tickers: [NVDA, AAPL, MSFT, GOOG, TSM]
analysts: [market, news, fundamentals]   # optional; defaults to all four
```

Override the path:

```bash
export TRADINGAGENTS_WATCHLIST_PATH=/path/to/my-list.yaml
```

### Running the weekly batch

```bash
tradingagents weekly-run                     # use most recent trading day
tradingagents weekly-run --date 2026-05-26   # specific date
tradingagents weekly-run --no-narrative      # skip LLM cross-ticker summary
tradingagents weekly-run --no-notify         # skip Telegram notification
```

Tickers are processed **sequentially**. Each ticker runs inside its own error boundary — a single failure does not abort the batch.

### Output structure

```
reports/weekly/2026-W22/
  ├── summary.md        ← decision table + optional LLM narrative
  ├── NVDA.md           ← full individual report
  ├── AAPL.md
  └── errors.md         ← only written when one or more tickers fail
```

Configure the root directory:

```python
config["weekly_reports_dir"] = "reports/weekly"   # default
```

or via environment variable:

```bash
export TRADINGAGENTS_WEEKLY_REPORTS_DIR=/my/reports/weekly
```

### Weekly summary

`summary.md` always contains a deterministic decision table:

| Ticker | Rating | Thesis | Main Risk | Key Event |
|--------|--------|--------|-----------|-----------|
| NVDA | 🟢 Buy | … | … | … |
| AAPL | ⚪ Hold | … | … | … |

When `weekly_summary_narrative` is `True` (default), the summary also includes an LLM-generated section covering cross-ticker themes, divergences, and portfolio observations. Disable it per run with `--no-narrative` or globally:

```python
config["weekly_summary_narrative"] = False
```

### Telegram notifications

Add to your `.env` file:

```bash
TELEGRAM_BOT_TOKEN=<your bot token from @BotFather>
TELEGRAM_CHAT_ID=<your chat or group ID>
```

Enable in config:

```python
config["notifier"] = "telegram"
```

When the weekly batch completes, you receive a message like:

```
📊 Weekly Analysis · 2026-W22 (2026-05-26)

✅ 5/5 completed

🟢 Buy: NVDA, AAPL
🔵 Overweight: MSFT
⚪ Hold: GOOG
🟡 Underweight: TSM
```

The `Notifier` interface is open for extension. To add a custom notifier (e.g. Slack, webhook, OpenClaw), subclass `tradingagents.notifiers.base.Notifier`, implement `send()`, and register it in `tradingagents/notifiers/__init__.py`.

### Scheduling the weekly run

#### Option 1 — local schedule (launchd / crontab)

Configure the schedule in `default_config.py` or your own config:

```python
config["weekly_schedule"] = {
    "day": "monday",    # monday … sunday
    "time": "09:00",    # 24-hour HH:MM
    "timezone": "local",
}
```

Then install it once:

```bash
tradingagents schedule install    # writes launchd plist (macOS) or crontab (Linux)
tradingagents schedule status     # confirm it is registered
tradingagents schedule uninstall  # remove it
```

The schedule reads `weekly_schedule` from `DEFAULT_CONFIG` at install time. To change the day or time, edit your config and run `schedule install` again.

#### Option 2 — Claude Code Routine (cloud-side, no local machine needed)

You can trigger the weekly run from a [Claude Code Routine](https://claude.ai/code) so it runs in the cloud on schedule without your machine being on.

**Prerequisites:**
1. Push this repo (including the `reports/weekly/` output directory) to a **private GitHub repository**.
2. Configure the following environment variables in your Routine's environment:
   - `GH_TOKEN` — GitHub personal access token with `repo` scope
   - Your LLM provider key (e.g. `OPENAI_API_KEY`)
   - `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (if using Telegram notifications)

**Routine prompt template** (paste into your Routine configuration):

```
Run the TradingAgents weekly batch and commit the results.

Steps:
1. Clone the repo:
   git clone https://x-access-token:$GH_TOKEN@github.com/<your-org>/<your-repo>.git repo
   cd repo

2. Set up the environment:
   uv sync

3. Run the batch:
   uv run tradingagents weekly-run

4. Commit and push the generated reports:
   git config user.email "routine@tradingagents"
   git config user.name "TradingAgents Routine"
   git add reports/weekly/
   git commit -m "chore: weekly analysis $(date +%Y-W%V)" || echo "nothing to commit"
   git push
```

Set the Routine's cron schedule to match your preferred day and time, e.g. `0 9 * * 1` for Monday 09:00 UTC.

---

## Contributing

We welcome contributions from the community! Whether it's fixing a bug, improving documentation, or suggesting a new feature, your input helps make this project better. If you are interested in this line of research, please consider joining our open-source financial AI research community [Tauric Research](https://tauric.ai/).

Past contributions, including code, design feedback, and bug reports, are credited per release in [`CHANGELOG.md`](CHANGELOG.md).

---

## Citation

Please reference our work if you find *TradingAgents* provides you with some help :)

```
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework}, 
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138}, 
}
```
