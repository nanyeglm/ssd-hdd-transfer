"""xxh128sum checksum utilities."""

import subprocess
from pathlib import Path

CHECKSUM_EXT = ".xxh128"


def checksum_path_for(archive_path: str) -> str:
    return archive_path + CHECKSUM_EXT


def compute_checksum(file_path: str) -> str:
    """Run xxh128sum and return the hex digest."""
    result = subprocess.run(
        ["xxh128sum", file_path],
        capture_output=True, text=True, timeout=7200,
    )
    if result.returncode != 0:
        raise RuntimeError(f"xxh128sum failed: {result.stderr.strip()}")
    return result.stdout.strip().split()[0]


def save_checksum(hash_val: str, archive_path: str) -> str:
    """Write hash to sidecar file. Returns the sidecar path."""
    sidecar = checksum_path_for(archive_path)
    Path(sidecar).write_text(f"{hash_val}  {archive_path}\n")
    return sidecar


def load_checksum(archive_path: str) -> str | None:
    """Read stored hash from sidecar file, or None if absent."""
    sidecar = checksum_path_for(archive_path)
    p = Path(sidecar)
    if not p.exists():
        return None
    content = p.read_text().strip()
    if content:
        return content.split()[0]
    return None


def verify_checksum(archive_path: str) -> bool:
    """Compute hash and compare with stored sidecar. Raises if no sidecar."""
    stored = load_checksum(archive_path)
    if stored is None:
        raise FileNotFoundError(f"校验文件不存在: {checksum_path_for(archive_path)}")
    actual = compute_checksum(archive_path)
    return stored.lower() == actual.lower()
