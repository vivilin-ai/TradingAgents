"""CLI sub-commands for managing the stock watchlist.

Usage:
  tradingagents watchlist list
  tradingagents watchlist add NVDA AAPL MSFT
  tradingagents watchlist remove TSLA
  tradingagents watchlist edit          # opens $EDITOR
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import box

load_dotenv()
load_dotenv(".env.enterprise", override=False)

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.batch.watchlist import (
    add_tickers,
    load_watchlist,
    remove_tickers,
    save_watchlist,
)

app = typer.Typer(
    name="watchlist",
    help="Manage your stock watchlist.",
    no_args_is_help=True,
)
console = Console()


def _watchlist_path() -> str:
    return DEFAULT_CONFIG["watchlist_path"]


@app.command("list")
def list_watchlist() -> None:
    """Show all tickers in the watchlist."""
    data = load_watchlist(_watchlist_path())
    tickers = data.get("tickers", [])
    analysts = data.get("analysts", [])

    if not tickers:
        console.print("[yellow]Watchlist is empty.[/yellow]  Add tickers with [bold]watchlist add TICKER[/bold].")
        return

    table = Table(title="Watchlist", box=box.SIMPLE_HEAD, show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Ticker", style="cyan bold")
    for i, ticker in enumerate(tickers, 1):
        table.add_row(str(i), ticker)

    console.print(table)
    console.print(f"[dim]Analysts: {', '.join(analysts)}[/dim]")
    console.print(f"[dim]Path: {Path(_watchlist_path()).expanduser()}[/dim]")


@app.command("add")
def add_cmd(
    tickers: list[str] = typer.Argument(..., help="Ticker symbols to add (e.g. NVDA AAPL MSFT)"),
) -> None:
    """Add one or more tickers to the watchlist."""
    updated = add_tickers(_watchlist_path(), tickers)
    added = [t.upper() for t in tickers]
    console.print(f"[green]✓ Added:[/green] {', '.join(added)}")
    console.print(f"[dim]Watchlist now has {len(updated)} tickers.[/dim]")


@app.command("remove")
def remove_cmd(
    tickers: list[str] = typer.Argument(..., help="Ticker symbols to remove"),
) -> None:
    """Remove one or more tickers from the watchlist."""
    updated = remove_tickers(_watchlist_path(), tickers)
    removed = [t.upper() for t in tickers]
    console.print(f"[yellow]Removed:[/yellow] {', '.join(removed)}")
    console.print(f"[dim]Watchlist now has {len(updated)} tickers.[/dim]")


@app.command("edit")
def edit_cmd() -> None:
    """Open the watchlist YAML file in your default editor ($EDITOR)."""
    path = Path(_watchlist_path()).expanduser()

    # Ensure file exists before opening
    if not path.exists():
        save_watchlist(str(path), {"tickers": [], "analysts": ["market", "social", "news", "fundamentals"]})
        console.print(f"[dim]Created empty watchlist at {path}[/dim]")

    editor = os.environ.get("EDITOR", "")
    if not editor:
        # Sensible platform defaults
        if sys.platform == "darwin":
            editor = "open -t"  # TextEdit
        elif sys.platform.startswith("win"):
            editor = "notepad"
        else:
            editor = "nano"

    console.print(f"[dim]Opening {path} with: {editor}[/dim]")
    subprocess.run(f"{editor} {path}", shell=True)
