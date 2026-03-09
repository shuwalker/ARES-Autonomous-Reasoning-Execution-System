"""Local LLM client — LM Studio at localhost:1234.

Uses OpenAI-compatible API.
"""

from __future__ import annotations

import httpx
from typing import Any

from ..config import get_config
from ..audit import log


async def complete(
    *,
    system: str,
    messages: list[dict[str, Any]],
    task_id: str | None = None,
    max_tokens: int = 4096,
    model: str | None = None,
) -> str:
    """Call the local LM Studio model and return the text response."""
    cfg = get_config()
    base_url = cfg.llm.local_url
    model = model or cfg.llm.local_model

    await log(
        task_id=task_id,
        action="llm_call",
        backend="local",
        model=model,
        url=base_url,
    )

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "max_tokens": max_tokens,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"]["content"]

            await log(
                task_id=task_id,
                action="llm_response",
                backend="local",
                tokens=data.get("usage", {}).get("completion_tokens", 0),
            )
            return text

    except (httpx.ConnectError, httpx.TimeoutException) as e:
        await log(
            task_id=task_id,
            action="llm_error",
            backend="local",
            error=str(e),
        )
        raise RuntimeError(
            f"LM Studio not reachable at {base_url}. "
            "Is LM Studio running with a model loaded?"
        ) from e


async def is_available() -> bool:
    """Check if LM Studio is running."""
    cfg = get_config()
    base_url = cfg.llm.local_url
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{base_url}/models")
            return response.status_code == 200
    except Exception:
        return False
