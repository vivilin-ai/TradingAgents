"""CLI commands for managing scheduled analysis tasks.

Usage:
  tradingagents tasks list
  tradingagents tasks add daily_nvda --ticker NVDA --schedule "0 8 * * 1-5"
  tradingagents tasks add weekly_all --watchlist --schedule "0 18 * * 1"
  tradingagents tasks remove daily_nvda
  tradingagents tasks install          # write launchd plists / crontab
  tradingagents tasks uninstall        # remove all scheduled tasks
"""

from __future__ import annotations

from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import box

load_dotenv()
load_dotenv(".env.enterprise", override=False)

from tradingagents.scheduler.tasks import ScheduledTask, load_tasks, add_task, remove_task
from tradingagents.scheduler.installer import install_all, uninstall_all, task_status

app = typer.Typer(name="tasks", help="Manage scheduled analysis tasks.", no_args_is_help=True)
console = Console()


@app.command("list")
def list_tasks() -> None:
    """List all configured scheduled tasks."""
    tasks = load_tasks()
    if not tasks:
        console.print("[yellow]No scheduled tasks configured.[/yellow]")
        console.print("Add one with: [bold]tradingagents tasks add <name> --ticker TICKER --schedule \"cron\"[/bold]")
        return

    status = task_status()
    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold magenta")
    table.add_column("Name", style="cyan bold")
    table.add_column("Schedule", style="green")
    table.add_column("Target", style="yellow")
    table.add_column("Enabled")
    table.add_column("Installed")

    for task in tasks:
        installed = "✓" if status.get(task.name) else "—"
        enabled = "[green]yes[/green]" if task.enabled else "[dim]no[/dim]"
        table.add_row(task.name, task.schedule, task.target, enabled, installed)

    console.print(table)


@app.command("add")
def add_cmd(
    name: str = typer.Argument(..., help="Unique task name (used as report sub-directory)"),
    schedule: str = typer.Option(..., "--schedule", help='Cron expression, e.g. "0 8 * * 1-5"'),
    ticker: Optional[str] = typer.Option(None, "--ticker", help="Single ticker, e.g. NVDA"),
    tickers: Optional[str] = typer.Option(None, "--tickers", help="Comma-separated list, e.g. NVDA,AAPL"),
    watchlist: bool = typer.Option(False, "--watchlist", help="Use the full watchlist"),
    disabled: bool = typer.Option(False, "--disabled", help="Create task but don't enable it"),
) -> None:
    """Add a new scheduled task."""
    if watchlist:
        target = "watchlist"
    elif tickers:
        target = tickers
    elif ticker:
        target = ticker
    else:
        console.print("[red]Specify --ticker, --tickers, or --watchlist[/red]")
        raise typer.Exit(1)

    task = ScheduledTask(
        name=name,
        schedule=schedule,
        target=target,
        enabled=not disabled,
    )
    add_task(task)
    console.print(f"[green]✓ Task '{name}' added.[/green]")
    console.print(f"[dim]Target: {target}  Schedule: {schedule}[/dim]")
    console.print("[dim]Run [bold]tradingagents tasks install[/bold] to activate it.[/dim]")


@app.command("remove")
def remove_cmd(
    name: str = typer.Argument(..., help="Task name to remove"),
) -> None:
    """Remove a scheduled task."""
    try:
        remove_task(name)
        console.print(f"[yellow]Removed task '{name}'.[/yellow]")
        console.print("[dim]Run [bold]tradingagents tasks uninstall[/bold] then [bold]install[/bold] to sync.[/dim]")
    except KeyError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


@app.command("install")
def install_cmd() -> None:
    """Install all enabled tasks into launchd (macOS) or crontab (Linux)."""
    installed = install_all()
    if not installed:
        console.print("[yellow]No enabled tasks to install.[/yellow]")
        return
    for name in installed:
        console.print(f"[green]✓[/green] {name}")
    console.print(f"\n[green]{len(installed)} task(s) installed.[/green]")


@app.command("uninstall")
def uninstall_cmd() -> None:
    """Remove all scheduled tasks from launchd / crontab."""
    removed = uninstall_all()
    if not removed:
        console.print("[yellow]Nothing to uninstall.[/yellow]")
        return
    for name in removed:
        console.print(f"[yellow]Removed:[/yellow] {name}")
    console.print(f"\n{len(removed)} task(s) uninstalled.")
