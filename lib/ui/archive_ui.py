"""Archive interaction flow: SSD directory -> HDD .sqsh."""

import os

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

from ..core.archiver import run_archive
from ..infra.daemon import daemonize
from ..infra.disk import (
    format_size, get_dir_stats, get_free_space,
    is_on_hdd, validate_hdd_dest, validate_source_dir,
)
from ..infra.logger import setup_logger
from .progress import follow_log


def do_archive(console: Console) -> None:
    console.print("\n[bold]=== 项目归档 (SSD -> HDD) ===[/]\n")

    src = Prompt.ask("源路径 (SSD)").strip()
    try:
        src_path = validate_source_dir(src)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        return

    hdd_dir = Prompt.ask("目标目录 (HDD)", default="/mnt/hdd").strip()
    try:
        hdd_path = validate_hdd_dest(hdd_dir)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        return

    archive_name = src_path.name + ".sqsh"
    archive_path = str(hdd_path / archive_name)

    if os.path.exists(archive_path):
        console.print(f"[yellow]归档文件已存在: {archive_path}[/]")
        if not Confirm.ask("覆盖?", default=False):
            return

    console.print("[dim]正在统计源目录...[/]")
    total_bytes, file_count = get_dir_stats(str(src_path))
    free = get_free_space(str(hdd_path))
    estimated = int(total_bytes * 0.6)

    if estimated > free:
        console.print(
            f"[red]HDD 空间不足: 预估需要 {format_size(estimated)}, "
            f"可用 {format_size(free)}[/]"
        )
        return

    table = Table(title="任务摘要", border_style="cyan", show_header=False, padding=(0, 2))
    table.add_column("项目", style="bold")
    table.add_column("内容")
    table.add_row("源", str(src_path))
    table.add_row("大小", f"{format_size(total_bytes)} ({file_count:,} 文件)")
    table.add_row("目标", archive_path)
    table.add_row("算法", "squashfs + zstd-1, 256K block")
    table.add_row("HDD 余量", format_size(free))
    console.print(table)

    if not Confirm.ask("\n确认归档?", default=True):
        return

    logger, log_path = setup_logger("archive")

    def _daemon_task(source_dir, archive_path, total_bytes, log_path):
        import logging
        lgr = logging.getLogger("transfer.daemon.archive")
        lgr.handlers.clear()
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
        lgr.addHandler(fh)
        lgr.setLevel(logging.DEBUG)
        run_archive(source_dir, archive_path, total_bytes, lgr)

    pid = daemonize(
        task_func=_daemon_task,
        task_kwargs=dict(
            source_dir=str(src_path),
            archive_path=archive_path,
            total_bytes=total_bytes,
            log_path=str(log_path),
        ),
        task_type="归档",
        src=str(src_path),
        dst=archive_path,
        log_path=str(log_path),
    )
    if pid is None:
        follow_log(str(log_path), task_type="归档", console=console)
        return
    console.print(f"\n[green]后台任务已启动 PID {pid}[/]")
    follow_log(str(log_path), task_type="归档", console=console)
