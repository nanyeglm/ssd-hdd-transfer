"""Archive logic: SSD directory -> HDD .sqsh via mksquashfs.

Two-phase pipeline for optimal speed:
  Phase 1: mksquashfs writes to SSD temp (fast, no HDD bottleneck)
  Phase 2: Copy SSD->HDD with inline xxh128 hash (hash cost = 0, overlapped with HDD write)

Falls back to direct-to-HDD if SSD temp space is insufficient.
"""

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import time

from ..infra.checksum import save_checksum
from ..infra.disk import format_size, get_free_space
from ..infra.logger import log_progress, log_summary

MKSQUASHFS_OPTS = [
    "-comp", "zstd",
    "-Xcompression-level", "1",
    "-b", "262144",
    "-processors", str(os.cpu_count() or 4),
    "-noappend",
    "-percentage",
]

COPY_CHUNK = 8 * 1024 * 1024  # 8 MB
SSD_STAGING_DIR = "/mnt/data/.transfer_staging"


def run_archive(
    source_dir: str,
    archive_path: str,
    total_bytes: int,
    logger: logging.Logger,
) -> tuple[bool, str, int, float]:
    """Execute mksquashfs to create a new archive.

    Returns (success, hash_value, archive_size_bytes, elapsed_seconds).
    """
    logger.info(f"任务启动 | 类型: 归档 | PID: {os.getpid()}")
    logger.info(f"源路径: {source_dir} ({format_size(total_bytes)})")
    logger.info(f"目标: {archive_path}")

    estimated_archive = int(total_bytes * 0.6)
    ssd_free = get_free_space(os.path.dirname(source_dir))
    use_staging = ssd_free > estimated_archive * 1.1

    if use_staging:
        logger.info("模式: 两阶段 (SSD 暂存 + 内联 hash 传输)")
        return _two_phase_archive(source_dir, archive_path, total_bytes, logger)
    else:
        logger.info("模式: 直写 HDD (SSD 空间不足, 回退)")
        return _direct_archive(source_dir, archive_path, total_bytes, logger)


def _two_phase_archive(
    source_dir: str,
    archive_path: str,
    total_bytes: int,
    logger: logging.Logger,
) -> tuple[bool, str, int, float]:
    """Phase 1: mksquashfs to SSD.  Phase 2: inline-hash copy to HDD."""
    os.makedirs(SSD_STAGING_DIR, exist_ok=True)
    tmp_sqsh = os.path.join(SSD_STAGING_DIR, f"_tmp_{os.getpid()}.sqsh")
    start = time.time()

    try:
        # Phase 1: mksquashfs -> SSD temp
        logger.info("阶段 1/2: 压缩归档到 SSD 暂存...")
        cmd = ["mksquashfs", source_dir, tmp_sqsh] + MKSQUASHFS_OPTS
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        )
        _monitor_percentage(proc, logger)
        proc.wait()
        if proc.returncode != 0:
            logger.error(f"mksquashfs 失败, 退出码: {proc.returncode}")
            _cleanup(tmp_sqsh, archive_path)
            elapsed = time.time() - start
            log_summary(logger, status="失败", operation="归档", 耗时=f"{elapsed:.1f}s")
            return False, "", 0, elapsed

        archive_size = os.path.getsize(tmp_sqsh)
        phase1_time = time.time() - start
        logger.info(f"阶段 1 完成: {format_size(archive_size)}, {phase1_time:.1f}s")

        # Phase 2: inline-hash copy SSD -> HDD
        logger.info("阶段 2/2: 内联 hash + 传输到 HDD...")
        hash_val = _inline_hash_copy(tmp_sqsh, archive_path, archive_size, logger)
        save_checksum(hash_val, archive_path)
        logger.info(f"校验和: {hash_val}")

    except Exception as e:
        logger.error(f"归档异常: {e}")
        _cleanup(tmp_sqsh, archive_path)
        elapsed = time.time() - start
        log_summary(logger, status="失败", operation="归档", 耗时=f"{elapsed:.1f}s", 错误=str(e))
        return False, "", 0, elapsed
    finally:
        _safe_remove(tmp_sqsh)

    elapsed = time.time() - start
    archive_size = os.path.getsize(archive_path) if os.path.exists(archive_path) else 0

    log_summary(
        logger, status="成功", operation="归档",
        源路径=source_dir, 源大小=format_size(total_bytes),
        归档文件=archive_path, 归档大小=format_size(archive_size),
        压缩率=f"{archive_size / max(total_bytes, 1) * 100:.1f}%",
        校验和=hash_val, 耗时=f"{elapsed:.1f}s",
    )
    return True, hash_val, archive_size, elapsed


