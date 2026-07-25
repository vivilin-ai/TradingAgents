"""Regression tests for price-cache poisoning in load_ohlcv.

A download that failed mid-flight used to write an empty CSV, and every later
run then failed with "No columns to parse from file" forever.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.dataflows import stockstats_utils


@pytest.fixture()
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(
        stockstats_utils, "get_config", lambda: {"data_cache_dir": str(tmp_path)}
    )
    return tmp_path


def _good_frame():
    idx = pd.bdate_range("2026-01-02", periods=10)
    return pd.DataFrame(
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1000},
        index=idx,
    ).rename_axis("Date")


def test_empty_download_is_not_cached(cache_dir):
    with patch.object(stockstats_utils.yf, "download", return_value=pd.DataFrame()):
        with pytest.raises(ValueError, match="No price data returned"):
            stockstats_utils.load_ohlcv("MARVELL", "2026-07-25")
    # Nothing may be left behind to poison the next run.
    assert list(cache_dir.glob("*.csv")) == []


def test_empty_cache_file_is_discarded_and_refetched(cache_dir):
    # Simulate the poisoned state left by an older build.
    with patch.object(stockstats_utils.yf, "download", return_value=_good_frame()):
        stockstats_utils.load_ohlcv("NVDA", "2026-07-25")
    cached = list(cache_dir.glob("NVDA-*.csv"))
    assert len(cached) == 1
    cached[0].write_text("", encoding="utf-8")

    with patch.object(stockstats_utils.yf, "download", return_value=_good_frame()) as dl:
        data = stockstats_utils.load_ohlcv("NVDA", "2026-07-25")
    assert dl.called, "an empty cache must trigger a refetch"
    assert not data.empty
    assert os.path.getsize(cached[0]) > 0


def test_valid_cache_is_reused_without_download(cache_dir):
    with patch.object(stockstats_utils.yf, "download", return_value=_good_frame()):
        first = stockstats_utils.load_ohlcv("NVDA", "2026-07-25")
    with patch.object(stockstats_utils.yf, "download") as dl:
        second = stockstats_utils.load_ohlcv("NVDA", "2026-07-25")
    dl.assert_not_called()
    assert len(second) == len(first)


def test_cache_without_close_column_is_discarded(cache_dir):
    with patch.object(stockstats_utils.yf, "download", return_value=_good_frame()):
        stockstats_utils.load_ohlcv("NVDA", "2026-07-25")
    cached = list(cache_dir.glob("NVDA-*.csv"))[0]
    cached.write_text("Date,Junk\n2026-01-02,1\n", encoding="utf-8")

    with patch.object(stockstats_utils.yf, "download", return_value=_good_frame()) as dl:
        stockstats_utils.load_ohlcv("NVDA", "2026-07-25")
    assert dl.called
