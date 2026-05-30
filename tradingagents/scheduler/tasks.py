"""Scheduled task definitions: load/save ~/.tradingagents/scheduled_tasks.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

import yaml

_DEFAULT_PATH = Path.home() / ".tradingagents" / "scheduled_tasks.yaml"


@dataclass
class ScheduledTask:
    """A single recurring analysis task.

    Attributes:
        name:     Unique identifier, used as sub-directory name in reports/.
        schedule: Cron expression, e.g. "0 8 * * 1-5".
        target:   "watchlist", a single ticker like "NVDA", or a comma-
                  separated list like "NVDA,AAPL,MSFT".
        enabled:  Whether the task is installed in launchd/crontab.
        analysts: Optional analyst subset; defaults to all four when empty.
    """
    name: str
    schedule: str
    target: str = "watchlist"
    enabled: bool = True
    analysts: list[str] = field(default_factory=list)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def tickers(self) -> Optional[list[str]]:
        """Return explicit ticker list, or None when target is 'watchlist'."""
        if self.target.lower() == "watchlist":
            return None
        parts = [t.strip().upper() for t in self.target.split(",") if t.strip()]
        return parts or None

    def is_watchlist(self) -> bool:
        return self.target.lower() == "watchlist"


# ── Persistence ───────────────────────────────────────────────────────────────

def _tasks_path() -> Path:
    return _DEFAULT_PATH


def load_tasks(path: Optional[str] = None) -> list[ScheduledTask]:
    """Load all scheduled tasks from YAML. Returns empty list if file absent."""
    p = Path(path) if path else _tasks_path()
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    tasks = []
    for item in data.get("tasks", []):
        tasks.append(ScheduledTask(
            name=item["name"],
            schedule=item["schedule"],
            target=item.get("target", "watchlist"),
            enabled=item.get("enabled", True),
            analysts=item.get("analysts", []),
        ))
    return tasks


def save_tasks(tasks: list[ScheduledTask], path: Optional[str] = None) -> None:
    p = Path(path) if path else _tasks_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"tasks": [asdict(t) for t in tasks]}
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def add_task(task: ScheduledTask, path: Optional[str] = None) -> list[ScheduledTask]:
    """Add or replace a task by name."""
    tasks = load_tasks(path)
    tasks = [t for t in tasks if t.name != task.name]
    tasks.append(task)
    save_tasks(tasks, path)
    return tasks


def remove_task(name: str, path: Optional[str] = None) -> list[ScheduledTask]:
    """Remove a task by name; raises KeyError if not found."""
    tasks = load_tasks(path)
    remaining = [t for t in tasks if t.name != name]
    if len(remaining) == len(tasks):
        raise KeyError(f"No task named '{name}'")
    save_tasks(remaining, path)
    return remaining