def _direct_archive(
    source_dir: str,
    archive_path: str,
    total_bytes: int,
    logger: logging.Logger,
) -> tuple[bool, str, int, float]:
    """Fallback: write directly to HDD, then compute hash separately."""
    cmd = ["mksquashfs", source_dir, archive_path] + MKSQUASHFS_OPTS
    start = time.time()

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        )
        _monitor_percentage(proc, logger)
        proc.wait()
        if proc.returncode != 0:
            logger.error(f"mksquashfs 失败, 退出码: {proc.returncode}")
            _cleanup("", archive_path)
            elapsed = time.time() - start
            log_summary(logger, status="失败", operation="归档", 耗时=f"{elapsed:.1f}s")
            return False, "", 0, elapsed
    except Exception as e:
        logger.error(f"执行异常: {e}")
        _cleanup("", archive_path)
        elapsed = time.time() - start
        log_summary(logger, status="失败", operation="归档", 耗时=f"{elapsed:.1f}s", 错误=str(e))
        return False, "", 0, elapsed

    archive_size = os.path.getsize(archive_path) if os.path.exists(archive_path) else 0

    logger.info("正在计算校验和 (直写模式, 需读取 HDD)...")
    try:
        result = subprocess.run(
            ["xxh128sum", archive_path], capture_output=True, text=True, timeout=7200,
        )
        hash_val = result.stdout.strip().split()[0] if result.returncode == 0 else ""
        if hash_val:
            save_checksum(hash_val, archive_path)
            logger.info(f"校验和: {hash_val}")
    except Exception as e:
        logger.warning(f"校验和失败: {e}")
        hash_val = ""

    elapsed = time.time() - start
    log_summary(
        logger, status="成功", operation="归档",
        源路径=source_dir, 源大小=format_size(total_bytes),
        归档文件=archive_path, 归档大小=format_size(archive_size),
        压缩率=f"{archive_size / max(total_bytes, 1) * 100:.1f}%",
        校验和=hash_val or "N/A", 耗时=f"{elapsed:.1f}s",
    )
    return True, hash_val, archive_size, elapsed


def _inline_hash_copy(
    src_path: str,
    dst_path: str,
    total_size: int,
    logger: logging.Logger,
) -> str:
    """Copy file from SSD to HDD while computing xxh128 hash inline.

    Uses subprocess xxh128sum reading from a pipe fed by Python,
    so we get the exact same hash format as the standalone tool.
    """
    hasher = subprocess.Popen(
        ["xxh128sum"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    copied = 0
    last_pct = -1

    with open(src_path, "rb") as fin, open(dst_path, "wb") as fout:
        while True:
            chunk = fin.read(COPY_CHUNK)
            if not chunk:
                break
            fout.write(chunk)
            hasher.stdin.write(chunk)
            copied += len(chunk)

            pct = int(copied * 100 / total_size) if total_size > 0 else 100
            if pct != last_pct:
                log_progress(logger, pct)
                last_pct = pct

    hasher.stdin.close()
    hasher.wait()
    raw = hasher.stdout.read().decode(errors="replace").strip()
    return raw.split()[0] if raw else ""


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


def _cleanup(*paths: str) -> None:
    for f in paths:
        if f:
            _safe_remove(f)
            _safe_remove(f + ".xxh128")


def _safe_remove(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
