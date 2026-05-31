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
  <a href="README_zh.md">中文文档</a> |
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=de">Deutsch</a> |
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=es">Español</a> |
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=fr">français</a> |
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ja">日本語</a> |
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ko">한국어</a> |
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=pt">Português</a> |
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ru">Русский</a>
</div>

---

# TradingAgents: Multi-Agent LLM Financial Trading Framework

## News
- [2026-05] **Personal edition features**: Telegram bot with two-way commands, position-aware analysis, watchlist position tracking, scheduled tasks with Telegram notifications.
- [2026-04] **TradingAgents v0.2.4** — structured-output agents, LangGraph checkpoint resume, persistent decision log, DeepSeek/Qwen/GLM/Azure support, Docker. See [CHANGELOG.md](CHANGELOG.md).
- [2026-03] **v0.2.3** — multi-language output, GPT-5.4 family, unified model catalog.
- [2026-02] **v0.2.0** — multi-provider LLM support (GPT-5.x, Gemini 3.x, Claude 4.x, Grok 4.x).

<div align="center">

🚀 [Framework](#framework) | ⚡ [Installation](#installation) | 🔑 [API Keys](#api-keys) | 💻 [CLI Usage](#cli-usage) | 🤖 [Telegram Bot](#telegram-bot-setup) | 📅 [Scheduled Tasks](#scheduled-tasks) | 📦 [Python API](#python-api) | ⚙️ [Config](#configuration-reference)

</div>

---

## Framework

TradingAgents mirrors a real trading firm. Specialized LLM agents collaborate to analyse a stock and produce a final portfolio decision.

```
Analyst Team  →  Researcher Team  →  Trader  →  Risk Management  →  Portfolio Manager
```

<p align="center">
  <img src="assets/schema.png" style="width: 100%; height: auto;">
</p>

| Team | Agents | Role |
|---|---|---|
| **Analyst** | Market, Sentiment, News, Fundamentals | Parallel data gathering |
| **Research** | Bull, Bear, Research Manager | Structured debate → investment thesis |
| **Trading** | Trader | Trade proposal with sizing |
| **Risk** | Aggressive, Conservative, Neutral | Risk debate |
| **Portfolio** | Portfolio Manager | Final 5-tier decision: Buy / Overweight / Hold / Underweight / Sell |

> For research purposes only. Not financial advice. See [disclaimer](https://tauric.ai/disclaimer/).

---

## Installation

### pip / conda
```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
conda create -n tradingagents python=3.13 && conda activate tradingagents
pip install .
```

### uv (recommended — fast)
```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
uv sync
uv run tradingagents
```

### Docker
```bash
cp .env.example .env   # fill in your keys
docker compose run --rm tradingagents
```

---

## API Keys

Copy `.env.example` to `.env` and fill in the values you need:

```bash
cp .env.example .env
```

### LLM Provider (one is enough)

| Provider | Variable | Notes |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | Default provider |
| Anthropic | `ANTHROPIC_API_KEY` | |
| Google | `GOOGLE_API_KEY` | |
| xAI | `XAI_API_KEY` | |
| DeepSeek (official) | `DEEPSEEK_API_KEY` + `DEEPSEEK_API_BASE=https://api.deepseek.com` | |
| DeepSeek (SiliconFlow) | `DEEPSEEK_API_KEY` + `DEEPSEEK_API_BASE=https://api.siliconflow.cn/v1` | |
| Qwen / DashScope | `DASHSCOPE_API_KEY` | |
| GLM / Zhipu | `ZHIPU_API_KEY` | |
| OpenRouter | `OPENROUTER_API_KEY` | |
| Ollama (local) | _(none required)_ | |
| Azure OpenAI | See `.env.enterprise.example` | |

### Override model for bot / scheduled tasks

These env vars let the bot and scheduled tasks pick a provider without the interactive wizard:

```bash
TRADINGAGENTS_LLM_PROVIDER=deepseek
TRADINGAGENTS_DEEP_THINK_LLM=deepseek-v4-pro
TRADINGAGENTS_QUICK_THINK_LLM=deepseek-v4-pro
```

### Telegram Bot

```bash
TELEGRAM_BOT_TOKEN=          # from @BotFather
TELEGRAM_CHAT_ID=            # your chat ID (see setup below)
TELEGRAM_ALLOWED_CHAT_IDS=   # security whitelist; defaults to TELEGRAM_CHAT_ID
```

### Proxy (required in China mainland)

```bash
HTTPS_PROXY=http://127.0.0.1:7890
HTTP_PROXY=http://127.0.0.1:7890
```

ClashX default mixed port is `7890`.

---

## CLI Usage

Activate the environment first:

```bash
source .venv/bin/activate   # or: conda activate tradingagents
```

### Single-stock analysis

```bash
# Interactive wizard — select provider, analysts, language, etc.
tradingagents analyze

# Non-interactive — uses .env settings, prompts for holding status only
tradingagents analyze NVDA
tradingagents analyze NVDA --date 2026-05-29
```

When running non-interactively the CLI asks:
- Do you currently hold NVDA? → enter average cost and quantity
- The Portfolio Manager then tailors its recommendation to your position

If you have **no position**: the PM focuses on **entry conditions** (when and at what price to buy), never suggesting reducing a position you don't hold.

If you **hold shares**: the PM considers whether to add, hold, reduce, or exit based on your cost basis.

### Batch analysis

```bash
tradingagents batch                           # full watchlist, latest trading day
tradingagents batch --date 2026-05-29
tradingagents batch --tickers NVDA,AAPL,MSFT  # custom list
tradingagents batch --no-narrative            # skip LLM cross-ticker summary
```

Reports saved to `reports/batch/<DATE>/`.

### Watchlist management

```bash
tradingagents watchlist list
tradingagents watchlist add NVDA AAPL MSFT         # prompts for position per ticker
tradingagents watchlist remove TSLA
tradingagents watchlist position NVDA --cost 125.50 --qty 100
tradingagents watchlist position NVDA --clear       # set to NA
tradingagents watchlist edit                        # open YAML in $EDITOR
```

`watchlist list` output:

```
# │ Ticker │ Cost/Share │ Qty  │ Total Cost
1 │ NVDA   │ $125.50   │ 100  │ $12,500.00
2 │ AAPL   │ NA        │ NA   │ NA
```

### Bot management

```bash
tradingagents bot start              # foreground (Ctrl-C to stop)
tradingagents bot start --daemon     # background
tradingagents bot stop
tradingagents bot status
tradingagents bot install-launchd    # macOS: auto-start on login
```

### Scheduled tasks

```bash
tradingagents tasks list
tradingagents tasks add weekly_all --watchlist --day Saturday --time 08:00
tradingagents tasks add daily_nvda --ticker NVDA --schedule "30 7 * * 1-5"
tradingagents tasks remove weekly_all
tradingagents tasks install          # write to launchd/crontab — no restart needed
tradingagents tasks uninstall
```

---

## Telegram Bot Setup

### Step 1 — Create the bot

1. Open Telegram → search **@BotFather** → tap **Start**
2. Send `/newbot`
3. Enter a display name, e.g. `My Trading Bot`
4. Enter a username ending in `bot`, e.g. `mytrading_bot`
5. Copy the **Token** returned by BotFather (format: `123456789:ABCdef…`)

### Step 2 — Find your Chat ID

1. Open your bot in Telegram and press **Start**
2. Send any message, e.g. `hello`
3. Open in a browser (replace `<TOKEN>` with your actual token):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
4. Look for `"chat":{"id":` in the JSON — the number after it is your Chat ID:
   ```json
   "chat": { "id": 987654321, "type": "private" }
   ```

### Step 3 — Fill in `.env`

```bash
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID=987654321
TELEGRAM_ALLOWED_CHAT_IDS=987654321
```

> `TELEGRAM_ALLOWED_CHAT_IDS` is a security whitelist. The bot silently ignores commands from any chat ID not listed here.

### Step 4 — Start the bot

```bash
source .venv/bin/activate
tradingagents bot start
```

Send `/help` in Telegram. You should see the command list.

### Step 5 — Auto-start on Mac login (optional)

```bash
tradingagents bot install-launchd
```

### All bot commands

| Command | Description |
|---|---|
| `/help` | Show all commands |
| `/analyze TICKER [--date DATE]` | Analyse a single stock (asks about your position first) |
| `/batch [--date DATE]` | Analyse the full watchlist |
| `/list` | Show watchlist with positions |
| `/add TICKER [cost qty]` | Add ticker to watchlist, e.g. `/add NVDA 125.50 100` |
| `/remove TICKER` | Remove from watchlist |
| `/position TICKER cost qty` | Update position, e.g. `/position NVDA 130 150` |
| `/position TICKER clear` | Clear position (set to NA) |
| `/tasks` | List all scheduled tasks |
| `/tasks add name target day time` | Add task, e.g. `/tasks add weekly watchlist Saturday 08:00` |
| `/tasks remove name` | Remove a task |
| `/tasks install` | Write tasks to system scheduler (takes effect immediately) |
| `/tasks uninstall` | Remove all scheduled tasks |
| `/status` | Show current job queue and progress |

### Position-aware analysis via bot

```
You:  /analyze NVDA
Bot:  NVDA — do you currently hold this stock?
      • If yes, reply: cost_per_share quantity  (e.g. 125.50 100)
      • If no, reply: no

You:  125.50 100
Bot:  ✓ NVDA queued (position 1): 100 shares @ $125.50. Result incoming...

(~15 minutes later)
Bot:  📊 NVDA · 2026-05-29 · Rating: Overweight
      [full Portfolio Manager decision text]
```

---

## Scheduled Tasks

Tasks run via **launchd** (macOS) or **crontab** (Linux). `tasks install` takes effect **immediately** — no Mac restart needed.

### CLI setup example

```bash
# Every Saturday at 08:00 — full watchlist
tradingagents tasks add weekly_all --watchlist --day Saturday --time 08:00

# Every weekday at 07:30 — NVDA only (cron expression)
tradingagents tasks add daily_nvda --ticker NVDA --schedule "30 7 * * 1-5"

# Activate
tradingagents tasks install

# Verify
tradingagents tasks list
```

### Telegram bot setup (same result)

```
/tasks add weekly watchlist Saturday 08:00
/tasks install
/tasks
```

### Notifications

Each scheduled run sends **two Telegram messages**:

**On start:**
```
🚀 Scheduled task started: weekly_all
Targets: watchlist (5 stocks)
Date: 2026-06-07
Analysis in progress, results incoming…
```

**On completion:**
```
📊 Scheduled task complete: weekly_all
Date: 2026-06-07
✅ 5/5 completed
  NVDA: Buy
  AAPL: Overweight
  MSFT: Hold
  GOOG: Hold
  TSM: Underweight
Report: reports/scheduled/weekly_all/2026-06-07/summary.md
```

### Report directory structure

```
reports/
  manual/<DATE>_<TICKER>/     ← single-stock via CLI or /analyze
    TICKER.md
  batch/<DATE>/               ← batch via CLI or /batch
    summary.md
    NVDA.md, AAPL.md, …
  scheduled/<task>/<DATE>/    ← scheduled task
    summary.md
    NVDA.md, AAPL.md, …
    errors.md  (if any)
```

---

## Persistence and Recovery

### Decision log

Every run appends to `~/.tradingagents/memory/trading_memory.md`. On the next run for the same ticker, past decisions (with realised return vs SPY and a reflection) are injected into the PM prompt so the agent learns from prior calls.

```bash
export TRADINGAGENTS_MEMORY_LOG_PATH=/your/custom/path.md
```

### Checkpoint resume

```bash
tradingagents analyze --checkpoint          # save state, resume if crashed
tradingagents analyze --clear-checkpoints   # wipe and start fresh
```

---

## Python API

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "deepseek"
config["deep_think_llm"] = "deepseek-v4-pro"
config["quick_think_llm"] = "deepseek-v4-pro"
config["output_language"] = "Chinese"   # or "English"

ta = TradingAgentsGraph(
    selected_analysts=["market", "news", "fundamentals"],
    config=config,
)

# Pass position context so PM tailors its recommendation
position_context = (
    "[Current Position]\n"
    "The user holds 100 shares at $125.50 average cost ($12,550 total)."
)
_, decision = ta.propagate("NVDA", "2026-05-29", extra_context=position_context)
print(decision)
```

---

## Configuration Reference

| Key | Default | Env override | Description |
|---|---|---|---|
| `llm_provider` | `"openai"` | `TRADINGAGENTS_LLM_PROVIDER` | LLM provider |
| `deep_think_llm` | `"gpt-5.4"` | `TRADINGAGENTS_DEEP_THINK_LLM` | Model for reasoning |
| `quick_think_llm` | `"gpt-5.4-mini"` | `TRADINGAGENTS_QUICK_THINK_LLM` | Model for fast tasks |
| `output_language` | `"Chinese"` | — | Report language |
| `reports_root` | `"reports"` | `TRADINGAGENTS_REPORTS_ROOT` | Report root directory |
| `watchlist_path` | `~/.tradingagents/watchlist.yaml` | `TRADINGAGENTS_WATCHLIST_PATH` | Watchlist file |
| `weekly_summary_narrative` | `True` | — | LLM cross-ticker narrative in batch summary |
| `max_debate_rounds` | `1` | — | Research debate rounds |
| `max_risk_discuss_rounds` | `1` | — | Risk debate rounds |
| `checkpoint_enabled` | `False` | — | LangGraph crash-resume |
| `bot_poll_interval` | `2` | — | Bot polling interval (seconds) |

---

## Supported LLM Providers

| Provider | `llm_provider` value | Example models |
|---|---|---|
| OpenAI | `"openai"` | `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-pro` |
| Anthropic | `"anthropic"` | `claude-opus-4-6`, `claude-sonnet-4-6` |
| Google | `"google"` | `gemini-3.1-pro-preview`, `gemini-2.5-pro` |
| xAI | `"xai"` | `grok-4-0709`, `grok-4-1-fast-reasoning` |
| DeepSeek | `"deepseek"` | `deepseek-v4-pro`, `deepseek-chat`, `deepseek-reasoner` |
| Qwen | `"qwen"` | `qwen3.6-plus`, `qwen3.5-flash` |
| GLM | `"glm"` | `glm-5.1`, `glm-5` |
| OpenRouter | `"openrouter"` | All OpenRouter models |
| Ollama (local) | `"ollama"` | `qwen3:latest`, `glm-4.7-flash:latest` |
| Bailian | `"bailian"` | `deepseek-v4-pro`, `kimi-2.6` |
| Azure OpenAI | `"azure"` | Any deployed model name |

---

## Contributing

We welcome contributions! See [`CHANGELOG.md`](CHANGELOG.md) for per-release credits. Join [Tauric Research](https://tauric.ai/) to collaborate on financial AI research.

---

## Citation

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
