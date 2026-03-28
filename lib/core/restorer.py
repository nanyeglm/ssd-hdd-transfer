"""Restore logic: HDD .sqsh -> SSD directory via unsquashfs full extraction."""

import logging
import os
import subprocess
import time

from ..infra.disk import format_size
from ..infra.logger import log_progress, log_summary


def run_restore(
    archive_path: str,
    target_dir: str,
    logger: logging.Logger,
) -> tuple[bool, float]:
    """Execute unsquashfs for full restore. Returns (success, elapsed)."""
    logger.info(f"任务启动 | 类型: 全量恢复 | PID: {os.getpid()}")
    logger.info(f"归档: {archive_path}")
    logger.info(f"目标: {target_dir}")

    archive_size = os.path.getsize(archive_path)
    logger.info(f"归档大小: {format_size(archive_size)}")

    cmd = ["unsquashfs", "-f", "-d", target_dir, "-percentage", archive_path]
    start = time.time()

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        _monitor_percentage(proc, logger)
        proc.wait()
        rc = proc.returncode
    except Exception as e:
        logger.error(f"执行异常: {e}")
        elapsed = time.time() - start
        log_summary(logger, status="失败", operation="全量恢复", 耗时=f"{elapsed:.1f}s", 错误=str(e))
        return False, elapsed

    elapsed = time.time() - start

    if rc != 0:
        logger.error(f"unsquashfs 失败, 退出码: {rc}")
        log_summary(logger, status="失败", operation="全量恢复", 耗时=f"{elapsed:.1f}s", 退出码=rc)
        return False, elapsed

    log_summary(
        logger,
        status="成功",
        operation="全量恢复",
        归档=archive_path,
        目标=target_dir,
        归档大小=format_size(archive_size),
        耗时=f"{elapsed:.1f}s",
    )
    return True, elapsed


def _monitor_percentage(proc: subprocess.Popen, logger: logging.Logger) -> None:
    last_pct = -1
    for raw in proc.stdout:
        line = raw.decode(errors="replace").strip()
        if not line:
            continue
        try:
            pct = int(line)
        except ValueError:
            if line and not line.startswith("["):
                logger.debug(line)
            continue
        if pct != last_pct and 0 <= pct <= 100:
            log_progress(logger, pct)
            last_pct = pct
