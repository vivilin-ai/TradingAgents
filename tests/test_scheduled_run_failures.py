"""Tests for scheduled-run failure reporting and crontab robustness.

A scheduled job that fails must be visible: non-zero exit so launchd/cron
records it, the real error in the notification, and no crash when the host
has no crontab binary.
"""

from __future__ import annotations

import plistlib
import subprocess
from unittest.mock import MagicMock, patch

import pytest
import typer

from tradingagents.scheduler import installer
from tradingagents.scheduler.tasks import ScheduledTask


# ── crontab robustness ───────────────────────────────────────────────────────

def test_read_crontab_without_binary(monkeypatch):
    monkeypatch.setattr(installer.shutil, "which", lambda _: None)
    assert installer.crontab_available() is False
    assert installer._read_crontab() == ""  # must not raise


def test_read_crontab_handles_oserror(monkeypatch):
    monkeypatch.setattr(installer.shutil, "which", lambda _: "/usr/bin/crontab")

    def boom(*a, **kw):
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(installer.subprocess, "run", boom)
    assert installer._read_crontab() == ""


def test_write_crontab_without_binary_raises(monkeypatch):
    monkeypatch.setattr(installer.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="crontab not found"):
        installer._write_crontab(["* * * * * echo hi"])


def test_task_status_without_crontab(monkeypatch, tmp_path):
    """tasks list / doctor must survive a host with no cron installed."""
    monkeypatch.setattr(installer.platform, "system", lambda: "Linux")
    monkeypatch.setattr(installer.shutil, "which", lambda _: None)
    path = str(tmp_path / "tasks.yaml")
    from tradingagents.scheduler.tasks import save_tasks

    save_tasks([ScheduledTask(name="weekly", schedule="0 8 * * 6")], path)
    assert installer.task_status(path) == {"weekly": False}


# ── plist generation ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "schedule,expected",
    [
        ("30 7 * * 6", {"Minute": 30, "Hour": 7, "Weekday": 6}),
        ("0 8 * * 6", {"Minute": 0, "Hour": 8, "Weekday": 6}),
    ],
)
def test_plist_is_valid_and_scheduled_correctly(schedule, expected):
    task = ScheduledTask(name="weekly_eval", schedule=schedule, target="evaluate")
    data = plistlib.loads(installer._plist_content(task).encode())
    assert data["StartCalendarInterval"] == expected
    assert data["ProgramArguments"][-2:] == ["scheduled-run", "weekly_eval"]


def test_plist_weekday_range_expands():
    task = ScheduledTask(name="workday", schedule="30 7 * * 1-5", target="NVDA")
    data = plistlib.loads(installer._plist_content(task).encode())
    assert [d["Weekday"] for d in data["StartCalendarInterval"]] == [1, 2, 3, 4, 5]


# ── scheduled-run exit status ────────────────────────────────────────────────

def _run_task(tmp_path, monkeypatch, results):
    """Invoke scheduled_run with a stubbed BatchRunner returning ``results``."""
    from tradingagents.scheduler.tasks import save_tasks

    tasks_path = tmp_path / "scheduled_tasks.yaml"
    save_tasks(
        [ScheduledTask(name="weekly_all", schedule="0 8 * * 6", target="NVDA,AAPL")],
        str(tasks_path),
    )
    monkeypatch.setattr(
        "tradingagents.scheduler.tasks._tasks_path", lambda: tasks_path
    )

    sent: list[str] = []
    runner = MagicMock()
    runner.run_batch.return_value = (results, tmp_path / "summary.md")

    from cli.main import scheduled_run

    with patch("tradingagents.batch.runner.BatchRunner", return_value=runner), \
         patch("requests.post", side_effect=lambda *a, **kw: sent.append(kw.get("json", {}).get("text", ""))):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        try:
            scheduled_run(task_name="weekly_all", date="2026-07-25")
            exit_code = 0
        except typer.Exit as exc:
            exit_code = exc.exit_code
    return exit_code, sent


def test_all_tickers_failing_exits_nonzero(tmp_path, monkeypatch):
    results = [
        {"ticker": "NVDA", "error": "rate limit exceeded", "rating": "Hold"},
        {"ticker": "AAPL", "error": "rate limit exceeded", "rating": "Hold"},
    ]
    exit_code, sent = _run_task(tmp_path, monkeypatch, results)
    assert exit_code == 1
    assert sent, "a notification should still be sent"
    final = sent[-1]
    assert "定时任务失败" in final
    assert "rate limit exceeded" in final  # the real cause must be surfaced


def test_partial_success_exits_zero(tmp_path, monkeypatch):
    results = [
        {"ticker": "NVDA", "error": None, "rating": "Buy"},
        {"ticker": "AAPL", "error": "boom", "rating": "Hold"},
    ]
    exit_code, sent = _run_task(tmp_path, monkeypatch, results)
    assert exit_code == 0
    assert "定时任务完成" in sent[-1]
    assert "1/2 完成" in sent[-1]


def test_all_success_exits_zero(tmp_path, monkeypatch):
    results = [
        {"ticker": "NVDA", "error": None, "rating": "Buy"},
        {"ticker": "AAPL", "error": None, "rating": "Hold"},
    ]
    exit_code, sent = _run_task(tmp_path, monkeypatch, results)
    assert exit_code == 0
    assert "定时任务完成" in sent[-1]
