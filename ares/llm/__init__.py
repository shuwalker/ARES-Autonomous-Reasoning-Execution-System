"""LLM package — routing to cloud (Anthropic) or local (LM Studio)."""

from .router import route, LLMBackend, route_from_hint
from . import cloud, local

__all__ = ["route", "LLMBackend", "route_from_hint", "cloud", "local"]
