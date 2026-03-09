"""Tool registry for ARES.

Lives at ~/.ares/memory/tools/registry.toml — plain TOML, human-editable.

Each tool entry looks like:
[tools.n8n]
name = "n8n"
description = "Workflow automation platform"
install_method = "npm"
install_command = "npm install -g n8n"
check_command = "n8n --version"
url = "http://localhost:5678"
installed = true
version = "1.x.x"
notes = "Primary workflow engine"
"""

from __future__ import annotations

import subprocess
import tomllib
import tomli_w
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from ..config import ares_paths
from ..audit import log_sync


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ToolEntry:
    name: str
    description: str = ""
    install_method: str = ""      # brew | npm | pip | manual | none
    install_command: str = ""
    check_command: str = ""
    url: str = ""
    installed: bool = False
    version: str = ""
    notes: str = ""
    quirks: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Registry paths
# ---------------------------------------------------------------------------

def registry_path() -> Path:
    return ares_paths()["memory_tools"] / "registry.toml"


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------

def load_registry() -> dict[str, ToolEntry]:
    path = registry_path()
    if not path.exists():
        return {}
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    tools_raw = raw.get("tools", {})
    result: dict[str, ToolEntry] = {}
    for key, data in tools_raw.items():
        result[key] = ToolEntry(
            name=data.get("name", key),
            description=data.get("description", ""),
            install_method=data.get("install_method", ""),
            install_command=data.get("install_command", ""),
            check_command=data.get("check_command", ""),
            url=data.get("url", ""),
            installed=data.get("installed", False),
            version=data.get("version", ""),
            notes=data.get("notes", ""),
            quirks=data.get("quirks", []),
        )
    return result


def save_registry(tools: dict[str, ToolEntry]) -> Path:
    path = registry_path()
    data: dict[str, Any] = {"tools": {}}
    for key, entry in tools.items():
        d = asdict(entry)
        data["tools"][key] = d
    with open(path, "wb") as fh:
        tomli_w.dump(data, fh)
    return path


def register_tool(key: str, entry: ToolEntry) -> None:
    tools = load_registry()
    tools[key] = entry
    save_registry(tools)
    log_sync(action="tool_registered", tool=key)


def get_tool(key: str) -> ToolEntry | None:
    return load_registry().get(key)


def mark_installed(key: str, version: str = "") -> None:
    tools = load_registry()
    if key in tools:
        tools[key].installed = True
        tools[key].version = version
        save_registry(tools)


# ---------------------------------------------------------------------------
# Install / check helpers
# ---------------------------------------------------------------------------

def check_tool_installed(entry: ToolEntry) -> tuple[bool, str]:
    """Run check_command and return (installed, version_string)."""
    if not entry.check_command:
        return False, ""
    try:
        result = subprocess.run(
            entry.check_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            version = result.stdout.strip().splitlines()[0] if result.stdout else ""
            return True, version
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return False, ""


def probe_all_tools() -> dict[str, bool]:
    """Check installation status for all registered tools."""
    tools = load_registry()
    status: dict[str, bool] = {}
    for key, entry in tools.items():
        installed, version = check_tool_installed(entry)
        if installed and not entry.installed:
            tools[key].installed = True
            tools[key].version = version
        status[key] = installed
    save_registry(tools)
    return status


# ---------------------------------------------------------------------------
# Built-in tool definitions (pre-populated registry)
# ---------------------------------------------------------------------------

BUILT_IN_TOOLS: dict[str, ToolEntry] = {
    "n8n": ToolEntry(
        name="n8n",
        description="Workflow automation platform — visible, editable workflows",
        install_method="npm",
        install_command="npm install -g n8n",
        check_command="n8n --version",
        url="http://localhost:5678",
        notes="Primary workflow engine for ARES automations",
    ),
    "elevenlabs": ToolEntry(
        name="ElevenLabs",
        description="AI voice synthesis — cloned voice TTS",
        install_method="none",
        url="https://elevenlabs.io",
        notes="Web API, no local install needed. Requires API key.",
    ),
    "davinci_resolve": ToolEntry(
        name="DaVinci Resolve",
        description="Professional video editor — .drp project format",
        install_method="manual",
        url="https://www.blackmagicdesign.com/products/davinciresolve",
        notes="GUI app. ARES opens .drp files and can script via Lua API.",
    ),
    "lm_studio": ToolEntry(
        name="LM Studio",
        description="Local LLM inference server — OpenAI-compatible API",
        install_method="manual",
        url="http://localhost:1234",
        check_command="curl -s http://localhost:1234/v1/models",
        notes="Runs local models. ARES uses this for sensitive/high-volume tasks.",
    ),
    "homebrew": ToolEntry(
        name="Homebrew",
        description="macOS package manager",
        install_method="manual",
        check_command="brew --version",
        notes="Primary CLI package manager for macOS",
    ),
}


def ensure_builtin_tools() -> None:
    """Ensure built-in tool definitions are in the registry."""
    tools = load_registry()
    changed = False
    for key, entry in BUILT_IN_TOOLS.items():
        if key not in tools:
            tools[key] = entry
            changed = True
    if changed:
        save_registry(tools)
