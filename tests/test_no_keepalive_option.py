"""Opt-in fix for intermittent "Connection error." during real batch runs.

Root cause (confirmed empirically, not guessed): curl reproductions of the
exact failing request — single call, a long-duration call, and three
concurrent calls — all succeeded 100% of the time through the user's proxy.
The one structural difference between curl and the real client is that curl
opens a fresh TCP connection every time, while httpx (used by the openai SDK
under langchain_openai.ChatOpenAI) pools and reuses connections for
keepalive_expiry seconds. A connection that looks fresh to httpx's local
clock can have been silently killed somewhere on the proxy/network path in
between two calls of the same ticker's multi-step pipeline; reusing it then
fails with httpcore.RemoteProtocolError ("peer closed connection without
sending complete message body"), which surfaces to the app as
openai.APIConnectionError: "Connection error." — exactly the reported
symptom. httpx.HTTPTransport(retries=N) does not cover this: reading
httpcore's source shows its retry loop only wraps the initial connect step
(ConnectError/ConnectTimeout), not a mid-response RemoteProtocolError on a
reused connection.

The fix (llm_disable_keepalive) makes every request open and close its own
connection, matching curl's proven-reliable behaviour. It's opt-in (off by
default) since it costs an extra TCP+TLS handshake per call.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


def test_disabled_by_default():
    assert DEFAULT_CONFIG["llm_disable_keepalive"] is False


def test_off_by_default_no_http_client_kwargs():
    config = {**DEFAULT_CONFIG, "llm_temperature": 0.0}
    kwargs = TradingAgentsGraph._get_provider_kwargs(MagicMock(config=config))
    assert "http_client" not in kwargs
    assert "http_async_client" not in kwargs


def test_enabling_it_forwards_no_keepalive_http_clients():
    config = {**DEFAULT_CONFIG, "llm_disable_keepalive": True}
    kwargs = TradingAgentsGraph._get_provider_kwargs(MagicMock(config=config))

    sync_client = kwargs["http_client"]
    async_client = kwargs["http_async_client"]
    assert isinstance(sync_client, httpx.Client)
    assert isinstance(async_client, httpx.AsyncClient)
    assert sync_client._transport._pool._max_keepalive_connections == 0
    assert async_client._transport._pool._max_keepalive_connections == 0


def test_no_keepalive_client_still_follows_redirects_and_trusts_env():
    # Must not silently drop the openai SDK's own defaults (redirects) or
    # the proxy env vars (HTTP_PROXY/HTTPS_PROXY) a local proxy relies on.
    http_client, http_async_client = TradingAgentsGraph._build_no_keepalive_http_clients()
    assert http_client.follow_redirects is True
    assert http_async_client.follow_redirects is True
    assert http_client._trust_env is True
    assert http_async_client._trust_env is True


def test_reaches_the_openai_compatible_client():
    """End to end: the flag must actually land on the ChatOpenAI instance
    used for DeepSeek, not just in the intermediate kwargs dict."""
    from tradingagents.llm_clients import create_llm_client

    http_client, http_async_client = TradingAgentsGraph._build_no_keepalive_http_clients()
    llm = create_llm_client(
        provider="deepseek", model="deepseek-v4-pro", api_key="x",
        http_client=http_client, http_async_client=http_async_client,
    ).get_llm()
    assert llm.root_client._client is http_client
    assert llm.root_async_client._client is http_async_client
