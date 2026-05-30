"""Command handlers for the Telegram bot.

Each handler receives (bot, message) and sends replies directly via bot.send().
The chat_id whitelist check is enforced in TelegramBot.handle_update() before
dispatching here.
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .telegram_bot import TelegramBot

from tradingagents.batch.runner import BatchRunner
from tradingagents.batch.watchlist import add_tickers, load_watchlist, remove_tickers

logger = logging.getLogger(__name__)

_MAX_MSG = 4000   # Telegram limit is 4096; leave headroom


def _split(text: str, limit: int = _MAX_MSG) -> list[str]:
    """Split a long string into ≤limit-char chunks at newline boundaries."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if current_len + len(line) > limit and current:
            chunks.append("".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += len(line)
    if current:
        chunks.append("".join(current))
    return chunks


def _send_long(bot: "TelegramBot", chat_id: int | str, text: str) -> None:
    for chunk in _split(text):
        bot.send(chat_id, chunk)


def _parse_date(args: list[str]) -> tuple[str | None, list[str]]:
    """Pull --date YYYY-MM-DD from args if present, return (date, remaining)."""
    try:
        idx = args.index("--date")
        date_str = args[idx + 1]
        datetime.date.fromisoformat(date_str)  # validate
        remaining = args[:idx] + args[idx + 2:]
        return date_str, remaining
    except (ValueError, IndexError):
        return None, args


# ── Handlers ──────────────────────────────────────────────────────────────────

def cmd_help(bot: "TelegramBot", message: dict[str, Any], args: list[str]) -> None:
    bot.send_plain(message["chat"]["id"], (
        "📈 TradingAgents Bot\n\n"
        "/analyze TICKER [--date YYYY-MM-DD] — 分析单只股票\n"
        "/batch [--date YYYY-MM-DD] — 分析全部自选列表\n"
        "/list — 查看自选列表及持仓\n"
        "/add TICKER [成本价 数量] — 加入自选（可附持仓）\n"
        "/remove TICKER — 从自选删除\n"
        "/position TICKER [成本价 数量] — 查看/更新持仓\n"
        "/position TICKER clear — 清空持仓\n"
        "/status — 查看当前任务进度\n"
        "/help — 帮助"
    ))


def cmd_analyze(bot: "TelegramBot", message: dict[str, Any], args: list[str]) -> None:
    chat_id = message["chat"]["id"]

    if not args:
        bot.send(chat_id, "Usage: /analyze TICKER \\[--date YYYY-MM-DD\\]")
        return

    date_str, remaining = _parse_date(args)
    ticker = remaining[0].upper() if remaining else None
    if not ticker:
        bot.send(chat_id, "Please specify a ticker, e.g. /analyze NVDA")
        return

    # Ask about position before queuing
    bot._pending_positions[str(chat_id)] = {"ticker": ticker, "date": date_str}
    bot.send(
        chat_id,
        f"📋 *{ticker}* — 你目前持有该股票吗？\n\n"
        f"• 如持有，请回复：`成本价 数量` （例：`125\\.50 100`）\n"
        f"• 如未持有，请回复：`no`",
    )


def cmd_batch(bot: "TelegramBot", message: dict[str, Any], args: list[str]) -> None:
    chat_id = message["chat"]["id"]
    date_str, _ = _parse_date(args)
    date_label = date_str or "latest trading day"

    wl = load_watchlist(bot.config["watchlist_path"])
    tickers = wl.get("tickers", [])
    if not tickers:
        bot.send(chat_id, "Your watchlist is empty. Use /add TICKER to add stocks.")
        return

    runner = BatchRunner(config=bot.config)

    def run():
        results, summary_path = runner.run_batch(trade_date=date_str, mode="batch")
        return results, summary_path

    def on_ticker_update(result: dict) -> None:
        ticker = result["ticker"]
        if result.get("error"):
            bot.send(chat_id, f"❌ {ticker}: {result['error'][:100]}")
        else:
            bot.send(chat_id, f"✅ {ticker}: {result.get('rating', '—')}")

    def on_complete(job, outcome, error):
        if error:
            bot.send(chat_id, f"❌ Batch failed: `{str(error)[:300]}`")
            return
        results, summary_path = outcome
        completed = [r for r in results if not r.get("error")]
        errors = [r for r in results if r.get("error")]
        lines = [
            f"📊 *Batch complete* · {date_label}",
            f"✅ {len(completed)}/{len(results)} succeeded",
        ]
        for r in completed:
            lines.append(f"  {r['ticker']}: {r.get('rating', '—')}")
        if errors:
            lines.append(f"❌ Failed: {', '.join(r['ticker'] for r in errors)}")
        lines.append(f"\nReport saved: `{summary_path}`")
        bot.send(chat_id, "\n".join(lines))

    # Wrap run() to pass on_ticker_done
    def run_with_callbacks():
        results, summary_path = runner.run_batch(
            trade_date=date_str,
            mode="batch",
            on_ticker_done=on_ticker_update,
        )
        return results, summary_path

    _, pos = bot.job_queue.add(f"Batch {len(tickers)} tickers {date_label}", run_with_callbacks, on_complete)
    bot.send(chat_id, f"✓ Batch queued: {len(tickers)} tickers, position {pos}. Updates incoming...")


def cmd_list(bot: "TelegramBot", message: dict[str, Any], args: list[str]) -> None:
    chat_id = message["chat"]["id"]
    wl = load_watchlist(bot.config["watchlist_path"])
    tickers = wl.get("tickers", [])
    if not tickers:
        bot.send(chat_id, "Watchlist is empty. Use /add TICKER to add stocks.")
        return
    lines = ["📋 *Watchlist*", ""] + [f"{i+1}\\. {t}" for i, t in enumerate(tickers)]
    bot.send(chat_id, "\n".join(lines))


def cmd_add(bot: "TelegramBot", message: dict[str, Any], args: list[str]) -> None:
    """Add ticker(s) to watchlist.

    Formats:
      /add NVDA                   → no position
      /add NVDA 125.50 100        → with cost and qty
      /add AAPL MSFT GOOG         → multiple, no position
    """
    from tradingagents.batch.watchlist import update_position
    chat_id = message["chat"]["id"]
    if not args:
        bot.send_plain(chat_id, "用法：\n/add TICKER\n/add TICKER 成本价 数量\n例：/add NVDA 125.50 100")
        return

    # Detect if second arg looks like a number (position info for single ticker)
    ticker = args[0].upper()
    position_lines: list[str] = []

    if len(args) >= 3:
        try:
            cost = float(args[1])
            qty = float(args[2])
            add_tickers(bot.config["watchlist_path"], [ticker])
            update_position(bot.config["watchlist_path"], ticker, cost, qty)
            position_lines.append(f"{ticker}：{qty:,.0f} 股 @ ${cost:,.2f}")
        except ValueError:
            # Treat all args as tickers
            tickers = [a.upper() for a in args]
            add_tickers(bot.config["watchlist_path"], tickers)
            for t in tickers:
                position_lines.append(f"{t}：NA")
    else:
        tickers = [a.upper() for a in args]
        add_tickers(bot.config["watchlist_path"], tickers)
        for t in tickers:
            position_lines.append(f"{t}：NA")

    data = bot.config["watchlist_path"]
    from tradingagents.batch.watchlist import load_watchlist
    total = len(load_watchlist(data)["tickers"])
    bot.send_plain(chat_id, "✓ 已添加：\n" + "\n".join(position_lines) + f"\n\n自选列表共 {total} 只股票")


def cmd_remove(bot: "TelegramBot", message: dict[str, Any], args: list[str]) -> None:
    chat_id = message["chat"]["id"]
    if not args:
        bot.send(chat_id, "Usage: /remove TICKER \\[TICKER …\\]")
        return
    updated = remove_tickers(bot.config["watchlist_path"], args)
    removed = [t.upper() for t in args]
    bot.send(chat_id, f"Removed: {', '.join(removed)}\\. Watchlist now has {len(updated)} tickers\\.")


def cmd_position(bot: "TelegramBot", message: dict[str, Any], args: list[str]) -> None:
    """Update or clear a position.

    /position NVDA 125.50 100   → set cost and qty
    /position NVDA clear        → clear (set to NA)
    /position NVDA              → show current
    """
    from tradingagents.batch.watchlist import update_position, get_position, load_watchlist
    chat_id = message["chat"]["id"]

    if not args:
        bot.send_plain(chat_id, "用法：\n/position TICKER 成本价 数量\n/position TICKER clear\n例：/position NVDA 125.50 100")
        return

    ticker = args[0].upper()
    data = load_watchlist(bot.config["watchlist_path"])
    if ticker not in [t.upper() for t in data["tickers"]]:
        bot.send_plain(chat_id, f"{ticker} 不在自选列表中，请先用 /add {ticker} 添加。")
        return

    # Clear
    if len(args) >= 2 and args[1].lower() in ("clear", "清空", "0", "no", "na"):
        update_position(bot.config["watchlist_path"], ticker, None, None)
        bot.send_plain(chat_id, f"✓ {ticker} 持仓已清空（NA）")
        return

    # Set position
    if len(args) >= 3:
        try:
            cost = float(args[1])
            qty = float(args[2])
            update_position(bot.config["watchlist_path"], ticker, cost, qty)
            total = cost * qty
            bot.send_plain(chat_id, f"✓ {ticker} 持仓已更新：{qty:,.0f} 股 @ ${cost:,.2f}（总成本 ${total:,.2f}）")
            return
        except ValueError:
            bot.send_plain(chat_id, "格式错误，请用：/position NVDA 125.50 100")
            return

    # Show current
    pos = get_position(bot.config["watchlist_path"], ticker)
    if pos and pos.get("cost") and pos.get("qty"):
        total = pos["cost"] * pos["qty"]
        bot.send_plain(chat_id, f"📋 {ticker} 当前持仓：{pos['qty']:,.0f} 股 @ ${pos['cost']:,.2f}（总成本 ${total:,.2f}）\n\n更新：/position {ticker} 成本价 数量\n清空：/position {ticker} clear")
    else:
        bot.send_plain(chat_id, f"📋 {ticker}：未持仓（NA）\n\n设置持仓：/position {ticker} 成本价 数量")


def cmd_status(bot: "TelegramBot", message: dict[str, Any], args: list[str]) -> None:
    chat_id = message["chat"]["id"]
    status = bot.job_queue.get_status()

    lines: list[str] = []
    current = status.get("current")
    if current:
        mins, secs = divmod(current["elapsed_s"], 60)
        lines.append(f"⚙️ *Running:* {current['description']} \\({mins:02d}:{secs:02d}\\)")
    else:
        lines.append("💤 No job running")

    pending = status.get("pending", [])
    if pending:
        lines.append(f"\n🕐 *Queue* \\({len(pending)}\\):")
        for job in pending[:5]:
            lines.append(f"  • {job['description']}")
        if len(pending) > 5:
            lines.append(f"  … and {len(pending)-5} more")
    else:
        lines.append("Queue empty")

    bot.send(chat_id, "\n".join(lines))


# ── Dispatch table ────────────────────────────────────────────────────────────

COMMANDS: dict[str, Any] = {
    "/help":     cmd_help,
    "/analyze":  cmd_analyze,
    "/batch":    cmd_batch,
    "/list":     cmd_list,
    "/add":      cmd_add,
    "/remove":   cmd_remove,
    "/position": cmd_position,
    "/status":   cmd_status,
}
