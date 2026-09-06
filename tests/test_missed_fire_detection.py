"""Tests for detecting a scheduled task that launchd never triggered.

A task's launchctl exit status and its log content both describe the *last
time the job ran* — neither one can say whether it should have run again
since. Comparing the cron schedule against the wall clock is the only way to
tell "it ran and produced no new output" apart from "it never fired".
"""

from __future__ import annotations

import os
import platform
from datetime import datetime, timedelta

import pytest
from typer.testing import CliRunner

import cli.tasks as tasks_cli
from cli.tasks import _last_expected_fire
from tradingagents.scheduler import installer as installer_mod
from tradingagents.scheduler.tasks import ScheduledTask


# Reference "now": Sunday 2026-09-06 11:00 (after both 09:30 and 10:30 fire times).
SUNDAY_MORNING = datetime(2026, 9, 6, 11, 0)


def test_weekly_schedule_expects_the_most_recent_matching_weekday():
    # "30 9 * * 0" = every Sunday 09:30. 2026-09-06 is a Sunday.
    expected = _last_expected_fire("30 9 * * 0", SUNDAY_MORNING)
    assert expected == datetime(2026, 9, 6, 9, 30)


def test_before_todays_fire_time_falls_back_to_last_week():
    # Same schedule, but "now" is before today's 09:30 -> last Sunday's fire.
    early_sunday = datetime(2026, 9, 6, 8, 0)
    expected = _last_expected_fire("30 9 * * 0", early_sunday)
    assert expected == datetime(2026, 8, 30, 9, 30)


def test_exact_fire_moment_counts_as_already_fired():
    exact = datetime(2026, 9, 6, 9, 30)
    assert _last_expected_fire("30 9 * * 0", exact) == exact


def test_daily_schedule():
    expected = _last_expected_fire("0 8 * * *", datetime(2026, 9, 3, 9, 0))
    assert expected == datetime(2026, 9, 3, 8, 0)


def test_weekday_range():
    # "30 7 * * 1-5" = weekdays only. 2026-09-06 is Sunday (dow 0) -> not in
    # range, so the most recent match is Friday 2026-09-04.
    expected = _last_expected_fire("30 7 * * 1-5", SUNDAY_MORNING)
    assert expected == datetime(2026, 9, 4, 7, 30)


@pytest.mark.parametrize("schedule", [
    "30 9 1 * 0",     # day-of-month constrained: outside this tool's shape
    "30 9 * 6 0",     # month constrained
    "* 9 * * 0",      # non-numeric minute
    "30 * * * 0",     # non-numeric hour
    "30 9 * * a",     # unparseable day-of-week
    "30 9 * *",       # too few fields
])
def test_unsupported_shapes_return_none(schedule):
    assert _last_expected_fire(schedule, SUNDAY_MORNING) is None


def test_wildcard_day_of_week_matches_every_day():
    expected = _last_expected_fire("0 12 * * *", datetime(2026, 9, 6, 13, 0))
    assert expected == datetime(2026, 9, 6, 12, 0)


# ── end-to-end: doctor must surface the gap, not old log content ────────────

def _cron_ago(ago: timedelta) -> str:
    """A weekly cron string whose most recent fire was ``ago`` before now
    (``ago`` must be under 7 days). Pinned to the specific weekday of
    ``now - ago`` — a wildcard day-of-week would instead match today or
    yesterday, since every day qualifies, making it impossible to place the
    expected fire further back than one day.
    """
    assert ago < timedelta(days=7)
    t = datetime.now() - ago
    cron_dow = (t.weekday() + 1) % 7  # date.weekday(): Mon=0..Sun=6 -> cron: Sun=0..Sat=6
    return f"{t.minute} {t.hour} * * {cron_dow}"


def _run_doctor(monkeypatch, tmp_path, schedule: str, log_age: timedelta) -> str:
    """Invoke `tasks doctor` against one fake task whose only log is
    ``log_age`` old."""
    task = ScheduledTask(name="weekly_eval", schedule=schedule, target="evaluate")
    monkeypatch.setattr(tasks_cli, "load_tasks", lambda: [task])
    monkeypatch.setattr(tasks_cli, "task_status", lambda: {"weekly_eval": True})
    monkeypatch.setattr(tasks_cli, "installed_task_names", lambda: ["weekly_eval"])
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(installer_mod, "_read_crontab", lambda: "")
    monkeypatch.setattr(installer_mod, "_LOG_DIR", tmp_path)

    log = tmp_path / "weekly_eval.log"
    log.write_text(
        "scheduled-run: weekly_eval (target=evaluate)\n📈 done\n", encoding="utf-8"
    )
    stamp = (datetime.now() - log_age).timestamp()
    os.utime(log, (stamp, stamp))

    result = CliRunner().invoke(tasks_cli.app, ["doctor", "-n", "0"])
    assert result.exit_code == 0, result.output
    return result.output


def test_stale_log_is_reported_as_a_missed_fire(tmp_path, monkeypatch):
    # Should have fired 3 days ago (well past the 2h grace); the log predates
    # that by a full day — an unambiguous margin, so minute-level truncation
    # in the schedule vs. sub-second precision in the mtime can't flip which
    # side of "expected fire" the log lands on.
    schedule = _cron_ago(timedelta(days=3))
    output = _run_doctor(monkeypatch, tmp_path, schedule, log_age=timedelta(days=4))
    # Rich word-wraps long CJK lines to the console width, which can split a
    # target phrase across a line break; collapse whitespace before matching.
    flat = " ".join(output.split())
    assert "launchd 没有按计划" in flat
    assert "本应在" in flat


def test_log_newer_than_the_expected_fire_is_not_flagged(tmp_path, monkeypatch):
    # Should have fired 3 days ago, but the log is fresh — a later run
    # already covered this (or a more recent) window.
    schedule = _cron_ago(timedelta(days=3))
    output = _run_doctor(monkeypatch, tmp_path, schedule, log_age=timedelta(minutes=5))
    assert "launchd 没有按计划" not in output


def test_a_run_still_in_progress_is_not_flagged(tmp_path, monkeypatch):
    # Expected fire was only 30 minutes ago — inside the grace window for a
    # long-running batch — even though the only log predates it.
    schedule = _cron_ago(timedelta(minutes=30))
    output = _run_doctor(monkeypatch, tmp_path, schedule, log_age=timedelta(hours=1))
    assert "launchd 没有按计划" not in output
