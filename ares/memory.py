"""Memory system for ARES.

~/.ares/memory/
├── episodic/       JSONL task logs with outcomes
├── preferences/    How user likes things done (Markdown + TOML)
├── tools/          registry.toml — tool configs and quirks
├── knowledge/      Research notes and learned facts (Markdown)
└── projects/       Per-project context and state (TOML)

All plain files. Readable in any text editor. Synced via iCloud.
"""

from __future__ import annotations

import json
import tomllib
import tomli_w
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ares_paths


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _paths() -> dict[str, Path]:
    return ares_paths()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Episodic memory — JSONL task logs
# ---------------------------------------------------------------------------

@dataclass
class EpisodicEntry:
    task_id: str
    goal: str
    started_at: str
    completed_at: str | None = None
    outcome: str = "in_progress"  # in_progress | success | failed | cancelled
    stages: list[dict[str, Any]] = field(default_factory=list)
    retrospective: str = ""
    preferences_noticed: list[str] = field(default_factory=list)
    api_cost_usd: float = 0.0


def episodic_path() -> Path:
    return _paths()["memory_episodic"]


def write_episodic(entry: EpisodicEntry) -> Path:
    """Append or update an episodic entry in its JSONL file."""
    path = episodic_path() / f"{entry.task_id}.jsonl"
    with open(path, "a") as fh:
        fh.write(json.dumps(asdict(entry)) + "\n")
    return path


def read_episodic(task_id: str) -> list[EpisodicEntry]:
    path = episodic_path() / f"{task_id}.jsonl"
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            entries.append(EpisodicEntry(**json.loads(line)))
    return entries


def list_episodic(limit: int = 20) -> list[dict[str, Any]]:
    """Return summary of recent episodic entries."""
    p = episodic_path()
    files = sorted(p.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    summaries = []
    for f in files[:limit]:
        lines = f.read_text().splitlines()
        if lines:
            last = json.loads(lines[-1])
            summaries.append({
                "task_id": last.get("task_id"),
                "goal": last.get("goal"),
                "outcome": last.get("outcome"),
                "completed_at": last.get("completed_at"),
            })
    return summaries


# ---------------------------------------------------------------------------
# Preferences — Markdown + TOML
# ---------------------------------------------------------------------------

def preferences_path() -> Path:
    return _paths()["memory_preferences"]


def write_preference(key: str, value: Any) -> Path:
    """Write a preference to preferences/profile.toml."""
    path = preferences_path() / "profile.toml"
    existing: dict[str, Any] = {}
    if path.exists():
        with open(path, "rb") as fh:
            existing = tomllib.load(fh)
    existing[key] = value
    with open(path, "wb") as fh:
        tomli_w.dump(existing, fh)
    return path


def read_preferences() -> dict[str, Any]:
    path = preferences_path() / "profile.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def append_preference_note(note: str) -> Path:
    """Append a free-form note to preferences/notes.md."""
    path = preferences_path() / "notes.md"
    ts = _now_iso()
    with open(path, "a") as fh:
        fh.write(f"\n## {ts}\n\n{note}\n")
    return path


# ---------------------------------------------------------------------------
# Knowledge — Markdown research notes
# ---------------------------------------------------------------------------

def knowledge_path() -> Path:
    return _paths()["memory_knowledge"]


def write_knowledge(title: str, content: str, tags: list[str] | None = None) -> Path:
    """Write a knowledge note."""
    slug = title.lower().replace(" ", "-").replace("/", "-")[:60]
    path = knowledge_path() / f"{slug}.md"
    ts = _now_iso()
    header = f"# {title}\n\nCreated: {ts}"
    if tags:
        header += f"\nTags: {', '.join(tags)}"
    header += "\n\n---\n\n"
    path.write_text(header + content)
    return path


def read_knowledge(slug: str) -> str | None:
    path = knowledge_path() / f"{slug}.md"
    if not path.exists():
        return None
    return path.read_text()


def list_knowledge() -> list[str]:
    return [f.stem for f in knowledge_path().glob("*.md")]


# ---------------------------------------------------------------------------
# Projects — Per-project TOML state
# ---------------------------------------------------------------------------

def projects_path() -> Path:
    return _paths()["memory_projects"]


def write_project(project_id: str, data: dict[str, Any]) -> Path:
    path = projects_path() / f"{project_id}.toml"
    existing: dict[str, Any] = {}
    if path.exists():
        with open(path, "rb") as fh:
            existing = tomllib.load(fh)
    existing.update(data)
    existing["updated_at"] = _now_iso()
    with open(path, "wb") as fh:
        tomli_w.dump(existing, fh)
    return path


def read_project(project_id: str) -> dict[str, Any]:
    path = projects_path() / f"{project_id}.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def list_projects() -> list[str]:
    return [f.stem for f in projects_path().glob("*.toml")]


# ---------------------------------------------------------------------------
# Retrospective writer
# ---------------------------------------------------------------------------

async def write_retrospective(
    task_id: str,
    goal: str,
    what_worked: str,
    what_didnt: str,
    preferences_noticed: list[str],
    do_differently: str,
    api_cost_usd: float = 0.0,
) -> None:
    """Write a retrospective after task completion."""
    entry = EpisodicEntry(
        task_id=task_id,
        goal=goal,
        started_at=_now_iso(),
        completed_at=_now_iso(),
        outcome="success",
        retrospective=f"## What worked\n{what_worked}\n\n## What didn't\n{what_didnt}\n\n## Do differently\n{do_differently}",
        preferences_noticed=preferences_noticed,
        api_cost_usd=api_cost_usd,
    )
    write_episodic(entry)

    # Also write preferences noticed
    for pref in preferences_noticed:
        append_preference_note(f"[{task_id}] {pref}")
