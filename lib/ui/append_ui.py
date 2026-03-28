"""Append interaction flow: add SSD data to existing HDD archive."""

import os

from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table

from ..core.appender import detect_conflicts, run_append
from ..infra.daemon import daemonize
from ..infra.disk import (
    format_size, get_dir_stats, validate_archive, validate_source_dir,
)
from ..infra.logger import setup_logger
from .progress import follow_log


def do_append(console: Console) -> None:
    console.print("\n[bold]=== 数据追加 (SSD -> 已有归档) ===[/]\n")

    archive = Prompt.ask("归档路径 (HDD)").strip()
    try:
        archive_path = validate_archive(archive)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        return

    src = Prompt.ask("追加源 (SSD)").strip()
    try:
        src_path = validate_source_dir(src)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        return

    console.print("[dim]分析中...[/]")

    src_bytes, src_count = get_dir_stats(str(src_path))
    archive_size = os.path.getsize(str(archive_path))

    try:
        conflicts = detect_conflicts(str(archive_path), str(src_path))
    except Exception as e:
        console.print(f"[red]冲突检测失败: {e}[/]")
        return

    new_items = [
        item for item in sorted(os.listdir(str(src_path)))
        if item not in conflicts
    ]

    table = Table(title="追加预览", border_style="yellow", show_header=False, padding=(0, 2))
    table.add_column("项目", style="bold")
    table.add_column("内容")
    table.add_row("归档现有", f"{format_size(archive_size)}")
    table.add_row("追加数据", f"{format_size(src_bytes)} ({src_count:,} 文件)")

    for item in new_items:
        table.add_row("[green][新增][/]", item)
    for item in conflicts:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        table.add_row("[yellow][冲突][/]", f"{item} -> {item}_{ts}")

    console.print(table)

    if conflicts:
        console.print(
            f"\n[yellow]检测到 {len(conflicts)} 个同名冲突。"
            f"冲突项将自动添加时间戳后缀。[/]"
        )

    if not Confirm.ask("\n确认追加?", default=True):
        return

    logger, log_path = setup_logger("append")

    def _daemon_task(source_dir, archive_path, conflicts, log_path):
        import logging
        lgr = logging.getLogger("transfer.daemon.append")
        lgr.handlers.clear()
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
        lgr.addHandler(fh)
        lgr.setLevel(logging.DEBUG)
        run_append(source_dir, archive_path, conflicts, lgr)

    pid = daemonize(
        task_func=_daemon_task,
        task_kwargs=dict(
            source_dir=str(src_path),
            archive_path=str(archive_path),
            conflicts=conflicts,
            log_path=str(log_path),
        ),
        task_type="追加",
        src=str(src_path),
        dst=str(archive_path),
        log_path=str(log_path),
    )
    if pid is None:
        follow_log(str(log_path), task_type="追加", console=console)
        return
    console.print(f"\n[green]后台任务已启动 PID {pid}[/]")
    follow_log(str(log_path), task_type="追加", console=console)
