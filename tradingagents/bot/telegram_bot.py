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
from .commands import COMMANDS

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"
_SEND_TIMEOUT = 15
_POLL_TIMEOUT = 30   # long-poll window; counted against Telegram's server


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

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the job queue worker and enter the polling loop (blocks)."""
        if not self.token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not set.")

        self.job_queue.start()
        self._running = True
        logger.info("Bot started. Allowed IDs: %s", self.allowed_ids or "(none)")

        while self._running:
            try:
                updates = self._get_updates()
                for update in updates:
                    self._handle_update(update)
            except requests.RequestException as exc:
                logger.warning("Poll error: %s — retrying in 5s", exc)
                time.sleep(5)
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
            return  # ignore non-commands

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
