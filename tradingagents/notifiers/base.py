"""Notifier protocol — any concrete notifier must implement send()."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class Notifier(ABC):
    @abstractmethod
    def send(self, title: str, body: str, url: Optional[str] = None) -> None:
        """Send a notification.

        Args:
            title: Short subject line.
            body:  Main notification text.
            url:   Optional deep-link URL shown to the user (e.g. report path).
        """
