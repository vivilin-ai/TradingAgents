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
    bot.send(message["chat"]["id"], (
        "📈 *TradingAgents Bot*\n\n"
        "/analyze TICKER \\[--date YYYY-MM-DD\\] — single-stock analysis\n"
        "/batch \\[--date YYYY-MM-DD\\] — analyse full watchlist\n"
        "/list — show watchlist\n"
        "/add TICKER \\[TICKER …\\] — add to watchlist\n"
        "/remove TICKER \\[TICKER …\\] — remove from watchlist\n"
        "/status — current job queue\n"
        "/help — this message"
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

    date_label = date_str or "latest trading day"
    runner = BatchRunner(config=bot.config)

    def run():
        return runner.run_single(ticker, trade_date=date_str, mode="manual")

    def on_complete(job, result, error):
        if error or (result and result.get("error")):
            err_msg = str(error or result.get("error", "unknown error"))
            bot.send(chat_id, f"❌ *{ticker}* analysis failed:\n`{err_msg[:300]}`")
            return
        pm = result.get("pm_decision", "") or ""
        rating = result.get("rating", "—")
        header = f"📊 *{ticker}* · {result.get('date', '')} · Rating: *{rating}*\n\n"
        _send_long(bot, chat_id, header + pm)

    _, pos = bot.job_queue.add(f"{ticker} {date_label}", run, on_complete)
    bot.send(chat_id, f"✓ *{ticker}* queued (position {pos}). I'll send the result when done.")


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
    chat_id = message["chat"]["id"]
    if not args:
        bot.send(chat_id, "Usage: /add TICKER \\[TICKER …\\]")
        return
    updated = add_tickers(bot.config["watchlist_path"], args)
    added = [t.upper() for t in args]
    bot.send(chat_id, f"✓ Added: {', '.join(added)}\\. Watchlist now has {len(updated)} tickers\\.")


def cmd_remove(bot: "TelegramBot", message: dict[str, Any], args: list[str]) -> None:
    chat_id = message["chat"]["id"]
    if not args:
        bot.send(chat_id, "Usage: /remove TICKER \\[TICKER …\\]")
        return
    updated = remove_tickers(bot.config["watchlist_path"], args)
    removed = [t.upper() for t in args]
    bot.send(chat_id, f"Removed: {', '.join(removed)}\\. Watchlist now has {len(updated)} tickers\\.")


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
    "/help":    cmd_help,
    "/analyze": cmd_analyze,
    "/batch":   cmd_batch,
    "/list":    cmd_list,
    "/add":     cmd_add,
    "/remove":  cmd_remove,
    "/status":  cmd_status,
}
