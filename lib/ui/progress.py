"""Log-following progress renderer using rich.

Parses PROGRESS: and SUMMARY blocks from daemon log files,
renders a live progress bar. Ctrl+C detaches without killing the daemon.
Includes watchdog to detect dead daemons (avoids infinite hang).
"""

import os
import re
import time

from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn, SpinnerColumn
from rich.table import Table

from ..infra.daemon import get_task_status, LOCK_FAILED_MARKER

PROGRESS_RE = re.compile(r"PROGRESS:\s*(\d+)%")
SUMMARY_START = "SUMMARY_START"
SUMMARY_END = "SUMMARY_END"
DAEMON_EXIT = "DAEMON_EXIT"

_WATCHDOG_INTERVAL = 6
_WATCHDOG_MAX_STALE = 3


def follow_log(log_path: str, task_type: str = "任务", console: Console | None = None) -> None:
    """Tail the daemon log, rendering a rich progress bar.

    Blocks until the daemon exits (DAEMON_EXIT line), the daemon process
    dies (watchdog), or user presses Ctrl+C.
    """
    if console is None:
        console = Console()

    console.print(f"[dim](Ctrl+C 断开跟踪, 任务不受影响. 用 transfer status 可重新跟踪)[/]")

    summary_lines: list[str] = []
    in_summary = False

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=40),
            TextColumn("{task.percentage:>5.1f}%"),
            TimeRemainingColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task(task_type, total=100)
            pos = 0
            stale_checks = 0
            last_watchdog = time.time()

            while True:
                if not os.path.exists(log_path):
                    time.sleep(0.3)
                    if time.time() - last_watchdog > _WATCHDOG_INTERVAL:
                        if _daemon_is_dead():
                            console.print("\n[red]后台进程已退出，未产生日志。[/]")
                            return
                        last_watchdog = time.time()
                    continue

                with open(log_path, "r", encoding="utf-8") as f:
                    f.seek(pos)
                    new_data = f.read()
                    pos = f.tell()

                if new_data:
                    stale_checks = 0
                    for line in new_data.split("\n"):
                        if DAEMON_EXIT in line:
                            progress.update(task, completed=100)
                            _render_summary(summary_lines, console)
                            return

                        if LOCK_FAILED_MARKER in line:
                            progress.stop()
                            console.print(f"\n[red]任务启动失败: 已有其他任务正在运行[/]")
                            console.print(f"[dim]使用 transfer status 查看运行中的任务[/]")
                            return

                        if SUMMARY_START in line:
                            in_summary = True
                            summary_lines = []
                            continue
                        if SUMMARY_END in line:
                            in_summary = False
                            continue
                        if in_summary:
                            summary_lines.append(line)
                            continue

                        m = PROGRESS_RE.search(line)
                        if m:
                            pct = int(m.group(1))
                            progress.update(task, completed=pct)
                else:
                    now = time.time()
                    if now - last_watchdog > _WATCHDOG_INTERVAL:
                        last_watchdog = now
                        if _daemon_is_dead():
                            stale_checks += 1
                            if stale_checks >= _WATCHDOG_MAX_STALE:
                                progress.stop()
                                console.print("\n[yellow]后台进程已退出。[/]")
                                if summary_lines:
                                    _render_summary(summary_lines, console)
                                else:
                                    _try_show_file_summary(log_path, console)
                                return

                time.sleep(0.5)

    except KeyboardInterrupt:
        console.print(f"\n[yellow]已断开跟踪。后台任务继续运行。[/]")
        console.print(f"[dim]日志: {log_path}[/]")


def show_last_summary(log_path: str, console: Console | None = None) -> None:
    """Read an existing log file and display its SUMMARY block."""
    if console is None:
        console = Console()
    if not os.path.exists(log_path):
        console.print("[dim]日志文件不存在[/]")
        return

    with open(log_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    summary: list[str] = []
    in_summary = False
    for line in lines:
        if SUMMARY_START in line:
            in_summary = True
            summary = []
            continue
        if SUMMARY_END in line:
            in_summary = False
            continue
        if in_summary:
            summary.append(line)

    if summary:
        _render_summary(summary, console)
    else:
        console.print("[dim]日志中未找到任务摘要[/]")


def _daemon_is_dead() -> bool:
    """Check if any daemon is still alive via the lock file."""
    return get_task_status() is None


def _try_show_file_summary(log_path: str, console: Console) -> None:
    """Try to parse summary from the log file after daemon exit."""
    try:
        show_last_summary(log_path, console)
    except Exception:
        console.print(f"[dim]日志: {log_path}[/]")


def _render_summary(lines: list[str], console: Console) -> None:
    if not lines:
        return
    table = Table(title="任务摘要", border_style="green", show_header=False, padding=(0, 2))
    table.add_column("项目", style="bold")
    table.add_column("内容")
    for line in lines:
        line = line.strip()
        ts_stripped = re.sub(r"^\d{2}:\d{2}:\d{2}\s+", "", line)
        if ": " in ts_stripped:
            key, _, val = ts_stripped.partition(": ")
            table.add_row(key.strip(), val.strip())
        elif ":" in ts_stripped:
            key, _, val = ts_stripped.partition(":")
            table.add_row(key.strip(), val.strip())
    if table.row_count > 0:
        console.print()
        console.print(table)
