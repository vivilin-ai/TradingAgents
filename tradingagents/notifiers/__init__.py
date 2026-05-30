from .base import Notifier
from .noop import NoopNotifier
from .telegram import TelegramNotifier


def create_notifier(config: dict) -> "Notifier":
    """Return a Notifier instance based on config['notifier']."""
    kind = (config.get("notifier") or "none").lower()
    if kind == "telegram":
        return TelegramNotifier()
    return NoopNotifier()


__all__ = ["Notifier", "NoopNotifier", "TelegramNotifier", "create_notifier"]
