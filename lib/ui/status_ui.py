"""Task status display and log re-attachment."""

import glob
import os

from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from ..infra.daemon import get_task_status
from ..infra.logger import LOG_DIR
from .progress import follow_log, show_last_summary


def do_status(console: Console) -> None:
    console.print("\n[bold]=== 任务状态 ===[/]\n")

    status = get_task_status()
    if status:
        table = Table(title="运行中的任务", border_style="green", show_header=False, padding=(0, 2))
        table.add_column("项目", style="bold")
        table.add_column("内容")
        table.add_row("类型", status.get("type", "N/A"))
        table.add_row("PID", str(status.get("pid", "N/A")))
        table.add_row("源", status.get("src", "N/A"))
        table.add_row("目标", status.get("dst", "N/A"))
        table.add_row("日志", status.get("log", "N/A"))
        console.print(table)

        if Confirm.ask("\n跟踪进度?", default=True):
            follow_log(status["log"], task_type=status.get("type", "任务"), console=console)
    else:
        console.print("[dim]当前没有运行中的任务[/]")
        _show_latest_log(console)


def _show_latest_log(console: Console) -> None:
    """Find and display the most recent log file summary."""
    log_dir = str(LOG_DIR)
    if not os.path.isdir(log_dir):
        return

    logs = sorted(glob.glob(os.path.join(log_dir, "*.log")), reverse=True)
    if not logs:
        console.print("[dim]无历史日志[/]")
        return

    latest = logs[0]
    console.print(f"\n[dim]最近日志: {os.path.basename(latest)}[/]")
    show_last_summary(latest, console)
