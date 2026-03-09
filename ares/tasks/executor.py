"""Task executor for ARES.

Executes plan stages using real tools. Each stage type has a handler.
Handles checkpoints, approvals, and failures.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from ..audit import log
from ..reasoning import Plan, PlanStage
from .queue import Task, update_task


# ---------------------------------------------------------------------------
# Checkpoint / approval protocol
# ---------------------------------------------------------------------------

ApprovalCallback = Callable[[str], Awaitable[bool]]


async def _default_approval(message: str) -> bool:
    """Default: print message and wait for input (blocks — for interactive use)."""
    print(f"\n[CHECKPOINT] {message}")
    print("Continue? [y/n]: ", end="", flush=True)
    loop = asyncio.get_event_loop()
    answer = await loop.run_in_executor(None, input)
    return answer.strip().lower() in ("y", "yes", "")


# ---------------------------------------------------------------------------
# Stage handlers
# ---------------------------------------------------------------------------

async def _execute_shell(stage: PlanStage, task: Task) -> str:
    """Execute a shell command stage."""
    import subprocess
    cmd = stage.action
    if not cmd:
        return f"Stage {stage.id} has no action command."

    await log(task_id=task.id, stage=stage.name, action="shell_exec", cmd=cmd[:80])

    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"Stage {stage.id} failed (exit {proc.returncode}):\n{stderr.decode()}"
        )
    return stdout.decode()


async def _execute_llm_stage(stage: PlanStage, task: Task) -> str:
    """Stage that calls the LLM to produce content."""
    from ..llm import cloud
    text = await cloud.complete(
        system="You are ARES, producing professional output for a contractor workflow.",
        messages=[{"role": "user", "content": f"Execute stage: {stage.action}"}],
        task_id=task.id,
    )
    if stage.output_file:
        from pathlib import Path
        import os
        output_dir = Path.home() / "Documents" / "ARES" / task.id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / stage.output_file
        output_path.write_text(text)
        await log(
            task_id=task.id,
            stage=stage.name,
            action="file_write",
            path=str(output_path),
        )
    return text


async def _execute_checkpoint(stage: PlanStage, task: Task) -> str:
    """Stage that waits for human approval."""
    await log(
        task_id=task.id,
        stage=stage.name,
        action="checkpoint",
        message=f"Waiting for approval at stage {stage.id}: {stage.name}",
    )
    return "checkpoint_reached"


# ---------------------------------------------------------------------------
# Main executor
# ---------------------------------------------------------------------------

class PlanExecutor:
    def __init__(
        self,
        approval_cb: ApprovalCallback | None = None,
        paused_event: asyncio.Event | None = None,
    ) -> None:
        self.approval_cb = approval_cb or _default_approval
        self.paused_event = paused_event or asyncio.Event()
        self.paused_event.set()  # Not paused by default

    async def execute(self, task: Task, plan: Plan) -> str:
        """Execute all stages of a plan. Returns final result."""
        task.status = "executing"
        task.started_at = datetime.now(timezone.utc).isoformat()
        task.plan_json = plan.raw_json
        update_task(task)

        await log(task_id=task.id, action="execute_start", stages=len(plan.stages))

        results = []

        for stage in plan.stages:
            # Wait if paused (user took over)
            await self.paused_event.wait()

            task.current_stage = stage.id
            update_task(task)

            await log(
                task_id=task.id,
                stage=stage.name,
                action="stage_start",
                tool=stage.tool,
            )

            # Checkpoint gate
            if stage.requires_approval or stage.id in plan.checkpoints:
                task.status = "paused"
                update_task(task)

                approved = await self.approval_cb(
                    f"Stage {stage.id}: {stage.name}\n"
                    f"  Tool: {stage.tool}\n"
                    f"  Action: {stage.action}\n"
                    f"  Output: {stage.output_file} ({stage.output_format})"
                )
                if not approved:
                    task.status = "paused"
                    update_task(task)
                    return f"Paused at stage {stage.id} — user declined."

                task.status = "executing"
                update_task(task)

            # Execute
            try:
                result = await self._run_stage(stage, task)
                results.append(f"Stage {stage.id} ({stage.name}): {str(result)[:200]}")
                await log(
                    task_id=task.id,
                    stage=stage.name,
                    action="stage_done",
                )
            except Exception as exc:
                await log(
                    task_id=task.id,
                    stage=stage.name,
                    action="stage_failed",
                    error=str(exc)[:200],
                )
                task.error = str(exc)[:500]
                task.status = "failed"
                update_task(task)
                return f"Failed at stage {stage.id}: {exc}"

        task.status = "done"
        task.completed_at = datetime.now(timezone.utc).isoformat()
        task.result = "\n".join(results)
        update_task(task)

        await log(task_id=task.id, action="execute_done", stages_completed=len(plan.stages))
        return task.result

    async def _run_stage(self, stage: PlanStage, task: Task) -> str:
        """Route stage to appropriate handler based on tool/action."""
        tool_lower = stage.tool.lower()
        action_lower = stage.action.lower()

        # LLM-based content creation stages
        if any(kw in tool_lower for kw in ("claude", "gpt", "llm", "ai")):
            return await _execute_llm_stage(stage, task)

        # Shell command stages
        if action_lower.startswith("run:") or action_lower.startswith("exec:"):
            stage_copy = PlanStage(**{
                **stage.__dict__,
                "action": stage.action.split(":", 1)[1].strip(),
            })
            return await _execute_shell(stage_copy, task)

        # Human stage — just log it
        if any(kw in tool_lower for kw in ("human", "manual", "user")):
            return f"Manual stage — awaiting human: {stage.action}"

        # Default: treat as LLM content generation
        return await _execute_llm_stage(stage, task)

    def pause(self) -> None:
        """Pause execution (user is taking over)."""
        self.paused_event.clear()

    def resume(self) -> None:
        """Resume execution."""
        self.paused_event.set()
