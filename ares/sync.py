"""iCloud Drive sync for ARES.

State lives in ~/.ares/ which should be symlinked or located inside iCloud Drive
for cross-device sync. This module handles flushing state and detecting the
iCloud path.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import ares_home, get_config
from .audit import log_sync


def detect_icloud_path() -> Path | None:
    """Detect the iCloud Drive path on macOS."""
    candidates = [
        Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs",
        Path.home() / "iCloud Drive",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def get_sync_target() -> Path | None:
    """Return the iCloud target directory for ARES state, or None if disabled."""
    cfg = get_config()
    if not cfg.sync.enabled:
        return None

    if cfg.sync.icloud_path:
        target = Path(cfg.sync.icloud_path) / ".ares"
    else:
        icloud = detect_icloud_path()
        if icloud is None:
            return None
        target = icloud / "ARES"

    target.mkdir(parents=True, exist_ok=True)
    return target


async def flush() -> None:
    """Flush current state to iCloud Drive (copy memory + tasks)."""
    target = get_sync_target()
    if target is None:
        return

    home = ares_home()
    dirs_to_sync = ["memory", "tasks", "n8n-workflows"]

    for dirname in dirs_to_sync:
        src = home / dirname
        dst = target / dirname
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    log_sync(action="sync_flush", target=str(target))


def setup_icloud_link() -> str:
    """
    Check if ~/.ares is inside iCloud or should be linked there.
    Returns a status message.
    """
    target = get_sync_target()
    if target is None:
        return "iCloud sync disabled or iCloud Drive not found."

    home = ares_home()
    return (
        f"ARES home: {home}\n"
        f"Sync target: {target}\n"
        f"Sync is active — memory and tasks will be copied on flush."
    )
