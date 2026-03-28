"""Extraction interaction flows: full restore, path-based, search-based."""

import os

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

from ..core.browser import (
    FileEntry, load_archive_tree, list_directory,
    search as browser_search, get_dir_summary,
)
from ..core.extractor import run_extract
from ..core.restorer import run_restore
from ..infra.daemon import daemonize
from ..infra.disk import format_size, get_free_space, validate_archive, validate_ssd_dest
from ..infra.logger import setup_logger
from .menu import extract_submenu
from .progress import follow_log


def do_extract(console: Console) -> None:
    while True:
        choice = extract_submenu(console)
        if choice == "1":
            do_full_restore(console)
        elif choice == "2":
            do_path_extract(console)
        elif choice == "3":
            do_search_extract(console)
        elif choice == "4":
            return


# ── Full Restore ──────────────────────────────────────────────────

def do_full_restore(console: Console) -> None:
    console.print("\n[bold]=== 全量提取 ===[/]\n")

    archive = Prompt.ask("归档路径 (HDD)").strip()
    try:
        archive_path = validate_archive(archive)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        return

    target = Prompt.ask("目标路径 (SSD)").strip()
    try:
        target_path = validate_ssd_dest(target)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        return

    archive_size = os.path.getsize(str(archive_path))
    free = get_free_space(str(target_path))
    estimated_uncompressed = int(archive_size * 2.0)

    if estimated_uncompressed > free:
        console.print(
            f"[red]SSD 空间不足: 预估需要 {format_size(estimated_uncompressed)}, "
            f"可用 {format_size(free)}[/]"
        )
        return

    table = Table(title="任务摘要", border_style="green", show_header=False, padding=(0, 2))
    table.add_column("项目", style="bold")
    table.add_column("内容")
    table.add_row("归档", str(archive_path))
    table.add_row("归档大小", format_size(archive_size))
    table.add_row("目标", str(target_path))
    table.add_row("SSD 余量", format_size(free))
    console.print(table)

    if not Confirm.ask("\n确认全量提取?", default=True):
        return

    _launch_extract_daemon(
        console, str(archive_path), str(target_path), [], "全量恢复",
        use_restore=True,
    )


# ── Path-based Extract (directory browser) ────────────────────────

def do_path_extract(console: Console) -> None:
    console.print("\n[bold]=== 指定路径提取 ===[/]\n")

    archive = Prompt.ask("归档路径 (HDD)").strip()
    try:
        archive_path = validate_archive(archive)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        return

    console.print("[dim]加载目录...[/]")
    try:
        entries = load_archive_tree(str(archive_path))
    except Exception as e:
        console.print(f"[red]加载失败: {e}[/]")
        return

    selected: list[str] = []
    current_dir = ""

    while True:
        children = list_directory(entries, current_dir)
        _display_directory(console, current_dir, children, entries)

        console.print(
            "\n[dim]操作: 序号=展开  e 序号=选中  r 序号=取消选中  ..=上级  list=已选  done=执行  q=返回[/]"
        )
        cmd = Prompt.ask(">").strip()

        if cmd.lower() == "q":
            return
        elif cmd == "..":
            if current_dir:
                current_dir = os.path.dirname(current_dir.rstrip("/"))
        elif cmd.lower() == "list":
            _show_selected(console, selected, entries)
        elif cmd.lower() == "done":
            if not selected:
                console.print("[yellow]未选择任何项[/]")
                continue
            _confirm_and_extract(console, str(archive_path), selected, entries)
            return
        elif cmd.lower().startswith("r "):
            idx_str = cmd[2:].strip()
            try:
                idx = int(idx_str) - 1
                if 0 <= idx < len(selected):
                    removed = selected.pop(idx)
                    console.print(f"  [red][-] 已移除: {removed}[/]")
                else:
                    console.print(f"[yellow]序号超出范围 (1-{len(selected)})[/]")
            except ValueError:
                console.print("[red]无效序号 (用 list 查看清单序号)[/]")
        elif cmd.lower().startswith("e "):
            idx_str = cmd[2:].strip()
            try:
                idx = int(idx_str) - 1
                if 0 <= idx < len(children):
                    path = children[idx].path.strip("/")
                    if path not in selected:
                        selected.append(path)
                        sz, _ = get_dir_summary(entries, path) if children[idx].is_dir else (children[idx].size, 1)
                        console.print(f"  [green][+] 已选: {path} ({format_size(sz)})[/]")
                    else:
                        console.print(f"  [yellow]已在清单中: {path}[/]")
            except ValueError:
                console.print("[red]无效序号[/]")
        else:
            try:
                idx = int(cmd) - 1
                if 0 <= idx < len(children) and children[idx].is_dir:
                    current_dir = children[idx].path.strip("/")
                else:
                    console.print("[yellow]不是目录或序号无效[/]")
            except ValueError:
                console.print("[red]无效输入[/]")


# ── Search-based Extract ──────────────────────────────────────────

