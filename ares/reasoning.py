"""Reasoning system for ARES — goal decomposition with the Contractor Test.

When ARES calls an LLM to plan work, it uses the Contractor Test system prompt
to ensure every output is a real file a human could open and continue from.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .llm import cloud, local
from .llm.router import route, LLMBackend
from .audit import log


# ---------------------------------------------------------------------------
# The Contractor Test system prompt
# ---------------------------------------------------------------------------

CONTRACTOR_TEST_SYSTEM = """You are the planning core of ARES — Autonomous Reasoning & Execution System.

When given a goal, produce a concrete step-by-step execution plan.

For each step specify:
1. The exact tool a professional human would use (name the real application)
2. What file or output it produces
3. The format of that output (so a human could open and edit it)
4. Whether this step requires human approval before proceeding
5. What ARES should do if this step fails

Rules:
- Do not suggest custom code where a real application already exists
- Do not invent file formats — use standard, widely-used formats only
- Every output must pass the Contractor Test: "Could a skilled freelance human
  pick up what ARES produced and continue the work — without special tools or instructions?"
- If you don't know the right tool for a stage, say so and flag for research

Output ONLY valid JSON in this exact structure:
{
  "goal": "<the goal>",
  "stages": [
    {
      "id": 1,
      "name": "<stage name>",
      "tool": "<exact tool name>",
      "action": "<what ARES does>",
      "output_file": "<filename>",
      "output_format": "<format description>",
      "requires_approval": true|false,
      "on_failure": "<what to do if this fails>",
      "new_install_required": false,
      "install_reason": ""
    }
  ],
  "new_installs": [
    {
      "tool": "<tool name>",
      "reason": "<one-line reason it's the right choice>",
      "install_method": "brew|npm|pip|manual",
      "install_command": "<command>"
    }
  ],
  "estimated_api_cost": "<e.g. ~$0.05 or 'none'>",
  "checkpoints": [<stage ids where ARES pauses for human review>]
}"""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PlanStage:
    id: int
    name: str
    tool: str
    action: str
    output_file: str
    output_format: str
    requires_approval: bool = False
    on_failure: str = "flag to user"
    new_install_required: bool = False
    install_reason: str = ""


@dataclass
class NewInstall:
    tool: str
    reason: str
    install_method: str = "brew"
    install_command: str = ""


@dataclass
class Plan:
    goal: str
    stages: list[PlanStage] = field(default_factory=list)
    new_installs: list[NewInstall] = field(default_factory=list)
    estimated_api_cost: str = "unknown"
    checkpoints: list[int] = field(default_factory=list)
    raw_json: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Reasoning call
# ---------------------------------------------------------------------------

async def reason(
    goal: str,
    *,
    task_id: str | None = None,
    context: str = "",
    backend: LLMBackend = LLMBackend.CLOUD,
) -> Plan:
    """Call LLM to decompose a goal into a concrete execution plan."""
    user_content = f"Goal: {goal}"
    if context:
        user_content += f"\n\nAdditional context:\n{context}"

    await log(task_id=task_id, action="reason_start", goal=goal[:80])

    messages = [{"role": "user", "content": user_content}]

    if backend == LLMBackend.LOCAL:
        raw_text = await local.complete(
            system=CONTRACTOR_TEST_SYSTEM,
            messages=messages,
            task_id=task_id,
        )
    else:
        raw_text = await cloud.complete(
            system=CONTRACTOR_TEST_SYSTEM,
            messages=messages,
            task_id=task_id,
        )

    plan = _parse_plan(goal, raw_text)
    await log(task_id=task_id, action="reason_done", stages=len(plan.stages))
    return plan


def _parse_plan(goal: str, raw_text: str) -> Plan:
    """Parse the LLM response into a Plan object."""
    # Extract JSON from response (may be wrapped in markdown fences)
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find raw JSON object
        brace_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        json_str = brace_match.group(0) if brace_match else "{}"

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        # Fallback: return a minimal plan
        return Plan(
            goal=goal,
            stages=[
                PlanStage(
                    id=1,
                    name="Manual review required",
                    tool="Human review",
                    action="LLM returned unparseable plan — review raw output",
                    output_file="plan_review.md",
                    output_format="Markdown",
                    requires_approval=True,
                    on_failure="Abort and ask user",
                )
            ],
            raw_json={"raw_text": raw_text[:500]},
        )

    stages = []
    for s in data.get("stages", []):
        stages.append(PlanStage(
            id=s.get("id", 0),
            name=s.get("name", ""),
            tool=s.get("tool", ""),
            action=s.get("action", ""),
            output_file=s.get("output_file", ""),
            output_format=s.get("output_format", ""),
            requires_approval=s.get("requires_approval", False),
            on_failure=s.get("on_failure", "flag to user"),
            new_install_required=s.get("new_install_required", False),
            install_reason=s.get("install_reason", ""),
        ))

    new_installs = []
    for ni in data.get("new_installs", []):
        new_installs.append(NewInstall(
            tool=ni.get("tool", ""),
            reason=ni.get("reason", ""),
            install_method=ni.get("install_method", "brew"),
            install_command=ni.get("install_command", ""),
        ))

    return Plan(
        goal=data.get("goal", goal),
        stages=stages,
        new_installs=new_installs,
        estimated_api_cost=data.get("estimated_api_cost", "unknown"),
        checkpoints=data.get("checkpoints", []),
        raw_json=data,
    )


# ---------------------------------------------------------------------------
# Proposal formatter
# ---------------------------------------------------------------------------

def format_proposal(plan: Plan) -> str:
    """Format a plan as a human-readable proposal."""
    lines = [
        f"Goal: {plan.goal}",
        "",
        "Proposed toolchain:",
    ]

    max_stage_len = max((len(s.name) for s in plan.stages), default=10)
    max_tool_len = max((len(s.tool) for s in plan.stages), default=10)

    for s in plan.stages:
        approval_tag = " [CHECKPOINT]" if s.requires_approval else ""
        line = (
            f"  Stage {s.id}  →  {s.tool:<{max_tool_len}}  "
            f"→  {s.output_file}  ({s.output_format}){approval_tag}"
        )
        lines.append(line)

    if plan.new_installs:
        lines.append("")
        lines.append("New installs required:")
        for ni in plan.new_installs:
            lines.append(f"  {ni.tool} — {ni.reason}")
            if ni.install_command:
                lines.append(f"    Install: {ni.install_command}")

    lines.append("")
    lines.append(f"Estimated API cost: {plan.estimated_api_cost}")
    lines.append("")
    lines.append("Approve? [yes / modify / I'll handle stage X myself]")

    return "\n".join(lines)
