"""Main menu and sub-menu rendering."""

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt


def main_menu(console: Console) -> str:
    """Display main menu and return user choice."""
    console.print()
    console.print(Panel(
        "[bold]  [1]  项目归档    SSD -> HDD\n"
        "  [2]  文件提取    HDD -> SSD\n"
        "  [3]  数据追加    SSD -> 已有归档\n"
        "  [4]  任务状态\n"
        "  [5]  退出[/]",
        title="[bold cyan]SSD <-> HDD 项目归档工具[/]",
        border_style="cyan",
        padding=(1, 2),
    ))
    return Prompt.ask("选择", choices=["1", "2", "3", "4", "5"], default="5")


def extract_submenu(console: Console) -> str:
    """Display extraction sub-menu."""
    console.print()
    console.print(Panel(
        "[bold]  [1]  全量提取        恢复整个归档到 SSD\n"
        "  [2]  指定路径提取    浏览归档目录, 选择文件/文件夹\n"
        "  [3]  搜索提取        按关键词/通配符/正则搜索\n"
        "  [4]  返回[/]",
        title="[bold green]文件提取 (HDD -> SSD)[/]",
        border_style="green",
        padding=(1, 2),
    ))
    return Prompt.ask("选择", choices=["1", "2", "3", "4"], default="4")
