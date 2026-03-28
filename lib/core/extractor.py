"""Selective extraction: extract specific paths from .sqsh archive.

Uses -extract-file with a temp file when path count exceeds the threshold,
avoiding ARG_MAX limits on the command line.
"""

import logging
import os
import subprocess
import tempfile
import time

from ..infra.disk import format_size
from ..infra.logger import log_summary, monitor_percentage

_EXTRACT_FILE_THRESHOLD = 50


def run_extract(
    archive_path: str,
    target_dir: str,
    paths: list[str],
    logger: logging.Logger,
) -> tuple[bool, float]:
    """Extract selected paths from archive. Returns (success, elapsed)."""
    logger.info(f"任务启动 | 类型: 选择性提取 | PID: {os.getpid()}")
    logger.info(f"归档: {archive_path}")
    logger.info(f"目标: {target_dir}")
    logger.info(f"提取项: {len(paths)} 个")
    for p in paths[:20]:
        logger.info(f"  - {p}")
    if len(paths) > 20:
        logger.info(f"  ... 及其他 {len(paths) - 20} 项")

    extract_file_path = ""
    try:
        if len(paths) > _EXTRACT_FILE_THRESHOLD:
            logger.info(f"路径数 {len(paths)} > {_EXTRACT_FILE_THRESHOLD}, 使用 -extract-file 模式")
            fd, extract_file_path = tempfile.mkstemp(prefix="transfer_extract_", suffix=".txt")
            with os.fdopen(fd, "w") as f:
                for p in paths:
                    f.write(p + "\n")
            cmd = [
                "unsquashfs", "-f", "-d", target_dir, "-percentage",
                "-extract-file", extract_file_path, archive_path,
            ]
        else:
            cmd = ["unsquashfs", "-f", "-d", target_dir, "-percentage", archive_path] + paths

        start = time.time()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        monitor_percentage(proc, logger)
        proc.wait()
        rc = proc.returncode
    except Exception as e:
        logger.error(f"执行异常: {e}")
        elapsed = time.time() - start if 'start' in dir() else 0
        log_summary(logger, status="失败", operation="选择性提取", 耗时=f"{elapsed:.1f}s", 错误=str(e))
        return False, elapsed
    finally:
        if extract_file_path and os.path.exists(extract_file_path):
            os.remove(extract_file_path)

    elapsed = time.time() - start

    if rc != 0:
        logger.error(f"unsquashfs 失败, 退出码: {rc}")
        log_summary(logger, status="失败", operation="选择性提取", 耗时=f"{elapsed:.1f}s", 退出码=rc)
        return False, elapsed

    log_summary(
        logger,
        status="成功",
        operation="选择性提取",
        归档=archive_path,
        目标=target_dir,
        提取项数=len(paths),
        耗时=f"{elapsed:.1f}s",
    )
    return True, elapsed


