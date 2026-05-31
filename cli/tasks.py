"""CLI commands for managing scheduled analysis tasks."""

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

app = typer.Typer(name="tasks", help="管理定时分析任务。", no_args_is_help=True)
console = Console()

# 星期中文/英文 → cron 数字（0=周日，6=周六）
_DAY_MAP = {
    "monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4,
    "friday": 5, "saturday": 6, "sunday": 0,
    "周一": 1, "周二": 2, "周三": 3, "周四": 4,
    "周五": 5, "周六": 6, "周日": 0, "周天": 0,
    "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 0,
}

_DAY_LABEL = {
    0: "周日", 1: "周一", 2: "周二", 3: "周三",
    4: "周四", 5: "周五", 6: "周六",
}


def _build_cron(day: str, time: str) -> str:
    """Convert day name + HH:MM into a cron expression."""
    day_lower = day.strip().lower()
    if day_lower not in _DAY_MAP:
        raise typer.BadParameter(
            f"无法识别的星期：'{day}'。支持：周一~周日 / monday~sunday / mon~sun"
        )
    dow = _DAY_MAP[day_lower]
    try:
        h, m = (int(x) for x in time.strip().split(":"))
    except ValueError:
        raise typer.BadParameter(f"时间格式错误：'{time}'，请用 HH:MM，如 08:00")
    return f"{m} {h} * * {dow}"


def _describe_schedule(schedule: str) -> str:
    """Human-readable description of a cron expression."""
    parts = schedule.strip().split()
    if len(parts) < 5:
        return schedule
    m, h, _, _, dow = parts[0], parts[1], parts[2], parts[3], parts[4]
    try:
        time_str = f"{int(h):02d}:{int(m):02d}"
    except ValueError:
        return schedule
    if dow == "*":
        return f"每天 {time_str}"
    if "-" in dow:
        s, e = dow.split("-")
        day_range = f"{_DAY_LABEL.get(int(s), s)}~{_DAY_LABEL.get(int(e), e)}"
        return f"每{day_range} {time_str}"
    try:
        return f"每{_DAY_LABEL.get(int(dow), dow)} {time_str}"
    except ValueError:
        return schedule


@app.command("list")
def list_tasks() -> None:
    """列出所有定时任务。"""
    tasks = load_tasks()
    if not tasks:
        console.print("[yellow]暂无定时任务。[/yellow]")
        console.print("添加：[bold]tradingagents tasks add <名称> --watchlist --day 周六 --time 08:00[/bold]")
        return

    status = task_status()
    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold magenta")
    table.add_column("名称", style="cyan bold")
    table.add_column("频率", style="green")
    table.add_column("分析对象", style="yellow")
    table.add_column("已启用")
    table.add_column("已安装")

    for task in tasks:
        installed = "[green]✓[/green]" if status.get(task.name) else "[dim]—[/dim]"
        enabled = "[green]是[/green]" if task.enabled else "[dim]否[/dim]"
        table.add_row(
            task.name,
            _describe_schedule(task.schedule),
            task.target,
            enabled,
            installed,
        )

    console.print(table)


@app.command("add")
def add_cmd(
    name: str = typer.Argument(..., help="任务名称（英文，用作报告子目录）"),
    day: Optional[str] = typer.Option(None, "--day", help="星期几，如：周六 / saturday / sat"),
    time: Optional[str] = typer.Option(None, "--time", help="时间，如：08:00"),
    schedule: Optional[str] = typer.Option(None, "--schedule", help="直接用 cron 表达式（高级），如 \"0 8 * * 6\""),
    ticker: Optional[str] = typer.Option(None, "--ticker", help="单只股票，如 NVDA"),
    tickers: Optional[str] = typer.Option(None, "--tickers", help="多只股票，逗号分隔，如 NVDA,AAPL"),
    watchlist: bool = typer.Option(False, "--watchlist", help="分析整个自选列表"),
    disabled: bool = typer.Option(False, "--disabled", help="添加但暂不启用"),
) -> None:
    """添加定时任务。

    示例：

      # 每周六上午 8 点分析全部自选列表
      tradingagents tasks add weekly_all --watchlist --day 周六 --time 08:00

      # 每个工作日早 7 点分析 NVDA
      tradingagents tasks add daily_nvda --ticker NVDA --day 周一 --time 07:00

      # 直接用 cron 表达式（工作日每天 7:30）
      tradingagents tasks add workday_nvda --ticker NVDA --schedule "30 7 * * 1-5"
    """
    # 确定 cron 表达式
    if schedule:
        cron = schedule
    elif day and time:
        cron = _build_cron(day, time)
    else:
        console.print("[red]请指定 --day 和 --time，或直接用 --schedule cron 表达式。[/red]")
        raise typer.Exit(1)

    # 确定分析对象
    if watchlist:
        target = "watchlist"
    elif tickers:
        target = tickers
    elif ticker:
        target = ticker
    else:
        console.print("[red]请指定 --ticker、--tickers 或 --watchlist。[/red]")
        raise typer.Exit(1)

    task = ScheduledTask(name=name, schedule=cron, target=target, enabled=not disabled)
    add_task(task)

    console.print(f"[green]✓ 任务 '{name}' 已添加[/green]")
    console.print(f"  频率：{_describe_schedule(cron)}（cron: {cron}）")
    console.print(f"  对象：{target}")
    console.print(f"\n[dim]运行以下命令将任务写入系统调度：[/dim]")
    console.print(f"  [bold]tradingagents tasks install[/bold]")


@app.command("remove")
def remove_cmd(
    name: str = typer.Argument(..., help="要删除的任务名称"),
) -> None:
    """删除定时任务。"""
    try:
        remove_task(name)
        console.print(f"[yellow]已删除任务 '{name}'。[/yellow]")
        console.print("[dim]如已安装，请重新运行 tasks uninstall + tasks install 同步。[/dim]")
    except KeyError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


@app.command("install")
def install_cmd() -> None:
    """将所有已启用的任务写入 launchd（macOS）或 crontab（Linux）。"""
    installed = install_all()
    if not installed:
        console.print("[yellow]没有已启用的任务需要安装。[/yellow]")
        return
    for name in installed:
        console.print(f"[green]✓[/green] {name}")
    console.print(f"\n[green]{len(installed)} 个任务已安装。[/green]")
    console.print("[dim]Mac 重启后任务会自动执行，无需手动启动。[/dim]")


@app.command("uninstall")
def uninstall_cmd() -> None:
    """从 launchd / crontab 中移除所有定时任务。"""
    removed = uninstall_all()
    if not removed:
        console.print("[yellow]没有已安装的任务。[/yellow]")
        return
    for name in removed:
        console.print(f"[yellow]已移除：[/yellow] {name}")
    console.print(f"\n{len(removed)} 个任务已卸载。")
