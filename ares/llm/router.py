"""LLM routing logic for ARES.

Routing rules:
- Task is sensitive/personal → local LM Studio (stays on device)
- Task requires complex reasoning or vision → cloud (claude-sonnet-4-6)
- High-volume generation (bulk work) → local LM Studio (don't burn API credits)
- Local model produces noticeably worse results → escalate to cloud
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class LLMBackend(str, Enum):
    LOCAL = "local"
    CLOUD = "cloud"


class TaskSensitivity(str, Enum):
    PERSONAL = "personal"       # → local only
    GENERAL = "general"         # → cloud preferred
    BULK = "bulk"               # → local (cost)
    VISION = "vision"           # → cloud (vision support)
    REASONING = "reasoning"     # → cloud (complex reasoning)


def route(
    *,
    task_type: str = "general",
    sensitive: bool = False,
    requires_vision: bool = False,
    bulk: bool = False,
    force: LLMBackend | None = None,
) -> LLMBackend:
    """Decide which LLM backend to use."""
    if force is not None:
        return force

    if sensitive:
        return LLMBackend.LOCAL

    if bulk:
        return LLMBackend.LOCAL

    if requires_vision:
        return LLMBackend.CLOUD

    if task_type in ("reasoning", "planning", "vision", "complex"):
        return LLMBackend.CLOUD

    return LLMBackend.CLOUD  # Default to cloud for quality


def route_from_hint(hint: str) -> LLMBackend:
    """Route based on a free-text hint."""
    hint_lower = hint.lower()
    local_keywords = ["personal", "private", "sensitive", "local only", "bulk", "batch"]
    cloud_keywords = ["vision", "image", "screenshot", "complex", "reasoning", "plan"]

    for kw in local_keywords:
        if kw in hint_lower:
            return LLMBackend.LOCAL

    for kw in cloud_keywords:
        if kw in hint_lower:
            return LLMBackend.CLOUD

    return LLMBackend.CLOUD
