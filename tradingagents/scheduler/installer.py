"""Generate and install launchd plists (macOS) or crontab entries (Linux)
for each enabled ScheduledTask.

Each task becomes one launchd job:
  Label: com.tradingagents.<task_name>
  Command: tradingagents scheduled-run <task_name>
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .tasks import ScheduledTask, load_tasks

_LAUNCHD_DIR = Path.home() / "Library" / "LaunchAgents"
_LABEL_PREFIX = "com.tradingagents."
_CRON_MARKER = "# tradingagents-task:"
_LOG_DIR = Path.home() / ".tradingagents" / "logs"


def _python_and_args() -> tuple[str, list[str]]:
    """Return (python_executable, base_args) for the launchd ProgramArguments.

    We call .venv/bin/python -m cli.main directly instead of going through
    the tradingagents wrapper script.  The wrapper reads pyvenv.cfg via the
    Python C bootstrap, which macOS blocks for launchd processes that don't
    have explicit file-system access grants.  Calling the interpreter binary
    itself bypasses that restriction.
    """
    # Prefer the venv Python that is running right now
    python = sys.executable
    return python, ["-m", "cli.main"]


def _plist_path(task_name: str) -> Path:
    return _LAUNCHD_DIR / f"{_LABEL_PREFIX}{task_name}.plist"


def _cron_entry(task: ScheduledTask, cmd: str) -> str:
    log = _LOG_DIR / f"{task.name}.log"
    return (
        f"{task.schedule} cd {Path.cwd()} && {cmd} scheduled-run {task.name} "
        f">> {log} 2>&1  {_CRON_MARKER}{task.name}"
    )


def _plist_content(task: ScheduledTask) -> str:
    label = f"{_LABEL_PREFIX}{task.name}"
    log_out = _LOG_DIR / f"{task.name}.log"
    log_err = _LOG_DIR / f"{task.name}_error.log"
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    python, base_args = _python_and_args()
    project_dir = str(Path.cwd())

    # Build ProgramArguments: python -m cli.main scheduled-run <task_name>
    prog_args = "\n        ".join(
        f"<string>{a}</string>" for a in [python] + base_args + ["scheduled-run", task.name]
    )

    # Parse cron expression: min hour dom month dow
    parts = task.schedule.strip().split()
    if len(parts) < 5:
        raise ValueError(f"Invalid cron expression: '{task.schedule}'")
    minute, hour = parts[0], parts[1]

    cal: list[str] = []
    if minute != "*":
        cal.append(f"<key>Minute</key><integer>{int(minute)}</integer>")
    if hour != "*":
        cal.append(f"<key>Hour</key><integer>{int(hour)}</integer>")

    dow = parts[4]
    if dow not in ("*", "?"):
        if "-" in dow:
            start_d, end_d = (int(x) for x in dow.split("-"))
            cal_items = [
                f"<dict>{''.join(cal)}<key>Weekday</key><integer>{d}</integer></dict>"
                for d in range(start_d, end_d + 1)
            ]
            interval_xml = f"<array>{''.join(cal_items)}</array>"
        else:
            cal.append(f"<key>Weekday</key><integer>{int(dow)}</integer>")
            interval_xml = f"<dict>{''.join(cal)}</dict>"
    else:
        interval_xml = f"<dict>{''.join(cal)}</dict>"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        {prog_args}
    </array>
    <key>WorkingDirectory</key>
    <string>{project_dir}</string>
    <key>StartCalendarInterval</key>
    {interval_xml}
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{log_out}</string>
    <key>StandardErrorPath</key>
    <string>{log_err}</string>
</dict>
</plist>
"""


# ── Public API ────────────────────────────────────────────────────────────────

def installed_task_names() -> list[str]:
    """Names of tasks currently present in the system scheduler.

    Read from launchd/crontab itself rather than the YAML, so tasks deleted
    or disabled in the YAML are still discovered — otherwise they keep firing
    with nothing left to clean them up.
    """
    if platform.system() == "Darwin":
        if not _LAUNCHD_DIR.exists():
            return []
        return sorted(
            p.stem[len(_LABEL_PREFIX):]
            for p in _LAUNCHD_DIR.glob(f"{_LABEL_PREFIX}*.plist")
        )
    names = []
    for line in _read_crontab().splitlines():
        if _CRON_MARKER in line:
            names.append(line.rsplit(_CRON_MARKER, 1)[1].strip())
    return sorted(set(names))


