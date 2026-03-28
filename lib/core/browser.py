"""Archive directory browser and search engine.

Parses `unsquashfs -lls -d ""` output into a structured tree that supports
directory navigation, multi-keyword / glob / regex search.
"""

import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FileEntry:
    path: str
    is_dir: bool
    size: int  # bytes; -1 for directories without explicit size
    mtime: str = ""
    permissions: str = ""
    owner: str = ""

    @property
    def name(self) -> str:
        return os.path.basename(self.path.rstrip("/"))

    @property
    def parent(self) -> str:
        return os.path.dirname(self.path.rstrip("/"))

    @property
    def depth(self) -> int:
        p = self.path.strip("/")
        return p.count("/") + 1 if p else 0


_cache: dict[str, list[FileEntry]] = {}


def load_archive_tree(archive_path: str) -> list[FileEntry]:
    """Load full directory listing from archive. Cached per archive path."""
    rp = os.path.realpath(archive_path)
    if rp in _cache:
        return _cache[rp]

    result = subprocess.run(
        ["unsquashfs", "-lls", "-d", "", archive_path],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"unsquashfs -lls 失败: {result.stderr.strip()}")

    entries = _parse_lls(result.stdout)
    _cache[rp] = entries
    return entries


def invalidate_cache(archive_path: str | None = None) -> None:
    """Clear cached listings. Pass None to clear all."""
    if archive_path is None:
        _cache.clear()
    else:
        _cache.pop(os.path.realpath(archive_path), None)


def list_directory(entries: list[FileEntry], dir_path: str) -> list[FileEntry]:
    """Return direct children of *dir_path* (one level)."""
    dir_path = dir_path.strip("/")
    children = []
    seen = set()
    for e in entries:
        ep = e.path.strip("/")
        if not ep:
            continue
        if dir_path == "":
            parts = ep.split("/")
            top = parts[0]
            if top not in seen:
                seen.add(top)
                if len(parts) == 1:
                    children.append(e)
                else:
                    children.append(_find_dir_entry(entries, top))
        else:
            if not ep.startswith(dir_path + "/"):
                continue
            rel = ep[len(dir_path) + 1:]
            if "/" not in rel and rel:
                children.append(e)

    children.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    return children


def get_top_level_names(entries: list[FileEntry]) -> set[str]:
    """Return names at archive root."""
    names = set()
    for e in entries:
        p = e.path.strip("/")
        if not p:
            continue
        names.add(p.split("/")[0])
    return names


def search(entries: list[FileEntry], pattern: str, mode: str = "keyword") -> list[FileEntry]:
    """Search entries by pattern.

    Modes:
      keyword — space-separated words, ALL must appear in path (case-insensitive)
      glob    — fnmatch pattern matched against the basename
      regex   — POSIX regex matched against the full path
    """
    if mode == "keyword":
        words = pattern.lower().split()
        if not words:
            return []
        return [e for e in entries if e.path.strip("/") and all(w in e.path.lower() for w in words)]
    elif mode == "glob":
        return [e for e in entries if e.path.strip("/") and fnmatch.fnmatch(e.name.lower(), pattern.lower())]
    elif mode == "regex":
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error:
            return []
        return [e for e in entries if e.path.strip("/") and rx.search(e.path)]
    return []


def get_dir_summary(entries: list[FileEntry], dir_path: str) -> tuple[int, int]:
    """Return (total_size_bytes, file_count) under dir_path."""
    dir_path = dir_path.strip("/")
    prefix = dir_path + "/" if dir_path else ""
    total = 0
    count = 0
    for e in entries:
        ep = e.path.strip("/")
        if not ep:
            continue
        if prefix and not ep.startswith(prefix) and ep != dir_path:
            continue
        if not prefix or ep.startswith(prefix):
            if not e.is_dir and e.size > 0:
                total += e.size
                count += 1
    return total, count


def _parse_lls(output: str) -> list[FileEntry]:
    """Parse `unsquashfs -lls -d ""` output into FileEntry list.

    Format per line: ``permissions owner size YYYY-MM-DD HH:MM path``
    Path may be empty (root entry) or start with ``/``.
    Symlinks have `` -> target`` appended.
    """
    entries = []
    for line in output.strip().split("\n"):
        if not line or line.startswith("Parallel") or line.startswith("squashfs"):
            continue

        perms_char = line[0] if line else ""
        if perms_char not in "dlcbps-":
            continue

        parts = line.split(None, 5)
        # parts: [perms, owner, size, date, time, path_or_empty]
        if len(parts) < 5:
            continue

        perms = parts[0]
        owner = parts[1]
        try:
            size = int(parts[2])
        except ValueError:
            size = -1
        mtime = f"{parts[3]} {parts[4]}"

        path_str = parts[5].strip() if len(parts) > 5 else ""

        if " -> " in path_str:
            path_str = path_str.split(" -> ")[0].strip()

        is_dir = perms.startswith("d")
        if is_dir:
            size = -1

        path_str = path_str.lstrip("/")
        if path_str:
            entries.append(FileEntry(
                path=path_str,
                is_dir=is_dir,
                size=size,
                mtime=mtime,
                permissions=perms,
                owner=owner,
            ))
    return entries


def _find_dir_entry(entries: list[FileEntry], name: str) -> FileEntry:
    """Find or create a synthetic entry for a top-level directory."""
    for e in entries:
        if e.path.strip("/") == name and e.is_dir:
            return e
    return FileEntry(path=name, is_dir=True, size=-1)
