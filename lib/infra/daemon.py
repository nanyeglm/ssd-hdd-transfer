"""Daemon process management: fork+setsid, PID lock file, signal handling.

Uses os.pipe() for reliable parent-child PID synchronization (no file polling).
"""

import atexit
import json
import logging
import os
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

LOCK_FILE = Path(__file__).resolve().parent.parent.parent / ".transfer.lock"

LOCK_FAILED_MARKER = "LOCK_FAILED"


def acquire_lock(task_type: str, src: str, dst: str, log_path: str) -> bool:
    """Try to acquire the lock. Returns True on success."""
    if LOCK_FILE.exists():
        try:
            info = json.loads(LOCK_FILE.read_text())
            pid = info.get("pid", 0)
            if pid and _pid_alive(pid):
                return False
        except (json.JSONDecodeError, OSError):
            pass
        LOCK_FILE.unlink(missing_ok=True)

    info = {
        "pid": os.getpid(),
        "type": task_type,
        "src": src,
        "dst": dst,
        "log": log_path,
        "start_time": time.time(),
    }
    LOCK_FILE.write_text(json.dumps(info, ensure_ascii=False))
    return True


def release_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


def get_task_status() -> dict[str, Any] | None:
    """Return running task info, or None if no task is active."""
    if not LOCK_FILE.exists():
        return None
    try:
        info = json.loads(LOCK_FILE.read_text())
        pid = info.get("pid", 0)
        if pid and _pid_alive(pid):
            return info
        LOCK_FILE.unlink(missing_ok=True)
        return None
    except (json.JSONDecodeError, OSError):
        return None


def daemonize(
    task_func: Callable,
    task_kwargs: dict,
    task_type: str,
    src: str,
    dst: str,
    log_path: str,
) -> int | None:
    """Fork a daemon process to run task_func.

    Returns the real daemon PID to the parent, or None if the daemon
    failed to start (e.g. lock acquisition failure).

    Uses os.pipe() for synchronization: the daemon writes its PID (or
    LOCK_FAILED) through the pipe, and the parent reads it -- no file
    polling, no timeout races.
    """
    r_fd, w_fd = os.pipe()

    pid = os.fork()
    if pid > 0:
        os.close(w_fd)
        with os.fdopen(r_fd, "r") as r:
            msg = r.read().strip()
        if msg == LOCK_FAILED_MARKER:
            return None
        try:
            return int(msg)
        except ValueError:
            return None

    # First child
    os.close(r_fd)
    os.setsid()

    pid2 = os.fork()
    if pid2 > 0:
        os.close(w_fd)
        os._exit(0)

    # Grand-child: the actual daemon
    sys.stdin.close()
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)

    if not acquire_lock(task_type, src, dst, log_path):
        with os.fdopen(w_fd, "w") as w:
            w.write(LOCK_FAILED_MARKER)
        _write_crash_log(log_path, "已有任务正在运行，无法获取锁", is_lock_fail=True)
        os._exit(1)

    with os.fdopen(w_fd, "w") as w:
        w.write(str(os.getpid()))

    atexit.register(release_lock)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    try:
        task_func(**task_kwargs)
    except Exception as e:
        _write_crash_log(log_path, e)
    finally:
        release_lock()

    os._exit(0)


def _write_crash_log(log_path: str, error: object, is_lock_fail: bool = False) -> None:
    """Write error info + DAEMON_EXIT to the log so follow_log can detect it."""
    try:
        from .logger import make_daemon_logger, SUMMARY_SEPARATOR
        lgr = make_daemon_logger("crash", log_path)

        if is_lock_fail:
            lgr.error(f"{LOCK_FAILED_MARKER}: {error}")
        else:
            lgr.error(f"守护进程异常: {error}")
            lgr.error(traceback.format_exc())

        lgr.info(SUMMARY_SEPARATOR)
        lgr.info("SUMMARY_START")
        lgr.info(f"状态: {'锁冲突' if is_lock_fail else '异常退出'}")
        lgr.info(f"错误: {error}")
        lgr.info("SUMMARY_END")
        lgr.info(SUMMARY_SEPARATOR)
        lgr.info(f"DAEMON_EXIT PID={os.getpid()}")
    except Exception:
        pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
