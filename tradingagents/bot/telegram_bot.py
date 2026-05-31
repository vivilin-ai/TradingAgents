"""Telegram Bot: long-polling loop with command routing and chat-ID whitelist.

The bot uses the Telegram Bot API directly via ``requests`` (already a project
dependency) — no third-party bot framework needed.

Security: every incoming message is checked against TELEGRAM_ALLOWED_CHAT_IDS
before any command handler is invoked.  Messages from unknown chat IDs are
silently dropped.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import requests

from .queue import JobQueue
from .commands import COMMANDS, _split

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"
_SEND_TIMEOUT = 15
_POLL_TIMEOUT = 10   # short poll to avoid proxy connection resets


class TelegramBot:
    """Telegram Bot with long-polling and a serial job queue.

    Environment variables read at construction time:
      TELEGRAM_BOT_TOKEN          — required
      TELEGRAM_CHAT_ID            — primary chat for outgoing-only sends
      TELEGRAM_ALLOWED_CHAT_IDS   — comma-separated whitelist of chat IDs
                                    that may issue commands.  If empty,
                                    defaults to TELEGRAM_CHAT_ID only.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.primary_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

        raw_allowed = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
        if raw_allowed:
            self.allowed_ids: set[str] = {c.strip() for c in raw_allowed.split(",") if c.strip()}
        elif self.primary_chat_id:
            self.allowed_ids = {self.primary_chat_id}
        else:
            self.allowed_ids = set()

        self.job_queue = JobQueue()
        self._offset = 0
        self._running = False
        # Tracks pending position questions: {chat_id: {ticker, date}}
        self._pending_positions: dict[str, dict] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the job queue worker and enter the polling loop (blocks)."""
        if not self.token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not set.")

        self.job_queue.start()
        self._running = True
        logger.info("Bot started. Allowed IDs: %s", self.allowed_ids or "(none)")

        _backoff = 1
        while self._running:
            try:
                updates = self._get_updates()
                for update in updates:
                    self._handle_update(update)
                _backoff = 1  # reset backoff on success
            except (ConnectionResetError, ConnectionAbortedError):
                # Expected with proxies; suppress to debug to avoid terminal spam
                logger.debug("Poll: connection reset by proxy, retrying in %ds", _backoff)
                time.sleep(_backoff)
                _backoff = min(_backoff * 2, 10)
            except requests.RequestException as exc:
                logger.debug("Poll error: %s — retrying in %ds", exc, _backoff)
                time.sleep(_backoff)
                _backoff = min(_backoff * 2, 10)
            except Exception as exc:
                logger.error("Unexpected error in poll loop: %s", exc, exc_info=True)
                time.sleep(2)

    def stop(self) -> None:
        self._running = False
        self.job_queue.stop()

    def send(self, chat_id: int | str, text: str) -> bool:
        """Send a MarkdownV2-formatted message.  Returns True on success."""
        if not self.token:
            return False
        try:
            resp = requests.post(
                _API.format(token=self.token, method="sendMessage"),
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": True,
                },
                timeout=_SEND_TIMEOUT,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as exc:
            logger.error("send() failed to %s: %s", chat_id, exc)
            return False

    def send_plain(self, chat_id: int | str, text: str) -> bool:
        """Send a plain-text message (no markdown parsing)."""
        if not self.token:
            return False
        try:
            resp = requests.post(
                _API.format(token=self.token, method="sendMessage"),
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                timeout=_SEND_TIMEOUT,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as exc:
            logger.error("send_plain() failed to %s: %s", chat_id, exc)
            return False

    # ── Internals ─────────────────────────────────────────────────────────────

    def _get_updates(self) -> list[dict]:
        resp = requests.get(
            _API.format(token=self.token, method="getUpdates"),
            params={"offset": self._offset, "timeout": _POLL_TIMEOUT},
            timeout=_POLL_TIMEOUT + 10,
        )
        resp.raise_for_status()
        data = resp.json()
        updates = data.get("result", [])
        if updates:
            self._offset = updates[-1]["update_id"] + 1
        return updates

    def _handle_update(self, update: dict) -> None:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat_id = str(message.get("chat", {}).get("id", ""))
        text: str = message.get("text", "").strip()

        if not text.startswith("/"):
            # Handle pending position reply
            if str(chat_id) in self._pending_positions:
                self._handle_position_reply(message, text)
            return

        # Whitelist check
        if self.allowed_ids and chat_id not in self.allowed_ids:
            logger.warning("Ignoring message from unauthorized chat_id=%s", chat_id)
            return

        # Extract command and args (strip bot username if present, e.g. /analyze@MyBot)
        parts = text.split()
        raw_cmd = parts[0].split("@")[0].lower()
        args = parts[1:]

        handler = COMMANDS.get(raw_cmd)
        if handler is None:
            self.send(chat_id, f"Unknown command: `{raw_cmd}`\\. Try /help\\.")
            return

        try:
            handler(self, message, args)
        except Exception as exc:
            logger.error("Handler %s raised: %s", raw_cmd, exc, exc_info=True)
            self.send_plain(chat_id, f"Internal error in {raw_cmd}: {exc}")

    def _handle_position_reply(self, message: dict, text: str) -> None:
        """Process a position-info reply that follows a /analyze prompt."""
        from tradingagents.batch.runner import BatchRunner
        chat_id = str(message.get("chat", {}).get("id", ""))
        pending = self._pending_positions.pop(chat_id, None)
        if not pending:
            return

        ticker = pending["ticker"]
        date_str = pending.get("date")
        date_label = date_str or "latest trading day"

        # Parse reply
        position: dict | None = None
        if text.strip().lower() not in ("no", "n", "没有", "无"):
            parts = text.strip().split()
            try:
                cost = float(parts[0])
                qty = float(parts[1]) if len(parts) > 1 else None
                if qty is None:
                    raise ValueError("qty missing")
                position = {"cost": cost, "qty": qty}
            except (ValueError, IndexError):
                self.send_plain(
                    chat_id,
                    f"格式不对，请回复「成本价 数量」（如 125.50 100）或 no。"
                    f"已取消 {ticker} 分析，请重新发送 /analyze {ticker}。"
                )
                return

        # Confirm and queue
        if position:
            pos_label = f"{position['qty']:,.0f} 股 @ ${position['cost']:,.2f}"
        else:
            pos_label = "未持仓"

        runner = BatchRunner(config=self.config)

        def run():
            return runner.run_single(ticker, trade_date=date_str, mode="manual", position=position)

        def on_complete(job, result, error):
            if error or (result and result.get("error")):
                err_msg = str(error or result.get("error", "unknown error"))
                self.send_plain(chat_id, f"❌ {ticker} 分析失败：{err_msg[:300]}")
                return
            pm = result.get("pm_decision", "") or ""
            rating = result.get("rating", "—")
            header = f"📊 {ticker} · {result.get('date', '')} · 评级：{rating}\n\n"
            for chunk in _split(header + pm):
                self.send_plain(chat_id, chunk)

        _, pos = self.job_queue.add(f"{ticker} {date_label} [{pos_label}]", run, on_complete)
        self.send_plain(
            chat_id,
            f"✓ {ticker} 已加入队列（第 {pos} 位），持仓：{pos_label}。分析完成后发送结果。"
        )
