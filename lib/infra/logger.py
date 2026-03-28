"""Logging system: timestamped file logs with PROGRESS/SUMMARY format."""

import logging
import os
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
    logger.info(f"SUMMARY_START")
    logger.info(f"状态: {status}")
    logger.info(f"操作: {operation}")
    for k, v in details.items():
        logger.info(f"{k}: {v}")
    logger.info(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"SUMMARY_END")
    logger.info(SUMMARY_SEPARATOR)
    pid = os.getpid()
    logger.info(f"DAEMON_EXIT PID={pid}")
