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
from typing import Optional

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
    update_position,
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
    """Show all tickers in the watchlist with position info."""
    data = load_watchlist(_watchlist_path())
    tickers = data.get("tickers", [])
    analysts = data.get("analysts", [])
    positions = data.get("positions", {})

    if not tickers:
        console.print("[yellow]Watchlist is empty.[/yellow]  Add tickers with [bold]watchlist add TICKER[/bold].")
        return

    table = Table(title="Watchlist", box=box.SIMPLE_HEAD, show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Ticker", style="cyan bold")
    table.add_column("Cost/Share", justify="right")
    table.add_column("Qty", justify="right")
    table.add_column("Total Cost", justify="right")

    for i, ticker in enumerate(tickers, 1):
        pos = positions.get(ticker.upper())
        if pos and pos.get("cost") and pos.get("qty"):
            cost = float(pos["cost"])
            qty = float(pos["qty"])
            total = cost * qty
            cost_str = f"${cost:,.2f}"
            qty_str = f"{qty:,.0f}"
            total_str = f"${total:,.2f}"
        else:
            cost_str = qty_str = total_str = "[dim]NA[/dim]"
        table.add_row(str(i), ticker, cost_str, qty_str, total_str)

    console.print(table)
    console.print(f"[dim]Analysts: {', '.join(analysts)}[/dim]")
    console.print(f"[dim]Path: {Path(_watchlist_path()).expanduser()}[/dim]")


@app.command("add")
def add_cmd(
    tickers: list[str] = typer.Argument(..., help="Ticker symbols to add (e.g. NVDA AAPL MSFT)"),
) -> None:
    """Add tickers to the watchlist and optionally record position info."""
    path = _watchlist_path()
    updated = add_tickers(path, tickers)

    added_info: list[str] = []
    for ticker in tickers:
        ticker = ticker.upper()
        console.print(f"\n[bold]{ticker}[/bold] — do you currently hold this stock?")
        holds = typer.confirm("  Holding?", default=False)
        if holds:
            cost = typer.prompt("  Average cost per share ($)", prompt_suffix=": ")
            qty = typer.prompt("  Number of shares", prompt_suffix=": ")
            try:
                update_position(path, ticker, float(cost), float(qty))
                added_info.append(f"{ticker} ({qty} shares @ ${float(cost):.2f})")
            except ValueError:
                console.print("[yellow]  Invalid input — position saved as NA.[/yellow]")
                added_info.append(f"{ticker} (NA)")
        else:
            update_position(path, ticker, None, None)
            added_info.append(f"{ticker} (NA)")

    console.print(f"\n[green]✓ Added:[/green] {', '.join(added_info)}")
    console.print(f"[dim]Watchlist now has {len(updated)} tickers.[/dim]")


@app.command("remove")
def remove_cmd(
    tickers: list[str] = typer.Argument(..., help="Ticker symbols to remove"),
) -> None:
    """Remove tickers from the watchlist."""
    updated = remove_tickers(_watchlist_path(), tickers)
    removed = [t.upper() for t in tickers]
    console.print(f"[yellow]Removed:[/yellow] {', '.join(removed)}")
    console.print(f"[dim]Watchlist now has {len(updated)} tickers.[/dim]")


@app.command("position")
def position_cmd(
    ticker: str = typer.Argument(..., help="Ticker symbol, e.g. NVDA"),
    cost: Optional[float] = typer.Option(None, "--cost", help="Average cost per share"),
    qty: Optional[float] = typer.Option(None, "--qty", help="Number of shares held"),
    clear: bool = typer.Option(False, "--clear", help="Clear position (set to NA)"),
) -> None:
    """Update or clear the position for a watchlist ticker.

    Without flags, launches an interactive prompt.

    Examples:

      tradingagents watchlist position NVDA --cost 125.50 --qty 100

      tradingagents watchlist position NVDA --clear
    """
    path = _watchlist_path()
    ticker = ticker.upper()

    # Verify ticker is in watchlist
    data = load_watchlist(path)
    if ticker not in [t.upper() for t in data["tickers"]]:
        console.print(f"[red]{ticker} is not in your watchlist.[/red] Add it first with [bold]watchlist add {ticker}[/bold].")
        raise typer.Exit(1)

    if clear:
        update_position(path, ticker, None, None)
        console.print(f"[yellow]✓ {ticker} position cleared (NA).[/yellow]")
        return

    if cost is not None and qty is not None:
        update_position(path, ticker, cost, qty)
        total = cost * qty
        console.print(f"[green]✓ {ticker}:[/green] {qty:,.0f} 股 @ ${cost:,.2f}（总成本 ${total:,.2f}）")
        return

    # Interactive mode
    current = data.get("positions", {}).get(ticker)
    if current and current.get("cost") and current.get("qty"):
        console.print(f"[dim]当前持仓：{current['qty']:,.0f} 股 @ ${current['cost']:,.2f}[/dim]")
    else:
        console.print(f"[dim]当前持仓：NA[/dim]")

    holds = typer.confirm(f"是否持有 {ticker}？", default=bool(current))
    if not holds:
        update_position(path, ticker, None, None)
        console.print(f"[yellow]✓ {ticker} position cleared (NA).[/yellow]")
        return

    while True:
        try:
            new_cost = float(typer.prompt("  平均成本价 ($)"))
            new_qty = float(typer.prompt("  持有数量（股）"))
            break
        except ValueError:
            console.print("[red]请输入数字。[/red]")

    update_position(path, ticker, new_cost, new_qty)
    total = new_cost * new_qty
    console.print(f"[green]✓ {ticker}:[/green] {new_qty:,.0f} 股 @ ${new_cost:,.2f}（总成本 ${total:,.2f}）")


@app.command("edit")
def edit_cmd() -> None:
    """Open the watchlist YAML file in your default editor ($EDITOR)."""
    path = Path(_watchlist_path()).expanduser()

    if not path.exists():
        save_watchlist(str(path), {"tickers": [], "analysts": ["market", "social", "news", "fundamentals"], "positions": {}})
        console.print(f"[dim]Created empty watchlist at {path}[/dim]")

    editor = os.environ.get("EDITOR", "")
    if not editor:
        if sys.platform == "darwin":
            editor = "open -t"
        elif sys.platform.startswith("win"):
            editor = "notepad"
        else:
            editor = "nano"

    console.print(f"[dim]Opening {path} with: {editor}[/dim]")
    subprocess.run(f"{editor} {path}", shell=True)
