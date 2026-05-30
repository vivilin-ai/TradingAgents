"""Unit tests for the scheduler module."""

from __future__ import annotations

import pytest
from tradingagents.scheduler.tasks import (
    ScheduledTask,
    add_task,
    load_tasks,
    remove_task,
    save_tasks,
)


@pytest.fixture()
def tmp_tasks(tmp_path):
    return str(tmp_path / "tasks.yaml")


def test_load_tasks_missing_file(tmp_tasks):
    assert load_tasks(tmp_tasks) == []


def test_add_and_load(tmp_tasks):
    task = ScheduledTask(name="daily_nvda", schedule="0 8 * * 1-5", target="NVDA")
    add_task(task, tmp_tasks)
    tasks = load_tasks(tmp_tasks)
    assert len(tasks) == 1
    assert tasks[0].name == "daily_nvda"
    assert tasks[0].target == "NVDA"


def test_add_replaces_existing(tmp_tasks):
    t1 = ScheduledTask(name="foo", schedule="0 8 * * *", target="NVDA")
    t2 = ScheduledTask(name="foo", schedule="0 9 * * *", target="AAPL")
    add_task(t1, tmp_tasks)
    add_task(t2, tmp_tasks)
    tasks = load_tasks(tmp_tasks)
    assert len(tasks) == 1
    assert tasks[0].schedule == "0 9 * * *"
    assert tasks[0].target == "AAPL"


def test_remove_task(tmp_tasks):
    add_task(ScheduledTask(name="a", schedule="0 8 * * *", target="NVDA"), tmp_tasks)
    add_task(ScheduledTask(name="b", schedule="0 9 * * *", target="AAPL"), tmp_tasks)
    remove_task("a", tmp_tasks)
    tasks = load_tasks(tmp_tasks)
    assert len(tasks) == 1
    assert tasks[0].name == "b"


def test_remove_unknown_raises(tmp_tasks):
    with pytest.raises(KeyError):
        remove_task("nonexistent", tmp_tasks)


def test_task_tickers_single(tmp_tasks):
    task = ScheduledTask(name="t", schedule="*", target="NVDA")
    assert task.tickers() == ["NVDA"]
    assert not task.is_watchlist()


def test_task_tickers_list(tmp_tasks):
    task = ScheduledTask(name="t", schedule="*", target="NVDA,AAPL,MSFT")
    assert task.tickers() == ["NVDA", "AAPL", "MSFT"]


def test_task_is_watchlist():
    task = ScheduledTask(name="t", schedule="*", target="watchlist")
    assert task.is_watchlist()
    assert task.tickers() is None


def test_save_and_reload_roundtrip(tmp_tasks):
    tasks = [
        ScheduledTask(name="weekly", schedule="0 18 * * 1", target="watchlist", enabled=True),
        ScheduledTask(name="daily", schedule="0 8 * * 1-5", target="NVDA", enabled=False),
    ]
    save_tasks(tasks, tmp_tasks)
    reloaded = load_tasks(tmp_tasks)
    assert len(reloaded) == 2
    assert reloaded[0].name == "weekly"
    assert reloaded[1].enabled is False
