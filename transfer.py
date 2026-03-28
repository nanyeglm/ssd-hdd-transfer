#!/usr/bin/env python3
"""SSD <-> HDD 项目归档工具

所有任务以守护进程执行，终端仅作为可随时断开/重连的跟踪窗口。
用法:
    transfer               # 交互主菜单
    transfer status        # 查看/跟踪后台任务
"""

import sys

from rich.console import Console

from lib.infra.disk import check_dependencies
from lib.ui.archive_ui import do_archive
from lib.ui.append_ui import do_append
from lib.ui.extract_ui import do_extract
from lib.ui.menu import main_menu
from lib.ui.status_ui import do_status

console = Console()


def _check_deps() -> None:
    missing = check_dependencies()
    if missing:
        console.print(f"[red]缺少系统工具: {', '.join(missing)}[/]")
        console.print("[dim]请安装后重试[/]")
        sys.exit(1)


def main() -> None:
    _check_deps()

    if len(sys.argv) > 1 and sys.argv[1] == "status":
        do_status(console)
        return

    while True:
        choice = main_menu(console)
        if choice == "1":
            do_archive(console)
        elif choice == "2":
            do_extract(console)
        elif choice == "3":
            do_append(console)
        elif choice == "4":
            do_status(console)
        elif choice == "5":
            console.print("[dim]退出[/]")
            break


if __name__ == "__main__":
    main()
