"""Cloud LLM client — Anthropic claude-sonnet-4-6.

Uses streaming for all calls to prevent timeout issues.
"""

from __future__ import annotations

import anthropic
from typing import Any

from ..config import get_config
from ..audit import log


# ---------------------------------------------------------------------------
# Client singleton
# ---------------------------------------------------------------------------

_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        cfg = get_config()
        api_key = cfg.llm.cloud_api_key
        if api_key:
            _client = anthropic.AsyncAnthropic(api_key=api_key)
        else:
            _client = anthropic.AsyncAnthropic()  # Uses ANTHROPIC_API_KEY env var
    return _client


# ---------------------------------------------------------------------------
# Core call
# ---------------------------------------------------------------------------

async def complete(
    *,
    system: str,
    messages: list[dict[str, Any]],
    task_id: str | None = None,
    max_tokens: int = 8096,
    model: str | None = None,
) -> str:
    """Call the cloud LLM and return the text response."""
    cfg = get_config()
    model = model or cfg.llm.cloud_model

    client = get_client()

    await log(
        task_id=task_id,
        action="llm_call",
        backend="cloud",
        model=model,
    )

    # Stream to handle large responses without timeout
    full_text = ""
    async with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        thinking={"type": "adaptive"},
    ) as stream:
        async for text in stream.text_stream:
            full_text += text

    await log(
        task_id=task_id,
        action="llm_response",
        backend="cloud",
        tokens=len(full_text.split()),
    )

    return full_text


async def complete_with_usage(
    *,
    system: str,
    messages: list[dict[str, Any]],
    task_id: str | None = None,
    max_tokens: int = 8096,
    model: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Call cloud LLM and return (text, usage_dict)."""
    cfg = get_config()
    model = model or cfg.llm.cloud_model
    client = get_client()

    await log(task_id=task_id, action="llm_call", backend="cloud", model=model)

    full_text = ""
    final_message = None

    async with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        thinking={"type": "adaptive"},
    ) as stream:
        async for text in stream.text_stream:
            full_text += text
        final_message = await stream.get_final_message()

    usage = {}
    if final_message:
        usage = {
            "input_tokens": final_message.usage.input_tokens,
            "output_tokens": final_message.usage.output_tokens,
        }

    await log(
        task_id=task_id,
        action="llm_response",
        backend="cloud",
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
    )

    return full_text, usage