def do_search_extract(console: Console) -> None:
    console.print("\n[bold]=== 搜索提取 ===[/]\n")

    archive = Prompt.ask("归档路径 (HDD)").strip()
    try:
        archive_path = validate_archive(archive)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        return

    console.print("[dim]加载目录...[/]")
    try:
        entries = load_archive_tree(str(archive_path))
    except Exception as e:
        console.print(f"[red]加载失败: {e}[/]")
        return

    selected: list[str] = []

    console.print("[dim]搜索模式: 关键词(默认) | *.ext(通配符) | /regex/(正则)[/]")

    while True:
        cmd = Prompt.ask("搜索").strip()

        if cmd.lower() == "q":
            return
        elif cmd.lower() == "list":
            _show_selected(console, selected, entries)
            continue
        elif cmd.lower() == "done":
            if not selected:
                console.print("[yellow]未选择任何项[/]")
                continue
            _confirm_and_extract(console, str(archive_path), selected, entries)
            return

        if cmd.startswith("/") and cmd.endswith("/") and len(cmd) > 2:
            mode, pattern = "regex", cmd[1:-1]
        elif any(c in cmd for c in "*?["):
            mode, pattern = "glob", cmd
        else:
            mode, pattern = "keyword", cmd

        results = browser_search(entries, pattern, mode)

        if not results:
            console.print("[yellow]未找到匹配项[/]")
            continue

        console.print(f"\n  找到 {len(results)} 个匹配:")
        display_results = results[:50]
        for i, e in enumerate(display_results, 1):
            sz = format_size(e.size) if not e.is_dir else "DIR"
            console.print(f"  [{i:>3}]  {e.path:<60s}  {sz}")
        if len(results) > 50:
            console.print(f"  [dim]... 还有 {len(results) - 50} 项未显示[/]")

        console.print("\n[dim]选择: 序号 / 多选如 1,3,5 / all / s 继续搜索 / list / done / q[/]")
        sel = Prompt.ask("选择").strip()

        if sel.lower() == "s" or sel == "":
            continue
        elif sel.lower() == "all":
            added = 0
            for e in results:
                p = e.path.strip("/")
                if p and p not in selected:
                    selected.append(p)
                    added += 1
            console.print(f"  [green][+] 已选全部 {added} 项 (共 {len(results)} 匹配)[/]")
        elif sel.lower() == "list":
            _show_selected(console, selected, entries)
        elif sel.lower() == "done":
            if not selected:
                console.print("[yellow]未选择任何项[/]")
                continue
            _confirm_and_extract(console, str(archive_path), selected, entries)
            return
        elif sel.lower() == "q":
            return
        else:
            for part in sel.split(","):
                part = part.strip()
                try:
                    idx = int(part) - 1
                    if 0 <= idx < len(display_results):
                        p = display_results[idx].path.strip("/")
                        if p not in selected:
                            selected.append(p)
                            console.print(f"  [green][+] 已选: {p}[/]")
                except ValueError:
                    pass


# ── Helpers ───────────────────────────────────────────────────────

def _display_directory(
    console: Console,
    current_dir: str,
    children: list[FileEntry],
    all_entries: list[FileEntry],
) -> None:
    display_path = "/" + current_dir if current_dir else "/"
    total, count = get_dir_summary(all_entries, current_dir)
    console.print(f"\n[bold]{display_path}[/]  ({format_size(total)}, {count:,} 文件)")

    for i, e in enumerate(children, 1):
        kind = "DIR " if e.is_dir else "FILE"
        if e.is_dir:
            sz_total, _ = get_dir_summary(all_entries, e.path.strip("/"))
            sz = format_size(sz_total)
        else:
            sz = format_size(e.size)
        console.print(f"  [{i:>3}]  {kind}  {e.name:<40s}  {sz}")


def _show_selected(console: Console, selected: list[str], entries: list[FileEntry]) -> None:
    if not selected:
        console.print("[dim]提取清单为空[/]")
        return
    total = 0
    console.print(f"\n  提取清单 ({len(selected)} 项):")
    for i, p in enumerate(selected, 1):
        sz, _ = get_dir_summary(entries, p)
        if sz == 0:
            for e in entries:
                if e.path.strip("/") == p and not e.is_dir:
                    sz = e.size
                    break
        total += sz
        console.print(f"    {i}. {p:<50s}  {format_size(sz)}")
    console.print(f"  [bold]合计: {format_size(total)}[/]")


def _confirm_and_extract(
    console: Console,
    archive_path: str,
    selected: list[str],
    entries: list[FileEntry],
) -> None:
    _show_selected(console, selected, entries)
    target = Prompt.ask("\n目标路径 (SSD)").strip()
    try:
        target_path = validate_ssd_dest(target)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        return

    if not Confirm.ask(f"确认提取 {len(selected)} 项?", default=True):
        return

    _launch_extract_daemon(console, archive_path, str(target_path), selected, "选择性提取")


def _launch_extract_daemon(
    console: Console,
    archive_path: str,
    target_dir: str,
    paths: list[str],
    operation: str,
    use_restore: bool = False,
) -> None:
    logger, log_path = setup_logger("extract" if not use_restore else "restore")

    def _daemon_task(archive_path, target_dir, paths, log_path, use_restore):
        from ..infra.logger import make_daemon_logger
        lgr = make_daemon_logger("restore" if use_restore else "extract", log_path)
        if use_restore:
            run_restore(archive_path, target_dir, lgr)
        else:
            run_extract(archive_path, target_dir, paths, lgr)

    pid = daemonize(
        task_func=_daemon_task,
        task_kwargs=dict(
            archive_path=archive_path,
            target_dir=target_dir,
            paths=paths,
            log_path=str(log_path),
            use_restore=use_restore,
        ),
        task_type=operation,
        src=archive_path,
        dst=target_dir,
        log_path=str(log_path),
    )
    if pid is None:
        follow_log(str(log_path), task_type=operation, console=console)
        return
    console.print(f"\n[green]后台任务已启动 PID {pid}[/]")
    follow_log(str(log_path), task_type=operation, console=console)
