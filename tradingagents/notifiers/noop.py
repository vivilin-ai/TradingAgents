"""No-op notifier: silently discards every notification."""

from __future__ import annotations

import logging
from typing import Optional

from .base import Notifier

logger = logging.getLogger(__name__)


class NoopNotifier(Notifier):
    def send(self, title: str, body: str, url: Optional[str] = None) -> None:
        logger.debug("NoopNotifier: notification suppressed (%s)", title)
