"""CLI sub-commands for weekly batch analysis and schedule management.

Usage:
  tradingagents weekly-run
  tradingagents weekly-run --date 2026-05-26
  tradingagents weekly-run --no-narrative
  tradingagents weekly-run --no-notify

  tradingagents schedule install
  tradingagents schedule uninstall
  tradingagents schedule status
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

load_dotenv()
load_dotenv(".env.enterprise", override=False)

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.batch.runner import BatchRunner

console = Console()

# ── weekly-run ────────────────────────────────────────────────────────────────

weekly_app = typer.Typer(
    name="weekly-run",
    help="Run the weekly batch analysis over your watchlist.",
    invoke_without_command=True,
)

schedule_app = typer.Typer(
    name="schedule",
    help="Install or manage the weekly-run cron / launchd schedule.",
    no_args_is_help=True,
)


@weekly_app.callback(invoke_without_command=True)
def weekly_run(
    date: Optional[str] = typer.Option(
        None,
        "--date",
        help="Analysis date YYYY-MM-DD (default: most recent trading day).",
        metavar="DATE",
    ),
    no_narrative: bool = typer.Option(
        False,
        "--no-narrative",
        help="Skip the LLM cross-ticker narrative in summary.md.",
    ),
    no_notify: bool = typer.Option(
        False,
        "--no-notify",
        help="Do not send a notification when the run completes.",
    ),
) -> None:
    """Run TradingAgents for every ticker in the watchlist."""
    config = DEFAULT_CONFIG.copy()
    narrative = (not no_narrative) and config.get("weekly_summary_narrative", True)
    notify = not no_notify

    console.print(Panel(
        f"[bold green]Weekly Batch Run[/bold green]\n"
        f"[dim]Date: {date or 'most recent trading day'}  "
        f"Narrative: {'on' if narrative else 'off'}  "
        f"Notify: {'on' if notify else 'off'}[/dim]",
        border_style="green",
    ))

    runner = BatchRunner(config=config)
    try:
        summary_path = runner.run(
            trade_date=date,
            narrative=narrative,
            notify=notify,
        )
        console.print(f"\n[bold green]✓ Done![/bold green]  Summary → [cyan]{summary_path}[/cyan]")
    except Exception as exc:
        console.print(f"[bold red]Batch run failed:[/bold red] {exc}")
        raise typer.Exit(code=1)


# ── schedule ──────────────────────────────────────────────────────────────────

# Launchd plist label and file path (macOS)
_LAUNCHD_LABEL = "com.tradingagents.weekly"
_LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"

# Crontab marker (Linux / non-macOS)
_CRON_MARKER = "# tradingagents-weekly"


def _weekday_number(day: str) -> int:
    """Convert day name to cron weekday number (0=Sunday … 6=Saturday)."""
    days = {
        "sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3,
        "thursday": 4, "friday": 5, "saturday": 6,
    }
    return days.get(day.lower(), 1)  # default Monday


def _launchd_weekday(day: str) -> int:
    """Convert day name to launchd weekday number (0=Sunday … 6=Saturday)."""
    return _weekday_number(day)


def _tradingagents_cmd() -> str:
    """Path to the tradingagents executable in the current environment."""
    cmd = shutil.which("tradingagents")
    if cmd:
        return cmd
    # Fallback: use `python -m cli.main`
    return f"{sys.executable} -m cli.main"


def _plist_content(day: str, hour: int, minute: int, cmd: str) -> str:
    weekday = _launchd_weekday(day)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/sh</string>
        <string>-c</string>
        <string>cd {Path.cwd()} &amp;&amp; {cmd} weekly-run</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>{weekday}</integer>
        <key>Hour</key>
        <integer>{hour}</integer>
        <key>Minute</key>
        <integer>{minute}</integer>
    </dict>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{Path.home()}/.tradingagents/logs/weekly_schedule.log</string>
    <key>StandardErrorPath</key>
    <string>{Path.home()}/.tradingagents/logs/weekly_schedule_error.log</string>
</dict>
</plist>
"""


