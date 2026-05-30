"""CLI commands for managing the Telegram bot daemon.

Usage:
  tradingagents bot start              # foreground (development)
  tradingagents bot start --daemon     # background, writes PID file
  tradingagents bot stop               # send SIGTERM to daemon
  tradingagents bot status             # check if running
  tradingagents bot install-launchd    # register as macOS launch agent
"""

from __future__ import annotations

import os
import platform
import signal
import subprocess
import sys
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()
load_dotenv(".env.enterprise", override=False)

from tradingagents.default_config import DEFAULT_CONFIG

app = typer.Typer(name="bot", help="Manage the Telegram bot daemon.", no_args_is_help=True)
console = Console()

_HOME = Path.home() / ".tradingagents"
_PID_FILE = _HOME / "bot.pid"
_LOG_FILE = _HOME / "logs" / "bot.log"
_LAUNCHD_LABEL = "com.tradingagents.bot"
_LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"


def _tradingagents_cmd() -> str:
    import shutil
    cmd = shutil.which("tradingagents")
    return cmd if cmd else f"{sys.executable} -m cli.main"


def _pid() -> int | None:
    if not _PID_FILE.exists():
        return None
    try:
        pid = int(_PID_FILE.read_text().strip())
        os.kill(pid, 0)   # check process exists (raises if not)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        _PID_FILE.unlink(missing_ok=True)
        return None


@app.command("start")
def start(
    daemon: bool = typer.Option(False, "--daemon", help="Run in background."),
) -> None:
    """Start the Telegram bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        console.print("[red]TELEGRAM_BOT_TOKEN is not set in .env[/red]")
        raise typer.Exit(1)

    if daemon:
        if _pid():
            console.print("[yellow]Bot is already running.[/yellow]")
            return
        _HOME.mkdir(parents=True, exist_ok=True)
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        cmd = _tradingagents_cmd()
        with open(_LOG_FILE, "a") as log:
            proc = subprocess.Popen(
                [*cmd.split(), "bot", "start"],
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        _PID_FILE.write_text(str(proc.pid))
        console.print(f"[green]✓ Bot started (PID {proc.pid})[/green]")
        console.print(f"[dim]Log: {_LOG_FILE}[/dim]")
    else:
        # Foreground — import and run directly
        _run_bot_foreground()


def _run_bot_foreground() -> None:
    from tradingagents.bot.telegram_bot import TelegramBot
    console.print("[green]Starting bot (Ctrl-C to stop)...[/green]")
    bot = TelegramBot(DEFAULT_CONFIG.copy())
    try:
        bot.start()
    except KeyboardInterrupt:
        bot.stop()
        console.print("\n[yellow]Bot stopped.[/yellow]")


@app.command("stop")
def stop() -> None:
    """Stop the background bot daemon."""
    pid = _pid()
    if not pid:
        console.print("[yellow]Bot is not running.[/yellow]")
        return
    os.kill(pid, signal.SIGTERM)
    _PID_FILE.unlink(missing_ok=True)
    console.print(f"[green]✓ Sent SIGTERM to PID {pid}[/green]")


@app.command("status")
def status() -> None:
    """Show whether the bot daemon is running."""
    pid = _pid()
    if pid:
        console.print(f"[green]Running[/green] (PID {pid})")
    else:
        console.print("[yellow]Not running[/yellow]")


@app.command("install-launchd")
def install_launchd() -> None:
    """Register the bot as a macOS launch agent (auto-starts on login)."""
    if platform.system() != "Darwin":
        console.print("[red]launchd is only available on macOS.[/red]")
        raise typer.Exit(1)

    cmd = _tradingagents_cmd()
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LAUNCHD_PLIST.parent.mkdir(parents=True, exist_ok=True)

    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
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
        <string>cd {Path.cwd()} &amp;&amp; {cmd} bot start</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{_LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>{_LOG_FILE}</string>
</dict>
</plist>
"""
    _LAUNCHD_PLIST.write_text(plist, encoding="utf-8")
    subprocess.run(["launchctl", "unload", str(_LAUNCHD_PLIST)], capture_output=True)
    result = subprocess.run(["launchctl", "load", str(_LAUNCHD_PLIST)], capture_output=True, text=True)

    if result.returncode != 0:
        console.print(f"[red]launchctl load failed:[/red] {result.stderr}")
        raise typer.Exit(1)

    console.print(f"[green]✓ Bot registered as launch agent[/green]")
    console.print(f"[dim]Plist: {_LAUNCHD_PLIST}[/dim]")
    console.print("[dim]The bot will start automatically on login.[/dim]")
