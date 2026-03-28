"""Disk utilities: path validation, space checks, size stats, dependency checks."""

import os
import shutil
import subprocess
from pathlib import Path

HDD_MOUNT = "/mnt/hdd"
SSD_MOUNTS = ("/mnt/data", "/mnt/disk1", "/mnt/disk2")
REQUIRED_TOOLS = ("mksquashfs", "unsquashfs", "sqfscat", "xxh128sum")


def check_dependencies() -> list[str]:
    """Return list of missing required system tools."""
    return [t for t in REQUIRED_TOOLS if shutil.which(t) is None]


def resolve_mount(path: str) -> str:
    """Return the mount point a path resides on."""
    path = os.path.realpath(path)
    while not os.path.ismount(path):
        path = os.path.dirname(path)
    return path


def is_on_hdd(path: str) -> bool:
    return os.path.realpath(path).startswith(os.path.realpath(HDD_MOUNT))


def is_on_ssd(path: str) -> bool:
    rp = os.path.realpath(path)
    return any(rp.startswith(os.path.realpath(m)) for m in SSD_MOUNTS)


def get_free_space(path: str) -> int:
    """Return free bytes on the filesystem containing *path*."""
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def get_dir_stats(path: str) -> tuple[int, int]:
    """Return (total_bytes, file_count) for a directory using du+find."""
    try:
        du = subprocess.run(
            ["du", "-sb", path], capture_output=True, text=True, timeout=300
        )
        total = int(du.stdout.split()[0]) if du.returncode == 0 else 0
    except Exception:
        total = 0
    try:
        fc = subprocess.run(
            ["find", path, "-type", "f"],
            capture_output=True, text=True, timeout=300,
        )
        count = fc.stdout.count("\n") if fc.returncode == 0 else 0
    except Exception:
        count = 0
    return total, count


def format_size(nbytes: int) -> str:
    """Human-readable size string."""
    if nbytes < 0:
        return "N/A"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}" if unit != "B" else f"{nbytes} B"
        nbytes /= 1024
    return f"{nbytes:.1f} PB"


def validate_source_dir(path: str) -> Path:
    """Validate that *path* is an existing directory. Raise ValueError otherwise."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ValueError(f"路径不存在: {p}")
    if not p.is_dir():
        raise ValueError(f"不是目录: {p}")
    return p


def validate_archive(path: str) -> Path:
    """Validate that *path* is an existing .sqsh file."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ValueError(f"文件不存在: {p}")
    if not p.is_file():
        raise ValueError(f"不是文件: {p}")
    if p.suffix != ".sqsh":
        raise ValueError(f"不是 .sqsh 归档文件: {p}")
    return p


def validate_hdd_dest(path: str) -> Path:
    """Validate HDD destination directory exists."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ValueError(f"HDD 目标路径不存在: {p}")
    if not is_on_hdd(str(p)):
        raise ValueError(f"目标路径不在 HDD ({HDD_MOUNT}) 上: {p}")
    return p


def validate_ssd_dest(path: str) -> Path:
    """Validate (or create) SSD destination directory. Warns if not on SSD."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        p.mkdir(parents=True, exist_ok=True)
    if not p.is_dir():
        raise ValueError(f"目标不是目录: {p}")
    if is_on_hdd(str(p)):
        raise ValueError(f"目标路径在 HDD 上，请指定 SSD 路径: {p}")
    return p
