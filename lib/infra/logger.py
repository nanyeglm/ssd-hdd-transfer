"""Logging system: timestamped file logs with PROGRESS/SUMMARY format.

Also provides shared utilities used by both core and daemon layers:
- make_daemon_logger: factory for daemon-side file loggers (eliminates boilerplate)
- monitor_percentage: shared parser for mksquashfs/unsquashfs -percentage output
"""

import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "log"
SUMMARY_SEPARATOR = "\u2500" * 50  # ──────


def setup_logger(operation: str) -> tuple[logging.Logger, Path]:
    """Create a timestamped log file and return (logger, log_path)."""
    LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"{ts}_{operation}.log"

    logger = logging.getLogger(f"transfer.{ts}.{operation}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(fh)

    return logger, log_path


def make_daemon_logger(name: str, log_path: str) -> logging.Logger:
    """Create a file-only logger for use inside daemon processes.

    Replaces the repeated 5-line FileHandler boilerplate in every *_ui daemon task.
    """
    lgr = logging.getLogger(f"transfer.daemon.{name}")
    lgr.handlers.clear()
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    lgr.addHandler(fh)
    lgr.setLevel(logging.DEBUG)
    return lgr


def log_progress(logger: logging.Logger, percent: int) -> None:
    """Write a PROGRESS line for follow_log to parse."""
    logger.info(f"PROGRESS: {percent}%")


def log_summary(
    logger: logging.Logger,
    *,
    status: str,
    operation: str,
    **details: object,
) -> None:
    """Write a structured SUMMARY block at task completion."""
    logger.info(SUMMARY_SEPARATOR)
    logger.info("SUMMARY_START")
    logger.info(f"状态: {status}")
    logger.info(f"操作: {operation}")
    for k, v in details.items():
        logger.info(f"{k}: {v}")
    logger.info(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("SUMMARY_END")
    logger.info(SUMMARY_SEPARATOR)
    logger.info(f"DAEMON_EXIT PID={os.getpid()}")


def monitor_percentage(proc: subprocess.Popen, logger: logging.Logger) -> None:
    """Parse mksquashfs/unsquashfs -percentage stdout and log PROGRESS lines.

    With -percentage, the tool outputs plain integer lines (e.g. "14", "69", "100").
    Non-integer lines are logged at debug level.
    """
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
