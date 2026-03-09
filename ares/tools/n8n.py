"""n8n workflow automation integration for ARES.

n8n runs at localhost:5678 (or configured URL).
ARES can:
- Check if n8n is running
- List, create, activate/deactivate, and execute workflows
- Build workflow JSON drafts
- Export workflows to ~/.ares/n8n-workflows/ for version control
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from ..config import get_config, ares_paths
from ..audit import log


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class N8NClient:
    def __init__(self) -> None:
        cfg = get_config()
        self.base_url = cfg.n8n.url.rstrip("/")
        self.api_key = cfg.n8n.api_key
        self._headers = {}
        if self.api_key:
            self._headers["X-N8N-API-KEY"] = self.api_key

    async def is_running(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/workflows",
                    headers=self._headers,
                )
                return response.status_code in (200, 401)  # 401 = running but needs key
        except Exception:
            return False

    async def list_workflows(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/workflows",
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json().get("data", [])

    async def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/workflows/{workflow_id}",
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json()

    async def create_workflow(self, workflow: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/workflows",
                json=workflow,
                headers={**self._headers, "Content-Type": "application/json"},
            )
            response.raise_for_status()
            result = response.json()
            await log(action="n8n_workflow_created", id=result.get("id"), name=result.get("name"))
            return result

    async def activate_workflow(self, workflow_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.patch(
                f"{self.base_url}/api/v1/workflows/{workflow_id}",
                json={"active": True},
                headers={**self._headers, "Content-Type": "application/json"},
            )
            response.raise_for_status()
            await log(action="n8n_workflow_activated", id=workflow_id)
            return response.json()

    async def deactivate_workflow(self, workflow_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.patch(
                f"{self.base_url}/api/v1/workflows/{workflow_id}",
                json={"active": False},
                headers={**self._headers, "Content-Type": "application/json"},
            )
            response.raise_for_status()
            return response.json()

    async def execute_workflow(self, workflow_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Trigger a workflow via webhook or manual execution."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/workflows/{workflow_id}/run",
                json={"workflowData": data or {}},
                headers={**self._headers, "Content-Type": "application/json"},
            )
            response.raise_for_status()
            await log(action="n8n_workflow_executed", id=workflow_id)
            return response.json()

    async def delete_workflow(self, workflow_id: str) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(
                f"{self.base_url}/api/v1/workflows/{workflow_id}",
                headers=self._headers,
            )
            response.raise_for_status()


# ---------------------------------------------------------------------------
# Workflow templates
# ---------------------------------------------------------------------------

def youtube_publish_workflow(
    *,
    title: str = "{{$json.title}}",
    description: str = "{{$json.description}}",
    video_path: str = "{{$json.video_path}}",
    thumbnail_path: str = "{{$json.thumbnail_path}}",
) -> dict[str, Any]:
    """Build an n8n workflow JSON for YouTube publishing.

    Returns a workflow draft — show to user before activating.
    Nodes:
    1. Webhook trigger (receives task data)
    2. Read file (video)
    3. YouTube upload (via OAuth)
    4. Set thumbnail
    5. Notify (optional)
    """
    return {
        "name": "ARES — YouTube Publish",
        "nodes": [
            {
                "id": "node-webhook",
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 1,
                "position": [250, 300],
                "parameters": {
                    "httpMethod": "POST",
                    "path": "ares-youtube-publish",
                    "responseMode": "onReceived",
                },
            },
            {
                "id": "node-set",
                "name": "Prepare Data",
                "type": "n8n-nodes-base.set",
                "typeVersion": 1,
                "position": [450, 300],
                "parameters": {
                    "values": {
                        "string": [
                            {"name": "title", "value": title},
                            {"name": "description", "value": description},
                            {"name": "video_path", "value": video_path},
                        ]
                    }
                },
            },
            {
                "id": "node-code",
                "name": "Upload to YouTube",
                "type": "n8n-nodes-base.code",
                "typeVersion": 1,
                "position": [650, 300],
                "parameters": {
                    "jsCode": (
                        "// YouTube Data API upload\n"
                        "// Replace with actual YouTube OAuth node when credentials are set\n"
                        "const data = items[0].json;\n"
                        "return [{ json: { ...data, status: 'upload_pending' } }];"
                    )
                },
            },
        ],
        "connections": {
            "Webhook": {"main": [[{"node": "Prepare Data", "type": "main", "index": 0}]]},
            "Prepare Data": {"main": [[{"node": "Upload to YouTube", "type": "main", "index": 0}]]},
        },
        "active": False,
        "settings": {},
        "tags": ["ares", "youtube"],
    }


def notification_workflow(
    *,
    slack_webhook: str = "",
    email: str = "",
) -> dict[str, Any]:
    """Build a simple notification workflow."""
    return {
        "name": "ARES — Notifications",
        "nodes": [
            {
                "id": "node-webhook",
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 1,
                "position": [250, 300],
                "parameters": {
                    "httpMethod": "POST",
                    "path": "ares-notify",
                },
            },
            {
                "id": "node-switch",
                "name": "Route by Channel",
                "type": "n8n-nodes-base.switch",
                "typeVersion": 1,
                "position": [450, 300],
                "parameters": {
                    "dataType": "string",
                    "value1": "={{$json.channel}}",
                    "rules": {
                        "rules": [
                            {"value2": "slack", "output": 0},
                            {"value2": "email", "output": 1},
                        ]
                    },
                },
            },
        ],
        "connections": {
            "Webhook": {"main": [[{"node": "Route by Channel", "type": "main", "index": 0}]]},
        },
        "active": False,
        "settings": {},
        "tags": ["ares", "notifications"],
    }


# ---------------------------------------------------------------------------
# Workflow file management
# ---------------------------------------------------------------------------

def save_workflow_draft(name: str, workflow: dict[str, Any]) -> Path:
    """Save a workflow JSON draft to ~/.ares/n8n-workflows/."""
    paths = ares_paths()
    slug = name.lower().replace(" ", "-").replace("/", "-")[:60]
    path = paths["n8n_workflows"] / f"{slug}.json"
    with open(path, "w") as fh:
        json.dump(workflow, fh, indent=2)
    return path


def load_workflow_draft(name: str) -> dict[str, Any] | None:
    paths = ares_paths()
    slug = name.lower().replace(" ", "-")[:60]
    path = paths["n8n_workflows"] / f"{slug}.json"
    if not path.exists():
        return None
    with open(path) as fh:
        return json.load(fh)


def list_workflow_drafts() -> list[str]:
    paths = ares_paths()
    return [f.stem for f in paths["n8n_workflows"].glob("*.json")]


# ---------------------------------------------------------------------------
# High-level helpers
# ---------------------------------------------------------------------------

async def ensure_n8n_workflow(
    name: str,
    workflow: dict[str, Any],
    *,
    activate: bool = False,
    task_id: str | None = None,
) -> dict[str, Any]:
    """
    Ensure an n8n workflow exists. Creates it if it doesn't exist.
    Always saves a draft first — never activates without showing user.
    """
    # Save draft to disk first (always)
    draft_path = save_workflow_draft(name, workflow)
    await log(task_id=task_id, action="n8n_draft_saved", path=str(draft_path))

    client = N8NClient()
    if not await client.is_running():
        raise RuntimeError(
            f"n8n is not running at {client.base_url}. "
            "Start it with: n8n start"
        )

    # Check if workflow already exists
    existing = await client.list_workflows()
    for wf in existing:
        if wf.get("name") == name:
            await log(task_id=task_id, action="n8n_workflow_exists", id=wf.get("id"))
            return wf

    # Create the workflow (inactive by default)
    created = await client.create_workflow(workflow)

    if activate:
        # Activation requires explicit approval — caller must confirm
        await client.activate_workflow(created["id"])
        await log(task_id=task_id, action="n8n_workflow_active", id=created.get("id"))

    return created
