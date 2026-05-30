"""Telegram Bot notifier.

Required environment variables:
  TELEGRAM_BOT_TOKEN   — token from @BotFather
  TELEGRAM_CHAT_ID     — your personal or group chat ID

The message is sent via the Telegram Bot API sendMessage endpoint using
Markdown v2 formatting.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from .base import Notifier

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT = 10  # seconds


def _escape_md(text: str) -> str:
    """Escape characters that are special in Telegram MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in text)


class TelegramNotifier(Notifier):
    """Send notifications via a Telegram Bot.

    Token and chat ID are read from environment variables at send time so
    that the notifier can be constructed before env vars are loaded (e.g.
    from a .env file).
    """

    def send(self, title: str, body: str, url: Optional[str] = None) -> None:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

        if not token or not chat_id:
            logger.warning(
                "Telegram notification skipped: "
                "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set."
            )
            return

        text = f"*{_escape_md(title)}*\n\n{_escape_md(body)}"
        if url:
            text += f"\n\n`{_escape_md(url)}`"

        try:
            resp = requests.post(
                _API_BASE.format(token=token),
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": True,
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Telegram notification failed: %s", exc)