def uninstall_task(name: str) -> bool:
    """Remove a single task from the system scheduler. True if it was there."""
    if platform.system() == "Darwin":
        plist = _plist_path(name)
        if not plist.exists():
            return False
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        plist.unlink()
        return True

    existing = _read_crontab()
    marker = f"{_CRON_MARKER}{name}"
    lines = [l for l in existing.splitlines() if marker not in l]
    if len(lines) == len(existing.splitlines()):
        return False
    _write_crontab(lines)
    return True


def install_all(tasks_path: Optional[str] = None) -> list[str]:
    """Install all enabled tasks and prune anything else.

    Tasks removed from the YAML — or disabled — are uninstalled here, so the
    scheduler always mirrors the task file exactly. Returns installed names.
    """
    tasks = [t for t in load_tasks(tasks_path) if t.enabled]
    wanted = {t.name for t in tasks}
    for stale in installed_task_names():
        if stale not in wanted:
            uninstall_task(stale)

    installed: list[str] = []
    if platform.system() == "Darwin":
        _LAUNCHD_DIR.mkdir(parents=True, exist_ok=True)
        for task in tasks:
            plist = _plist_path(task.name)
            plist.write_text(_plist_content(task), encoding="utf-8")
            subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
            subprocess.run(["launchctl", "load", str(plist)], capture_output=True)
            installed.append(task.name)
    else:
        python, base_args = _python_and_args()
        cmd = f"{python} {' '.join(base_args)}"
        _install_crontab(tasks, cmd)
        installed = [t.name for t in tasks]

    return installed


def uninstall_all(tasks_path: Optional[str] = None) -> list[str]:
    """Uninstall every TradingAgents task found in the system scheduler."""
    removed: list[str] = []

    if platform.system() == "Darwin":
        for name in installed_task_names():
            if uninstall_task(name):
                removed.append(name)
    else:
        removed = installed_task_names()
        _remove_crontab_all()

    return removed


def task_status(tasks_path: Optional[str] = None) -> dict[str, bool]:
    """Return {task_name: is_installed} for all tasks."""
    tasks = load_tasks(tasks_path)
    status: dict[str, bool] = {}

    if platform.system() == "Darwin":
        for task in tasks:
            status[task.name] = _plist_path(task.name).exists()
    else:
        crontab = _read_crontab()
        for task in tasks:
            marker = f"{_CRON_MARKER}{task.name}"
            status[task.name] = any(marker in line for line in crontab.splitlines())

    return status


# ── crontab helpers ───────────────────────────────────────────────────────────

def crontab_available() -> bool:
    """Whether a crontab binary exists on PATH."""
    return shutil.which("crontab") is not None


def _read_crontab() -> str:
    """Current user crontab, or "" when empty or cron is not installed."""
    if not crontab_available():
        return ""
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except OSError:
        return ""
    return result.stdout if result.returncode == 0 else ""


def _write_crontab(lines: list[str]) -> None:
    if not crontab_available():
        raise RuntimeError(
            "crontab not found on PATH — install cron, or run TradingAgents "
            "scheduling on macOS where launchd is used instead."
        )
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True)


def _install_crontab(tasks: list[ScheduledTask], cmd: str) -> None:
    existing = _read_crontab()
    # Remove old entries for these tasks
    names = {t.name for t in tasks}
    lines = [l for l in existing.splitlines() if not any(f"{_CRON_MARKER}{n}" in l for n in names)]
    for task in tasks:
        lines.append(_cron_entry(task, cmd))
    _write_crontab(lines)


def _remove_crontab_all() -> None:
    existing = _read_crontab()
    lines = [l for l in existing.splitlines() if _CRON_MARKER not in l]
    _write_crontab(lines)
