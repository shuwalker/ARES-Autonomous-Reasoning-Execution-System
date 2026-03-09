"""Task queue for ARES.

Tasks live in ~/.ares/tasks/queue.jsonl — one JSON object per line.
This allows the MacBook to enqueue tasks by appending to the file via iCloud sync.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import ares_paths
from ..audit import log


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Task:
    id: str
    goal: str
    status: str = "queued"          # queued | planning | executing | paused | done | failed
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    priority: int = 5               # 1 (highest) — 10 (lowest)
    current_stage: int = 0
    plan_json: dict[str, Any] = field(default_factory=dict)
    result: str = ""
    error: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


def new_task(goal: str, priority: int = 5, context: dict[str, Any] | None = None) -> Task:
    return Task(
        id=f"task-{uuid.uuid4().hex[:8]}",
        goal=goal,
        priority=priority,
        context=context or {},
    )


# ---------------------------------------------------------------------------
# Queue I/O
# ---------------------------------------------------------------------------

def _queue_path() -> Path:
    return ares_paths()["tasks"] / "queue.jsonl"


def _archive_path() -> Path:
    return ares_paths()["tasks"] / "archive.jsonl"


def enqueue(task: Task) -> None:
    """Add a task to the queue."""
    path = _queue_path()
    with open(path, "a") as fh:
        fh.write(json.dumps(asdict(task)) + "\n")


def _read_all() -> list[Task]:
    path = _queue_path()
    if not path.exists():
        return []
    tasks = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            tasks.append(Task(**json.loads(line)))
    return tasks


def _write_all(tasks: list[Task]) -> None:
    path = _queue_path()
    with open(path, "w") as fh:
        for task in tasks:
            fh.write(json.dumps(asdict(task)) + "\n")


def get_next_ready() -> Task | None:
    """Return the highest-priority queued task, or None."""
    tasks = _read_all()
    ready = [t for t in tasks if t.status == "queued"]
    if not ready:
        return None
    return min(ready, key=lambda t: t.priority)


def update_task(task: Task) -> None:
    """Update a task in the queue in-place."""
    tasks = _read_all()
    for i, t in enumerate(tasks):
        if t.id == task.id:
            tasks[i] = task
            break
    _write_all(tasks)


def archive_task(task: Task) -> None:
    """Move a completed/failed task to the archive."""
    tasks = _read_all()
    tasks = [t for t in tasks if t.id != task.id]
    _write_all(tasks)

    path = _archive_path()
    with open(path, "a") as fh:
        fh.write(json.dumps(asdict(task)) + "\n")


def list_active() -> list[Task]:
    return [t for t in _read_all() if t.status not in ("done", "failed")]


def get_task(task_id: str) -> Task | None:
    for t in _read_all():
        if t.id == task_id:
            return t
    return None


# ---------------------------------------------------------------------------
# Inbox — accept goals from CLI / MacBook
# ---------------------------------------------------------------------------

class Inbox:
    """Simple async inbox for new goals."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    async def put(self, goal: str) -> None:
        await self._queue.put(goal)

    async def drain(self) -> list[Task]:
        """Drain the inbox and create Task objects."""
        new_tasks = []
        while not self._queue.empty():
            goal = self._queue.get_nowait()
            task = new_task(goal)
            enqueue(task)
            await log(task_id=task.id, action="task_queued", goal=goal[:80])
            new_tasks.append(task)
        return new_tasks

    def put_nowait(self, goal: str) -> None:
        self._queue.put_nowait(goal)
