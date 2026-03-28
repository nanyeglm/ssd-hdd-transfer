"""Append logic: add new data to existing .sqsh archive.

Conflict handling: top-level name conflicts are resolved by renaming the
new entry with a timestamp suffix (cp -al hardlink staging). mksquashfs
native append then runs without any _1 collisions.
"""

import logging
import os
import shutil
import subprocess
import time
from datetime import datetime

from ..infra.checksum import checksum_path_for
from ..infra.disk import format_size
from ..infra.logger import log_progress, log_summary
from .browser import get_top_level_names, invalidate_cache, load_archive_tree


MKSQUASHFS_APPEND_OPTS = [
    "-comp", "zstd",
    "-Xcompression-level", "1",
    "-b", "262144",
    "-processors", str(os.cpu_count() or 4),
    "-percentage",
]


def detect_conflicts(archive_path: str, source_dir: str) -> list[str]:
    """Compare top-level entries; return names that exist in both."""
    entries = load_archive_tree(archive_path)
    archive_names = get_top_level_names(entries)
    source_names = set(os.listdir(source_dir))
    return sorted(archive_names & source_names)


def create_staging(
    source_dir: str,
    conflicts: list[str],
    timestamp: str,
) -> str:
    """Build a staging directory using hardlinks (cp -al).

    Conflicting items get a timestamp suffix.  Returns staging path.
    """
    staging = os.path.join(os.path.dirname(source_dir), f".transfer_staging_{os.getpid()}")
    os.makedirs(staging, exist_ok=True)

    for item in os.listdir(source_dir):
        src = os.path.join(source_dir, item)
        if item in conflicts:
            dst_name = f"{item}_{timestamp}"
        else:
            dst_name = item
        dst = os.path.join(staging, dst_name)

        if os.path.isdir(src):
            result = subprocess.run(["cp", "-al", src, dst], capture_output=True)
            if result.returncode != 0:
                shutil.copytree(src, dst, symlinks=True)
        else:
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)

    return staging


def cleanup_staging(staging_dir: str) -> None:
    if staging_dir and os.path.isdir(staging_dir):
        shutil.rmtree(staging_dir, ignore_errors=True)


def run_append(
    source_dir: str,
    archive_path: str,
    conflicts: list[str],
    logger: logging.Logger,
) -> tuple[bool, float]:
    """Full append pipeline: staging -> mksquashfs append -> checksum.

    Returns (success, elapsed).
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    staging_dir = ""

    logger.info(f"任务启动 | 类型: 数据追加 | PID: {os.getpid()}")
    logger.info(f"追加源: {source_dir}")
    logger.info(f"归档: {archive_path}")
    logger.info(f"冲突项: {conflicts or '无'}")

    start = time.time()

    try:
        if conflicts:
            logger.info(f"创建 staging (冲突项加时间戳 _{timestamp})...")
            staging_dir = create_staging(source_dir, conflicts, timestamp)
            append_src = staging_dir
            for c in conflicts:
                logger.info(f"  {c} -> {c}_{timestamp}")
        else:
            append_src = source_dir

        cmd = ["mksquashfs", append_src, archive_path] + MKSQUASHFS_APPEND_OPTS
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        _monitor_percentage(proc, logger)
        proc.wait()
        rc = proc.returncode

        if rc != 0:
            logger.error(f"mksquashfs 追加失败, 退出码: {rc}")
            elapsed = time.time() - start
            log_summary(logger, status="失败", operation="数据追加", 耗时=f"{elapsed:.1f}s", 退出码=rc)
            return False, elapsed

        invalidate_cache(archive_path)

        _mark_checksum_stale(archive_path, logger)

        elapsed = time.time() - start
        log_summary(
            logger,
            status="成功",
            operation="数据追加",
            追加源=source_dir,
            归档=archive_path,
            冲突处理=f"{len(conflicts)} 项时间戳重命名" if conflicts else "无冲突",
            耗时=f"{elapsed:.1f}s",
        )
        return True, elapsed

    except Exception as e:
        logger.error(f"追加异常: {e}")
        elapsed = time.time() - start
        log_summary(logger, status="失败", operation="数据追加", 耗时=f"{elapsed:.1f}s", 错误=str(e))
        return False, elapsed
    finally:
        if staging_dir:
            cleanup_staging(staging_dir)


def _mark_checksum_stale(archive_path: str, logger: logging.Logger) -> None:
    """Mark existing checksum sidecar as stale (archive was modified by append)."""
    sidecar = checksum_path_for(archive_path)
    try:
        from pathlib import Path
        p = Path(sidecar)
        if p.exists():
            old = p.read_text().strip()
            p.write_text(f"STALE (追加后未重算)\n原始校验: {old}\n")
            logger.info("校验和已标记为失效 (追加修改了归档)")
        else:
            logger.info("无旧校验和文件, 跳过")
    except Exception as e:
        logger.debug(f"标记校验和失效异常: {e}")


def _monitor_percentage(proc: subprocess.Popen, logger: logging.Logger) -> None:
    """Parse mksquashfs -percentage stdout (plain integer lines)."""
    last_pct = -1
    for raw in proc.stdout:
        line = raw.decode(errors="replace").strip()
        if not line:
            continue
        try:
            pct = int(line)
        except ValueError:
            logger.debug(line)
            continue
        if pct != last_pct and 0 <= pct <= 100:
            log_progress(logger, pct)
            last_pct = pct
