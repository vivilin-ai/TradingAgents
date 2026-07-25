"""Removing a task must also stop it from running.

Previously `tasks remove` only edited the YAML while `uninstall_all` iterated
the YAML, so a removed task's launchd plist / crontab line was never cleaned
up and kept firing on schedule forever.
"""

from __future__ import annotations

import pytest

from tradingagents.scheduler import installer
from tradingagents.scheduler.tasks import ScheduledTask, save_tasks


@pytest.fixture()
def mac_env(tmp_path, monkeypatch):
    """launchd layout backed by a temp LaunchAgents dir, no real launchctl."""
    launch_dir = tmp_path / "LaunchAgents"
    launch_dir.mkdir()
    monkeypatch.setattr(installer, "_LAUNCHD_DIR", launch_dir)
    monkeypatch.setattr(installer, "_LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(installer.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **kw: None)
    monkeypatch.setattr(
        installer, "_plist_path",
        lambda name: launch_dir / f"{installer._LABEL_PREFIX}{name}.plist",
    )
    return launch_dir


def _tasks_file(tmp_path, tasks):
    path = str(tmp_path / "tasks.yaml")
    save_tasks(tasks, path)
    return path


def test_installed_task_names_reads_the_scheduler(mac_env, tmp_path):
    path = _tasks_file(tmp_path, [
        ScheduledTask(name="weekly", schedule="30 10 * * 0"),
        ScheduledTask(name="weekly_all", schedule="0 8 * * 6"),
    ])
    installer.install_all(path)
    assert installer.installed_task_names() == ["weekly", "weekly_all"]


def test_uninstall_task_removes_single_plist(mac_env, tmp_path):
    path = _tasks_file(tmp_path, [
        ScheduledTask(name="weekly", schedule="30 10 * * 0"),
        ScheduledTask(name="weekly_all", schedule="0 8 * * 6"),
    ])
    installer.install_all(path)

    assert installer.uninstall_task("weekly_all") is True
    assert installer.installed_task_names() == ["weekly"]
    # Removing something that is not installed is a no-op, not an error.
    assert installer.uninstall_task("weekly_all") is False


def test_install_all_prunes_tasks_dropped_from_yaml(mac_env, tmp_path):
    path = _tasks_file(tmp_path, [
        ScheduledTask(name="weekly", schedule="30 10 * * 0"),
        ScheduledTask(name="weekly_all", schedule="0 8 * * 6"),
    ])
    installer.install_all(path)

    # User deletes weekly_all from the task file, then reinstalls.
    save_tasks([ScheduledTask(name="weekly", schedule="30 10 * * 0")], path)
    installed = installer.install_all(path)

    assert installed == ["weekly"]
    assert installer.installed_task_names() == ["weekly"], "orphan must be pruned"


def test_install_all_prunes_disabled_tasks(mac_env, tmp_path):
    path = _tasks_file(tmp_path, [ScheduledTask(name="weekly", schedule="30 10 * * 0")])
    installer.install_all(path)

    save_tasks(
        [ScheduledTask(name="weekly", schedule="30 10 * * 0", enabled=False)], path
    )
    assert installer.install_all(path) == []
    assert installer.installed_task_names() == []


def test_uninstall_all_removes_orphans_not_in_yaml(mac_env, tmp_path):
    path = _tasks_file(tmp_path, [
        ScheduledTask(name="weekly", schedule="30 10 * * 0"),
        ScheduledTask(name="weekly_all", schedule="0 8 * * 6"),
    ])
    installer.install_all(path)

    # Simulate the old buggy flow: YAML entry gone, plist left behind.
    save_tasks([ScheduledTask(name="weekly", schedule="30 10 * * 0")], path)

    removed = installer.uninstall_all(path)
    assert sorted(removed) == ["weekly", "weekly_all"]
    assert installer.installed_task_names() == []


def test_crontab_installed_names(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.platform, "system", lambda: "Linux")
    monkeypatch.setattr(installer, "crontab_available", lambda: True)
    crontab = (
        f"0 8 * * 6 cd /x && run scheduled-run weekly_all  {installer._CRON_MARKER}weekly_all\n"
        f"30 10 * * 0 cd /x && run scheduled-run weekly  {installer._CRON_MARKER}weekly\n"
    )
    monkeypatch.setattr(installer, "_read_crontab", lambda: crontab)
    assert installer.installed_task_names() == ["weekly", "weekly_all"]
