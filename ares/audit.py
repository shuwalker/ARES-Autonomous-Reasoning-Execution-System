"""Audit logging for ARES.

Every action is logged to ~/.ares/logs/exec.log in the format:
2025-03-09T14:22:01Z  [TASK:yt-001]  stage=script  action=llm_call  model=claude-sonnet-4-6
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ares_paths

_log_path: Path | None = None
_log_file = None
_lock: asyncio.Lock | None = None


def _get_log_path() -> Path:
    global _log_path
    if _log_path is None:
        paths = ares_paths()
        _log_path = paths["logs"] / "exec.log"
    return _log_path


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _format_entry(task_id: str | None, **fields: Any) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tag = f"[TASK:{task_id}]" if task_id else "[SYSTEM]"
    field_str = "  ".join(f"{k}={v}" for k, v in fields.items())
    return f"{ts}  {tag}  {field_str}"


def log_sync(task_id: str | None = None, **fields: Any) -> None:
    """Synchronous log write (for use outside async context)."""
    entry = _format_entry(task_id, **fields)
    print(entry, file=sys.stderr)  # Always echo to stderr
    path = _get_log_path()
    with open(path, "a") as fh:
        fh.write(entry + "\n")


async def log(task_id: str | None = None, **fields: Any) -> None:
    """Async log write."""
    entry = _format_entry(task_id, **fields)
    print(entry, file=sys.stderr)
    path = _get_log_path()
    lock = _get_lock()
    async with lock:
        with open(path, "a") as fh:
            fh.write(entry + "\n")


def tail_log(n: int = 50) -> list[str]:
    """Return the last n lines of the audit log."""
    path = _get_log_path()
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    return lines[-n:]
