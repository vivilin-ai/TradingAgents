"""Unit tests for the notifier implementations."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.notifiers import create_notifier, NoopNotifier, TelegramNotifier
from tradingagents.notifiers.telegram import _escape_md


# ── NoopNotifier ──────────────────────────────────────────────────────────────

def test_noop_send_does_not_raise():
    n = NoopNotifier()
    n.send("title", "body", url="http://example.com")  # must not raise


# ── create_notifier ───────────────────────────────────────────────────────────

def test_create_notifier_none():
    n = create_notifier({"notifier": "none"})
    assert isinstance(n, NoopNotifier)


def test_create_notifier_missing_key():
    n = create_notifier({})
    assert isinstance(n, NoopNotifier)


def test_create_notifier_telegram():
    n = create_notifier({"notifier": "telegram"})
    assert isinstance(n, TelegramNotifier)


# ── TelegramNotifier ──────────────────────────────────────────────────────────

def test_telegram_skips_when_no_env(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    n = TelegramNotifier()
    # Should log a warning and return without raising
    n.send("title", "body")


def test_telegram_sends_message(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None

    with patch("tradingagents.notifiers.telegram.requests.post", return_value=mock_resp) as mock_post:
        TelegramNotifier().send("Test title", "Test body", url="/path/to/report")

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs["json"]
    assert payload["chat_id"] == "12345"
    assert "Test title" in payload["text"]
    assert "Test body" in payload["text"]


def test_telegram_handles_request_error(monkeypatch):
    import requests as req
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    with patch("tradingagents.notifiers.telegram.requests.post", side_effect=req.ConnectionError("timeout")):
        # Should log an error but not raise
        TelegramNotifier().send("title", "body")


# ── _escape_md ────────────────────────────────────────────────────────────────

def test_escape_md_special_chars():
    raw = "Hello. World! (test) [link] #tag"
    escaped = _escape_md(raw)
    # All special chars should be escaped
    assert "\\." in escaped
    assert "\\!" in escaped
    assert "\\(" in escaped
    assert "\\[" in escaped
    assert "\\#" in escaped


def test_escape_md_plain_text():
    assert _escape_md("NVDA") == "NVDA"
