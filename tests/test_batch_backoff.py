"""A connection failure under concurrent load must trigger the same
reduce-concurrency-and-wait remedy as a clean rate-limit response.

Reported scenario: a scheduled batch run with several US tickers and one HK
ticker all hitting DeepSeek concurrently. Only one ticker succeeded; the rest
failed with openai.APIConnectionError's default message, "Connection error.".
That message contains no HTTP status code, so it previously fell through
_is_rate_limit's keyword list entirely and was retried after a flat 5-second
pause at unchanged concurrency — the same conditions that caused the failure
in the first place.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from tradingagents.batch.runner import BatchRunner, _needs_backoff
from tradingagents.default_config import DEFAULT_CONFIG


# ── _needs_backoff ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("error", [
    "Connection error.",                      # openai.APIConnectionError default
    "Error code: 429 - rate limit exceeded",
    "APIConnectionError: Connection error.",
    "httpx.ProxyError: Unable to connect to proxy",
    "ConnectionResetError: Connection reset by peer",
    "ConnectionRefusedError: [Errno 61] Connection refused",
    "Remote end closed connection without response",
])
def test_transient_failures_trigger_backoff(error):
    assert _needs_backoff(error) is True


@pytest.mark.parametrize("error", [
    "KeyError: 'final_trade_decision'",
    "No price data returned for 'FOO'",
    "ValueError: invalid ticker",
])
def test_unrelated_failures_do_not_trigger_backoff(error):
    assert _needs_backoff(error) is False


# ── run_batch retry loop ─────────────────────────────────────────────────────

def _make_state(ticker: str) -> dict:
    return {
        "company_of_interest": ticker,
        "trade_date": "2026-09-13",
        "final_trade_decision": "**Rating**: Hold\nNo strong signal.",
    }


@pytest.fixture()
def tmp_config(tmp_path):
    cfg = DEFAULT_CONFIG.copy()
    cfg["watchlist_path"] = str(tmp_path / "watchlist.yaml")
    cfg["reports_root"] = str(tmp_path / "reports")
    cfg["batch_max_workers"] = 3
    cfg["batch_max_retries"] = 1
    cfg["batch_retry_wait"] = 30
    return cfg


def test_connection_error_reduces_concurrency_and_waits_longer(tmp_config):
    """One ticker (the HK one) succeeds; the rest fail with the exact
    connection-error message DeepSeek/openai produces under load. The retry
    must go through the backoff path (reduced workers, tens-of-seconds wait),
    not the 5-second flat-retry path for unrelated failures."""
    tickers = ["GOOG", "NVDA", "MSFT", "0100.HK"]

    def propagate(ticker, trade_date, extra_context=""):
        if ticker == "0100.HK":
            return _make_state(ticker), "Hold"
        raise ConnectionError("Connection error.")

    backoff_calls = []

    with patch("tradingagents.batch.runner.TradingAgentsGraph") as MockGraph, \
         patch("time.sleep") as mock_sleep:
        MockGraph.return_value.propagate.side_effect = propagate
        runner = BatchRunner(config=tmp_config)
        results, _ = runner.run_batch(
            tickers=tickers, trade_date="2026-09-13", narrative=False,
            on_backoff=lambda *args: backoff_calls.append(args),
        )

    by_ticker = {r["ticker"]: r for r in results}
    assert by_ticker["0100.HK"]["error"] is None
    for t in ("GOOG", "NVDA", "MSFT"):
        assert "Connection error" in by_ticker[t]["error"]

    # The backoff callback fired with a reduced worker count and a
    # tens-of-seconds wait — not the old 5-second unconditional pause.
    assert len(backoff_calls) == 1
    failed_tickers, old_workers, new_workers, wait_s = backoff_calls[0]
    assert set(failed_tickers) == {"GOOG", "NVDA", "MSFT"}
    assert new_workers < old_workers
    assert wait_s >= 30
    mock_sleep.assert_any_call(wait_s)


def test_unrelated_failure_still_uses_the_short_retry_path(tmp_config):
    """A failure with nothing to do with load (e.g. a bad ticker) must not
    trigger the backoff callback or reduce concurrency."""
    def propagate(ticker, trade_date, extra_context=""):
        raise ValueError("invalid ticker symbol")

    backoff_calls = []

    with patch("tradingagents.batch.runner.TradingAgentsGraph") as MockGraph, \
         patch("time.sleep") as mock_sleep:
        MockGraph.return_value.propagate.side_effect = propagate
        runner = BatchRunner(config=tmp_config)
        runner.run_batch(
            tickers=["FOO"], trade_date="2026-09-13", narrative=False,
            on_backoff=lambda *args: backoff_calls.append(args),
        )

    assert backoff_calls == []
    mock_sleep.assert_any_call(5)
