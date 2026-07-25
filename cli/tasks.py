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
    evaluate: bool = typer.Option(False, "--evaluate", help="周度评估：结算历史建议并生成记分卡"),
    disabled: bool = typer.Option(False, "--disabled", help="添加但暂不启用"),
) -> None:
    """添加定时任务。

    示例：

      # 每周六上午 8 点分析全部自选列表
      tradingagents tasks add weekly_all --watchlist --day 周六 --time 08:00

      # 每周六 07:30 先做周度评估（结算 + 记分卡 + 校准块）
      tradingagents tasks add weekly_eval --evaluate --day 周六 --time 07:30

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
    if evaluate:
        target = "evaluate"
    elif watchlist:
        target = "watchlist"
    elif tickers:
        target = tickers
    elif ticker:
        target = ticker
    else:
        console.print("[red]请指定 --ticker、--tickers、--watchlist 或 --evaluate。[/red]")
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


@app.command("doctor")
def doctor_cmd(
    lines: int = typer.Option(20, "--lines", "-n", help="每个日志文件显示的末尾行数"),
) -> None:
    """诊断定时任务为什么没跑或跑失败。

    检查任务定义、系统调度安装状态、plist/crontab 里记录的解释器与工作目录
    是否仍然有效、运行日志的最后报错，以及运行时必需的环境变量。
    """
    import os
    import platform
    import plistlib
    import subprocess
    from pathlib import Path

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.scheduler.installer import (
        _LABEL_PREFIX, _LOG_DIR, _plist_path, _read_crontab,
    )

    problems: list[str] = []
    is_mac = platform.system() == "Darwin"

    # ── 1. 任务定义 ───────────────────────────────────────────────────────────
    console.print("\n[bold]1. 任务定义[/bold]")
    tasks = load_tasks()
    if not tasks:
        console.print("  [red]✗ 没有任何任务[/red]")
        problems.append("没有配置任务，用 tasks add 添加")
    for t in tasks:
        console.print(
            f"  • {t.name}: {_describe_schedule(t.schedule)} | 对象 {t.target} | "
            + ("启用" if t.enabled else "[yellow]已停用[/yellow]")
        )
        if not t.enabled:
            problems.append(f"任务 '{t.name}' 处于停用状态，不会被安装")

    # 同一时刻 + 同一对象的重复任务会并发跑，翻倍消耗 API 配额并触发限速
    seen: dict[tuple[str, str], str] = {}
    for t in tasks:
        key = (t.schedule, t.target.lower())
        if key in seen:
            msg = f"任务 '{t.name}' 与 '{seen[key]}' 时间和对象完全相同，会同时跑两遍（易触发 API 限速）"
            console.print(f"  [yellow]⚠ {msg}[/yellow]")
            problems.append(msg)
        else:
            seen[key] = t.name

    # ── 2. 系统调度安装状态 ───────────────────────────────────────────────────
    console.print("\n[bold]2. 系统调度安装状态[/bold]")
    status = task_status()
    for t in tasks:
        if status.get(t.name):
            console.print(f"  [green]✓[/green] {t.name} 已安装")
        else:
            console.print(f"  [red]✗[/red] {t.name} 未安装")
            problems.append(f"任务 '{t.name}' 未写入系统调度，运行 tasks install")

    if is_mac:
        for t in tasks:
            plist = _plist_path(t.name)
            if not plist.exists():
                continue
            # plist 里的解释器路径与工作目录是安装时写死的绝对路径；
            # 重建 venv、改名或移动项目目录后任务会静默失败。
            try:
                data = plistlib.loads(plist.read_bytes())
            except Exception as exc:
                console.print(f"  [red]✗ {t.name} 的 plist 无法解析：{exc}[/red]")
                problems.append(f"'{t.name}' 的 plist 损坏，重新运行 tasks install")
                continue
            args = data.get("ProgramArguments", [])
            workdir = data.get("WorkingDirectory", "")
            if args and not Path(args[0]).exists():
                console.print(f"  [red]✗ {t.name}: 解释器不存在 {args[0]}[/red]")
                problems.append(
                    f"'{t.name}' 指向的 Python 已不存在（venv 被重建或移动过），"
                    "重新运行 tasks install"
                )
            if workdir and not (Path(workdir) / "cli" / "main.py").exists():
                console.print(f"  [red]✗ {t.name}: 工作目录已失效 {workdir}[/red]")
                problems.append(
                    f"'{t.name}' 的工作目录 {workdir} 已不是项目根目录，"
                    "在正确目录下重新运行 tasks install"
                )
            # launchctl 记录的上次退出码：非 0 表示任务跑了但失败了
            out = subprocess.run(
                ["launchctl", "list", f"{_LABEL_PREFIX}{t.name}"],
                capture_output=True, text=True,
            )
            if out.returncode == 0:
                for line in out.stdout.splitlines():
                    if "LastExitStatus" in line:
                        code = line.split("=")[-1].strip().rstrip(";")
                        if code not in ("0", ""):
                            console.print(f"  [red]✗ {t.name}: 上次退出码 {code}[/red]")
                            problems.append(f"'{t.name}' 上次运行以退出码 {code} 失败，见下方日志")
                        else:
                            console.print(f"  [dim]{t.name}: 上次退出码 0[/dim]")
            else:
                console.print(f"  [yellow]⚠ {t.name} 未被 launchd 加载[/yellow]")
                problems.append(f"'{t.name}' 未加载到 launchd，运行 tasks install")
    else:
        crontab = _read_crontab()
        if not crontab.strip():
            console.print("  [yellow]⚠ 当前用户 crontab 为空[/yellow]")

    # ── 3. 运行日志 ───────────────────────────────────────────────────────────
    console.print(f"\n[bold]3. 运行日志[/bold] [dim]({_LOG_DIR})[/dim]")
    import datetime as _dt

    any_log = False
    for t in tasks:
        for suffix in ("", "_error"):
            log = _LOG_DIR / f"{t.name}{suffix}.log"
            if not log.exists() or log.stat().st_size == 0:
                continue
            any_log = True
            mtime = _dt.datetime.fromtimestamp(log.stat().st_mtime)
            console.print(f"\n  [cyan]{log.name}[/cyan] [dim](最后写入 {mtime:%Y-%m-%d %H:%M})[/dim]")
            tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
            for line in tail:
                console.print(f"    {line}", markup=False, highlight=False)
    if not any_log:
        console.print("  [yellow]⚠ 没有任何日志内容 —— 任务可能从未真正启动过[/yellow]")
        problems.append(
            "日志为空说明任务没被触发：Mac 在计划时间处于关机/睡眠状态时 launchd 不会补跑，"
            "可先用 tasks run 手动验证"
        )

    # ── 4. 运行环境 ───────────────────────────────────────────────────────────
    console.print("\n[bold]4. 运行环境[/bold]")
    provider = DEFAULT_CONFIG.get("llm_provider", "openai")
    key_env = {
        "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY", "xai": "XAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY", "qwen": "DASHSCOPE_API_KEY",
        "glm": "ZHIPU_API_KEY", "openrouter": "OPENROUTER_API_KEY",
        "bailian": "DASHSCOPE_API_KEY", "azure": "AZURE_OPENAI_API_KEY",
    }.get(provider.lower())
    console.print(f"  LLM provider: {provider}")
    if key_env:
        if os.getenv(key_env):
            console.print(f"  [green]✓[/green] {key_env} 已设置")
        else:
            console.print(f"  [red]✗[/red] {key_env} 未设置")
            problems.append(f"{key_env} 未设置 —— 定时任务无法调用模型，请写入项目根目录的 .env")
    env_file = Path.cwd() / ".env"
    if env_file.exists():
        console.print(f"  [green]✓[/green] .env 存在（{env_file}）")
    else:
        console.print(f"  [yellow]⚠[/yellow] 当前目录没有 .env")
        problems.append(
            "定时任务不继承终端环境变量，只读项目根目录的 .env；请确认密钥写在 .env 里"
        )
    if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        console.print("  [green]✓[/green] Telegram 通知已配置")
    else:
        console.print("  [yellow]⚠[/yellow] Telegram 未配置，任务结果不会推送")

    # ── 结论 ─────────────────────────────────────────────────────────────────
    console.print("\n[bold]诊断结论[/bold]")
    if problems:
        for p in problems:
            console.print(f"  • {p}", style="red", markup=False, highlight=False)
        console.print(
            "\n[dim]手动跑一次看完整报错：[/dim]tradingagents tasks run <任务名>"
        )
    else:
        console.print("  [green]✓ 未发现问题[/green]")


@app.command("run")
def run_cmd(
    name: str = typer.Argument(..., help="任务名称"),
    date: Optional[str] = typer.Option(None, "--date", help="指定日期 YYYY-MM-DD"),
) -> None:
    """立即手动执行一个定时任务（不等调度），用于验证任务能否跑通。"""
    from cli.main import scheduled_run

    console.print(f"[cyan]手动执行任务：{name}[/cyan]\n")
    scheduled_run(task_name=name, date=date)


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
