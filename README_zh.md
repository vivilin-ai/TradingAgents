<p align="center">
  <img src="assets/TauricResearch.png" style="width: 60%; height: auto;">
</p>

<div align="center">
  <a href="README.md">English</a> |
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=de">Deutsch</a> |
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ja">日本語</a> |
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ko">한국어</a>
</div>

---

# TradingAgents：多智能体 LLM 金融交易框架

> **致谢** — 本项目基于 [Tauric Research](https://tauric.ai/) 团队（Yijia Xiao、Edward Sun、Di Luo、Wei Wang）开源的 [TradingAgents](https://github.com/TauricResearch/TradingAgents) 框架二次开发。衷心感谢原作者团队在多智能体金融分析领域的开创性研究，以及他们以开源方式分享这一成果的慷慨精神。核心多智能体架构的一切功劳归属原创团队。本 Fork 在此基础上增加了个人使用层：Telegram 双向 Bot、持仓感知分析、自选列表持仓管理和定时任务功能。

## 更新
- [2026-05] **个人版新功能**：Telegram 双向 Bot（发命令、收结果）、持仓感知分析、自选列表持仓管理、定时任务 + 启动/完成通知。
- [2026-04] **v0.2.4** — 结构化输出智能体、LangGraph 断点续跑、持久化决策日志、DeepSeek/Qwen/GLM/Azure 支持、Docker。
- [2026-02] **v0.2.0** — 多模型提供商支持（GPT-5.x、Gemini 3.x、Claude 4.x、Grok 4.x）。

<div align="center">

🚀 [框架介绍](#框架介绍) | ⚡ [安装](#安装) | 🔑 [API 配置](#api-配置) | 💻 [命令行使用](#命令行使用) | 🤖 [Telegram Bot](#telegram-bot-配置) | 📅 [定时任务](#定时任务) | 📦 [Python API](#python-api) | ⚙️ [配置参考](#配置参考)

</div>

---

## 框架介绍

TradingAgents 模拟真实交易公司的运作方式，由多个专业 LLM 智能体协作分析股票并给出最终投资决策。

```
分析师团队  →  研究员团队  →  交易员  →  风险管理  →  投资组合经理
```

<p align="center">
  <img src="assets/schema.png" style="width: 100%; height: auto;">
</p>

| 团队 | 智能体 | 职责 |
|---|---|---|
| **分析师** | 市场、情绪、新闻、基本面 | 并行收集数据，生成分析报告 |
| **研究员** | 多头研究员、空头研究员、研究经理 | 多轮辩论 → 投资论点 |
| **交易员** | 交易员 | 提出具体交易方案 |
| **风险管理** | 激进型、保守型、中性型分析师 | 风险辩论 |
| **投资组合经理** | 投资组合经理 | 最终五档评级决策：买入 / 增持 / 持有 / 减持 / 卖出 |

> 本框架仅供研究使用，不构成投资建议。详见[免责声明](https://tauric.ai/disclaimer/)。

---

## 安装

### pip / conda

```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
conda create -n tradingagents python=3.13
conda activate tradingagents
pip install .
```

### uv（推荐，速度更快）

```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
uv sync
uv run tradingagents
```

### Docker

```bash
cp .env.example .env   # 填写 API Key
docker compose run --rm tradingagents
```

---

## API 配置

复制 `.env.example` 为 `.env` 并填写：

```bash
cp .env.example .env
```

**`.env` 文件在 Finder 里默认隐藏。** 有三种方式编辑：

```bash
# 方式一：用 TextEdit 打开
open -e .env

# 方式二：让 Finder 显示隐藏文件（快捷键）
# Command + Shift + .

# 方式三：终端 nano
nano .env
```

### LLM 提供商（只需配置一个）

| 提供商 | 环境变量 | 说明 |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | 默认提供商 |
| Anthropic（Claude） | `ANTHROPIC_API_KEY` | |
| Google（Gemini） | `GOOGLE_API_KEY` | |
| xAI（Grok） | `XAI_API_KEY` | |
| DeepSeek 官方 | `DEEPSEEK_API_KEY` + `DEEPSEEK_API_BASE=https://api.deepseek.com` | |
| DeepSeek via SiliconFlow | `DEEPSEEK_API_KEY` + `DEEPSEEK_API_BASE=https://api.siliconflow.cn/v1` | |
| 通义千问（DashScope） | `DASHSCOPE_API_KEY` | |
| 智谱 GLM | `ZHIPU_API_KEY` | |
| OpenRouter | `OPENROUTER_API_KEY` | |
| Ollama（本地） | 无需 Key | |
| Azure OpenAI | 参见 `.env.enterprise.example` | |

### Bot 和定时任务的模型配置

这几行让 Bot 和定时任务使用指定模型，无需交互选择：

```bash
TRADINGAGENTS_LLM_PROVIDER=deepseek
TRADINGAGENTS_DEEP_THINK_LLM=deepseek-v4-pro
TRADINGAGENTS_QUICK_THINK_LLM=deepseek-v4-pro
```

### Telegram Bot

```bash
TELEGRAM_BOT_TOKEN=          # 从 @BotFather 获取
TELEGRAM_CHAT_ID=            # 你的 Chat ID（见下方配置说明）
TELEGRAM_ALLOWED_CHAT_IDS=   # 安全白名单，默认与 TELEGRAM_CHAT_ID 相同
```

### 代理（中国大陆必须配置）

Telegram 在大陆被屏蔽，需要配置代理：

```bash
HTTPS_PROXY=http://127.0.0.1:7890
HTTP_PROXY=http://127.0.0.1:7890
```

ClashX 默认混合代理端口为 `7890`。打开 ClashX → General → Port 查看实际端口。

---

## 命令行使用

先激活环境：

```bash
source .venv/bin/activate   # 或：conda activate tradingagents
```

### 单只股票分析

```bash
# 交互式向导（可选模型、分析师、语言等）
tradingagents analyze

# 非交互式（使用 .env 配置，只询问持仓情况）
tradingagents analyze NVDA
tradingagents analyze NVDA --date 2026-05-29
```

**持仓感知逻辑：**

非交互模式运行时，程序会先问你是否持有该股票：

- **有持仓**：输入成本价和数量 → 投资组合经理会给出是否加仓/持有/减仓的建议
- **无持仓**：投资组合经理专注给出**何时、以什么价格买入**的建议，不会出现"减持"等不适用的建议

### 批量分析自选列表

```bash
tradingagents batch                           # 最近交易日，全部自选
tradingagents batch --date 2026-05-29
tradingagents batch --tickers NVDA,AAPL,MSFT  # 指定股票
tradingagents batch --no-narrative            # 不生成 LLM 跨股票总结
```

报告保存在 `reports/batch/<日期>/`。

### 自选列表管理

```bash
# 查看（含持仓信息）
tradingagents watchlist list

# 添加（会逐个询问持仓）
tradingagents watchlist add NVDA AAPL MSFT

# 删除
tradingagents watchlist remove TSLA

# 更新某只股票的持仓
tradingagents watchlist position NVDA --cost 125.50 --qty 100

# 清空持仓（设为 NA）
tradingagents watchlist position NVDA --clear

# 用编辑器直接修改 YAML
tradingagents watchlist edit
```

`watchlist list` 输出效果：

```
# │ 股票  │ 成本价    │ 数量  │ 总成本
1 │ NVDA  │ $125.50  │ 100  │ $12,500.00
2 │ AAPL  │ NA       │ NA   │ NA
```

### Bot 管理

```bash
tradingagents bot start              # 前台运行（Ctrl-C 停止）
tradingagents bot start --daemon     # 后台运行
tradingagents bot stop               # 停止后台 Bot
tradingagents bot status             # 查看是否运行
tradingagents bot install-launchd    # macOS：注册为登录启动项
```

### 定时任务管理

```bash
tradingagents tasks list
tradingagents tasks add weekly_all --watchlist --day 周六 --time 08:00
tradingagents tasks add daily_nvda --ticker NVDA --schedule "30 7 * * 1-5"
tradingagents tasks remove weekly_all
tradingagents tasks install          # 写入 launchd/crontab，立即生效，无需重启
tradingagents tasks uninstall
```

---

## Telegram Bot 配置

### 第一步：创建 Bot

1. 打开 Telegram，搜索 **@BotFather**，点击 **Start**
2. 发送 `/newbot`
3. 输入 Bot 显示名称，例如：`My Trading Bot`
4. 输入 Bot 用户名（必须以 `bot` 结尾），例如：`mytrading_bot`
5. BotFather 返回 **Token**，格式如下，**复制保存**：
   ```
   123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
   ```

### 第二步：获取你的 Chat ID

1. 在 Telegram 搜索你刚创建的 Bot，点击 **Start**
2. 发送任意消息，例如：`hello`
3. 在浏览器打开以下链接（替换 `<TOKEN>` 为你的 Token）：
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
   > 如果返回 `{"ok":true,"result":[]}` 说明还没有消息记录，先去 Telegram 给 Bot 发条消息再刷新。
4. 在返回的 JSON 中找到 `"chat":{"id":` 后面的数字，这就是你的 Chat ID：
   ```json
   "chat": {
     "id": 987654321,
     "type": "private"
   }
   ```

### 第三步：配置 `.env`

在 `.env` 文件中填入以下内容：

```bash
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID=987654321
TELEGRAM_ALLOWED_CHAT_IDS=987654321
```

> **`TELEGRAM_ALLOWED_CHAT_IDS` 是安全白名单**，Bot 只响应白名单中的 Chat ID 发来的命令，防止他人控制你的 Mac。

### 第四步：启动 Bot

```bash
source .venv/bin/activate
tradingagents bot start
```

看到 `Starting bot (Ctrl-C to stop)...` 后，去 Telegram 发送 `/help`，应该收到命令列表。

**常见问题：连接超时或无回应**

说明代理未配置或未启动，在 `.env` 中加入：
```bash
HTTPS_PROXY=http://127.0.0.1:7890
HTTP_PROXY=http://127.0.0.1:7890
```

### 第五步（可选）：开机自动启动

```bash
tradingagents bot install-launchd
```

Mac 登录后 Bot 自动在后台运行，无需手动启动。

### 所有 Bot 命令

| 命令 | 说明 |
|---|---|
| `/help` | 显示所有命令 |
| `/analyze TICKER [--date YYYY-MM-DD]` | 分析单只股票（先询问持仓） |
| `/batch [--date YYYY-MM-DD]` | 分析整个自选列表 |
| `/list` | 查看自选列表及持仓 |
| `/add TICKER [成本价 数量]` | 加入自选，例如 `/add NVDA 125.50 100` |
| `/remove TICKER` | 从自选删除 |
| `/position TICKER 成本价 数量` | 更新持仓，例如 `/position NVDA 130 150` |
| `/position TICKER clear` | 清空持仓（设为 NA） |
| `/tasks` | 查看定时任务列表 |
| `/tasks add 名称 对象 星期 时间` | 添加定时任务，例如 `/tasks add weekly watchlist 周六 08:00` |
| `/tasks remove 名称` | 删除任务 |
| `/tasks install` | 写入系统调度（立即生效） |
| `/tasks uninstall` | 卸载所有定时任务 |
| `/status` | 查看当前任务队列和进度 |

### 持仓感知分析流程（Bot 示例）

```
你：  /analyze NVDA
Bot： NVDA — 你目前持有该股票吗？
      • 如持有，请回复：成本价 数量（例：125.50 100）
      • 如未持有，请回复：no

你：  125.50 100
Bot： ✓ NVDA 已加入队列（第1位），持仓：100 股 @ $125.50。分析完成后发送结果。

（约15分钟后）
Bot： 📊 NVDA · 2026-05-29 · 评级：增持

      [完整的投资组合经理决策报告...]
```

---

## 定时任务

定时任务通过 **launchd**（macOS）或 **crontab**（Linux）调度。`tasks install` 执行后**立即生效，无需重启 Mac**。

### 命令行设置示例

```bash
# 每周六上午 8 点分析全部自选列表
tradingagents tasks add weekly_all --watchlist --day 周六 --time 08:00

# 每个工作日早 7:30 分析 NVDA（使用 cron 表达式）
tradingagents tasks add daily_nvda --ticker NVDA --schedule "30 7 * * 1-5"

# 写入系统（立即生效）
tradingagents tasks install

# 查看状态
tradingagents tasks list
```

支持的星期写法：`周一~周日` / `Monday~Sunday` / `Mon~Sun`

### Telegram Bot 设置（效果相同）

```
/tasks add weekly watchlist 周六 08:00
/tasks install
/tasks
```

### Telegram 通知内容

**任务启动时收到：**

```
🚀 定时任务启动：weekly_all
分析对象：自选列表（5 只股票）
日期：2026-06-07

分析进行中，完成后发送结果…
```

**全部完成后收到：**

```
📊 定时任务完成：weekly_all
日期：2026-06-07
✅ 5/5 完成
  NVDA：买入
  AAPL：增持
  MSFT：持有
  GOOG：持有
  TSM：减持
报告：reports/scheduled/weekly_all/2026-06-07/summary.md
```

### 报告目录结构

```
reports/
  manual/<日期>_<股票>/        ← 手动单股分析（CLI 或 /analyze）
    TICKER.md
  batch/<日期>/                ← 手动批量分析（CLI 或 /batch）
    summary.md
    NVDA.md, AAPL.md, …
  scheduled/<任务名>/<日期>/   ← 定时任务
    summary.md
    NVDA.md, AAPL.md, …
    errors.md（如有失败）
```

---

## 持久化与记忆

### 决策日志

每次分析完成后，决策自动追加到 `~/.tradingagents/memory/trading_memory.md`。下次分析同一只股票时，历史决策（含实际收益率和反思）会注入投资组合经理的提示词，让分析从历史中学习。

自定义路径：
```bash
export TRADINGAGENTS_MEMORY_LOG_PATH=/你的路径/trading_memory.md
```

### 断点续跑

```bash
tradingagents analyze --checkpoint          # 启用断点续跑
tradingagents analyze --clear-checkpoints   # 清除断点，强制重新开始
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
config["output_language"] = "Chinese"   # 或 "English"

ta = TradingAgentsGraph(
    selected_analysts=["market", "news", "fundamentals"],
    config=config,
)

# 传入持仓信息，投资组合经理会据此调整建议
position_context = (
    "[当前持仓]\n"
    "用户持有 100 股 NVDA，平均成本 $125.50（总成本 $12,550）。"
)
_, decision = ta.propagate("NVDA", "2026-05-29", extra_context=position_context)
print(decision)
```

---

## 配置参考

| 配置项 | 默认值 | 环境变量覆盖 | 说明 |
|---|---|---|---|
| `llm_provider` | `"openai"` | `TRADINGAGENTS_LLM_PROVIDER` | LLM 提供商 |
| `deep_think_llm` | `"gpt-5.4"` | `TRADINGAGENTS_DEEP_THINK_LLM` | 复杂推理模型 |
| `quick_think_llm` | `"gpt-5.4-mini"` | `TRADINGAGENTS_QUICK_THINK_LLM` | 快速任务模型 |
| `output_language` | `"Chinese"` | — | 报告输出语言 |
| `reports_root` | `"reports"` | `TRADINGAGENTS_REPORTS_ROOT` | 报告根目录 |
| `watchlist_path` | `~/.tradingagents/watchlist.yaml` | `TRADINGAGENTS_WATCHLIST_PATH` | 自选列表文件 |
| `weekly_summary_narrative` | `True` | — | 批量分析是否包含 LLM 跨股票总结 |
| `max_debate_rounds` | `1` | — | 研究辩论轮数 |
| `max_risk_discuss_rounds` | `1` | — | 风险辩论轮数 |
| `checkpoint_enabled` | `False` | — | 是否启用断点续跑 |
| `bot_poll_interval` | `2` | — | Bot 轮询间隔（秒） |

---

## 支持的 LLM 提供商

| 提供商 | `llm_provider` 值 | 示例模型 |
|---|---|---|
| OpenAI | `"openai"` | `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-pro` |
| Anthropic（Claude） | `"anthropic"` | `claude-opus-4-6`, `claude-sonnet-4-6` |
| Google（Gemini） | `"google"` | `gemini-3.1-pro-preview`, `gemini-2.5-pro` |
| xAI（Grok） | `"xai"` | `grok-4-0709`, `grok-4-1-fast-reasoning` |
| DeepSeek | `"deepseek"` | `deepseek-v4-pro`, `deepseek-chat`, `deepseek-reasoner` |
| 通义千问（Qwen） | `"qwen"` | `qwen3.6-plus`, `qwen3.5-flash` |
| 智谱 GLM | `"glm"` | `glm-5.1`, `glm-5` |
| OpenRouter | `"openrouter"` | OpenRouter 上所有模型 |
| Ollama（本地） | `"ollama"` | `qwen3:latest`, `glm-4.7-flash:latest` |
| 阿里百炼 | `"bailian"` | `deepseek-v4-pro`, `kimi-2.6`, `qwen-max` |
| Azure OpenAI | `"azure"` | 任何已部署的模型名 |

---

## 贡献

欢迎提交 Issue 和 PR！每个版本的贡献者记录在 [`CHANGELOG.md`](CHANGELOG.md)。

---

## 引用

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
