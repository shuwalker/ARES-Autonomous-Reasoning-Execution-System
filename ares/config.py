"""Config loading and watching for ARES.

Config lives at ~/.ares/config/ares.toml — plain TOML, human-editable.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def ares_home() -> Path:
    """Return ~/.ares, creating it if needed."""
    base = Path(os.environ.get("ARES_HOME", Path.home() / ".ares"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def ares_paths() -> dict[str, Path]:
    home = ares_home()
    paths = {
        "home": home,
        "config": home / "config",
        "memory": home / "memory",
        "memory_episodic": home / "memory" / "episodic",
        "memory_preferences": home / "memory" / "preferences",
        "memory_tools": home / "memory" / "tools",
        "memory_knowledge": home / "memory" / "knowledge",
        "memory_projects": home / "memory" / "projects",
        "tasks": home / "tasks",
        "n8n_workflows": home / "n8n-workflows",
        "logs": home / "logs",
        "cache": home / "cache",
        "socket": home / "ares.sock",
    }
    for key, path in paths.items():
        if key != "socket":
            path.mkdir(parents=True, exist_ok=True)
    return paths


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class LLMConfig:
    local_url: str = "http://localhost:1234/v1"
    local_model: str = "local-model"
    cloud_model: str = "claude-sonnet-4-6"
    cloud_api_key: str = ""


@dataclass
class N8NConfig:
    url: str = "http://localhost:5678"
    api_key: str = ""


@dataclass
class SyncConfig:
    enabled: bool = True
    icloud_path: str = ""  # Auto-detected if empty


@dataclass
class DecisionConfig:
    # Minutes of silence after proposing a Homebrew install before auto-proceeding
    cli_install_silence_minutes: int = 5


@dataclass
class AresConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    n8n: N8NConfig = field(default_factory=N8NConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    decision: DecisionConfig = field(default_factory=DecisionConfig)
    # Raw extra values from TOML for forward-compatibility
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_CONFIG_PATH: Path | None = None
_CONFIG: AresConfig | None = None


def config_path() -> Path:
    global _CONFIG_PATH
    if _CONFIG_PATH is None:
        paths = ares_paths()
        _CONFIG_PATH = paths["config"] / "ares.toml"
    return _CONFIG_PATH


def load_config() -> AresConfig:
    global _CONFIG
    path = config_path()
    raw: dict[str, Any] = {}
    if path.exists():
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)

    cfg = AresConfig()

    llm_raw = raw.get("llm", {})
    cfg.llm.local_url = llm_raw.get("local_url", cfg.llm.local_url)
    cfg.llm.local_model = llm_raw.get("local_model", cfg.llm.local_model)
    cfg.llm.cloud_model = llm_raw.get("cloud_model", cfg.llm.cloud_model)
    cfg.llm.cloud_api_key = llm_raw.get("cloud_api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")

    n8n_raw = raw.get("n8n", {})
    cfg.n8n.url = n8n_raw.get("url", cfg.n8n.url)
    cfg.n8n.api_key = n8n_raw.get("api_key", "") or os.environ.get("N8N_API_KEY", "")

    sync_raw = raw.get("sync", {})
    cfg.sync.enabled = sync_raw.get("enabled", cfg.sync.enabled)
    cfg.sync.icloud_path = sync_raw.get("icloud_path", cfg.sync.icloud_path)

    decision_raw = raw.get("decision", {})
    cfg.decision.cli_install_silence_minutes = decision_raw.get(
        "cli_install_silence_minutes", cfg.decision.cli_install_silence_minutes
    )

    cfg.extra = {k: v for k, v in raw.items() if k not in ("llm", "n8n", "sync", "decision")}
    _CONFIG = cfg
    return cfg


def get_config() -> AresConfig:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_config()
    return _CONFIG


def write_default_config() -> Path:
    """Write a default config file if none exists."""
    import tomli_w

    path = config_path()
    if path.exists():
        return path

    data = {
        "llm": {
            "local_url": "http://localhost:1234/v1",
            "local_model": "local-model",
            "cloud_model": "claude-sonnet-4-6",
            "cloud_api_key": "",  # Set ANTHROPIC_API_KEY env var
        },
        "n8n": {
            "url": "http://localhost:5678",
            "api_key": "",
        },
        "sync": {
            "enabled": True,
            "icloud_path": "",
        },
        "decision": {
            "cli_install_silence_minutes": 5,
        },
    }

    with open(path, "wb") as fh:
        tomli_w.dump(data, fh)

    return path