@schedule_app.command("install")
def schedule_install() -> None:
    """Install the weekly-run schedule (launchd on macOS, crontab on Linux)."""
    sched = DEFAULT_CONFIG.get("weekly_schedule", {})
    day = sched.get("day", "monday")
    time_str = sched.get("time", "09:00")
    try:
        hour, minute = (int(x) for x in time_str.split(":"))
    except ValueError:
        console.print(f"[red]Invalid weekly_schedule.time '{time_str}'. Use HH:MM format.[/red]")
        raise typer.Exit(1)

    cmd = _tradingagents_cmd()

    if platform.system() == "Darwin":
        _install_launchd(day, hour, minute, cmd)
    else:
        _install_crontab(day, hour, minute, cmd)


def _install_launchd(day: str, hour: int, minute: int, cmd: str) -> None:
    _LAUNCHD_PLIST.parent.mkdir(parents=True, exist_ok=True)
    _LAUNCHD_PLIST.write_text(_plist_content(day, hour, minute, cmd), encoding="utf-8")

    # Unload first in case it already exists
    subprocess.run(
        ["launchctl", "unload", str(_LAUNCHD_PLIST)],
        capture_output=True,
    )
    result = subprocess.run(
        ["launchctl", "load", str(_LAUNCHD_PLIST)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(f"[red]launchctl load failed:[/red] {result.stderr}")
        raise typer.Exit(1)

    console.print(
        f"[green]✓ Installed launchd schedule:[/green] "
        f"every {day.capitalize()} at {hour:02d}:{minute:02d}\n"
        f"[dim]Plist: {_LAUNCHD_PLIST}[/dim]"
    )


def _install_crontab(day: str, hour: int, minute: int, cmd: str) -> None:
    weekday = _weekday_number(day)
    cron_line = (
        f"{minute} {hour} * * {weekday} "
        f"cd {Path.cwd()} && {cmd} weekly-run "
        f">> {Path.home()}/.tradingagents/logs/weekly_schedule.log 2>&1"
        f"  {_CRON_MARKER}"
    )

    # Read current crontab (ignore error if empty)
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = result.stdout if result.returncode == 0 else ""

    # Remove old entry
    lines = [l for l in existing.splitlines() if _CRON_MARKER not in l]
    lines.append(cron_line)

    new_crontab = "\n".join(lines) + "\n"
    proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True, capture_output=True)
    if proc.returncode != 0:
        console.print(f"[red]crontab install failed:[/red] {proc.stderr}")
        raise typer.Exit(1)

    console.print(
        f"[green]✓ Installed crontab schedule:[/green] "
        f"every {day.capitalize()} at {hour:02d}:{minute:02d}"
    )


@schedule_app.command("uninstall")
def schedule_uninstall() -> None:
    """Remove the tradingagents weekly-run schedule."""
    if platform.system() == "Darwin":
        if _LAUNCHD_PLIST.exists():
            subprocess.run(["launchctl", "unload", str(_LAUNCHD_PLIST)], capture_output=True)
            _LAUNCHD_PLIST.unlink()
            console.print("[yellow]Removed launchd schedule.[/yellow]")
        else:
            console.print("[dim]No launchd schedule found.[/dim]")
    else:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if result.returncode != 0:
            console.print("[dim]No crontab found.[/dim]")
            return
        lines = [l for l in result.stdout.splitlines() if _CRON_MARKER not in l]
        subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True)
        console.print("[yellow]Removed crontab schedule.[/yellow]")


@schedule_app.command("status")
def schedule_status() -> None:
    """Show whether the weekly-run schedule is currently installed."""
    if platform.system() == "Darwin":
        if _LAUNCHD_PLIST.exists():
            console.print(f"[green]Installed[/green] (launchd) → {_LAUNCHD_PLIST}")
            result = subprocess.run(
                ["launchctl", "list", _LAUNCHD_LABEL],
                capture_output=True,
                text=True,
            )
            if result.stdout.strip():
                console.print(f"[dim]{result.stdout.strip()}[/dim]")
        else:
            console.print("[yellow]Not installed[/yellow]")
    else:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if result.returncode == 0 and _CRON_MARKER in result.stdout:
            for line in result.stdout.splitlines():
                if _CRON_MARKER in line:
                    console.print(f"[green]Installed[/green] (crontab)\n[dim]{line}[/dim]")
                    return
        console.print("[yellow]Not installed[/yellow]")
