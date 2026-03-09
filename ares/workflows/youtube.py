"""YouTube production pipeline for ARES.

Stage 0: Idea & Brief     → Conversation + Notion/Docs   → brief.md (Markdown)
Stage 1: Research         → Perplexity / browser         → research.md (Markdown)
Stage 2: Script           → Claude draft → Google Docs   → Google Doc (editable)
Stage 3: Voice            → ElevenLabs (cloned voice)    → voice_final.wav (WAV)
Stage 4: Video            → DaVinci Resolve              → project.drp + export.mp4
Stage 5: Thumbnail        → Canva or Figma (browser)     → thumbnail.png (1280×720)
Stage 6: Publish          → n8n workflow → YouTube Studio → live YouTube URL

Checkpoints (ARES pauses and waits):
- After brief — before research
- After script draft — before voice (user may want to edit)
- After voice — before video (confirm quality)
- After video export — before thumbnail and publish
- After thumbnail — hard gate before publish (always)
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..config import get_config, ares_paths
from ..audit import log
from ..llm import cloud
from ..memory import write_project, read_project
from ..tools.n8n import N8NClient, youtube_publish_workflow, save_workflow_draft


# ---------------------------------------------------------------------------
# Project state
# ---------------------------------------------------------------------------

@dataclass
class YouTubeProject:
    id: str
    topic: str
    channel: str = ""
    target_length_minutes: int = 10

    # Stage outputs
    brief_path: str = ""
    research_path: str = ""
    script_path: str = ""
    script_google_doc_url: str = ""
    voice_path: str = ""
    video_project_path: str = ""
    video_export_path: str = ""
    thumbnail_path: str = ""
    youtube_url: str = ""

    # State
    current_stage: int = 0
    status: str = "new"  # new | brief | research | script | voice | video | thumbnail | published
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def output_dir(self) -> Path:
        return Path.home() / "Documents" / "ARES" / "YouTube" / self.id

    def save(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
        write_project(f"yt-{self.id}", {
            "type": "youtube",
            "id": self.id,
            "topic": self.topic,
            "channel": self.channel,
            "target_length_minutes": self.target_length_minutes,
            "brief_path": self.brief_path,
            "research_path": self.research_path,
            "script_path": self.script_path,
            "script_google_doc_url": self.script_google_doc_url,
            "voice_path": self.voice_path,
            "video_project_path": self.video_project_path,
            "video_export_path": self.video_export_path,
            "thumbnail_path": self.thumbnail_path,
            "youtube_url": self.youtube_url,
            "current_stage": self.current_stage,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })


def load_yt_project(project_id: str) -> YouTubeProject | None:
    data = read_project(f"yt-{project_id}")
    if not data:
        return None
    return YouTubeProject(
        id=data.get("id", project_id),
        topic=data.get("topic", ""),
        channel=data.get("channel", ""),
        target_length_minutes=data.get("target_length_minutes", 10),
        brief_path=data.get("brief_path", ""),
        research_path=data.get("research_path", ""),
        script_path=data.get("script_path", ""),
        script_google_doc_url=data.get("script_google_doc_url", ""),
        voice_path=data.get("voice_path", ""),
        video_project_path=data.get("video_project_path", ""),
        video_export_path=data.get("video_export_path", ""),
        thumbnail_path=data.get("thumbnail_path", ""),
        youtube_url=data.get("youtube_url", ""),
        current_stage=data.get("current_stage", 0),
        status=data.get("status", "new"),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
    )


# ---------------------------------------------------------------------------
# Stage 0: Brief
# ---------------------------------------------------------------------------

async def stage_brief(project: YouTubeProject, *, task_id: str | None = None) -> Path:
    """Generate a project brief from the topic."""
    await log(task_id=task_id, stage="brief", action="start", topic=project.topic[:60])

    system = """You are a YouTube production strategist.
Create a concise video brief for the given topic.

Format as Markdown with sections:
# [Title idea]

## Core Premise
One paragraph: what is this video and why does it matter?

## Target Audience
Who specifically is this for?

## Key Points (3-5)
-
-

## Unique Angle
What makes this video different from others on this topic?

## Tone & Style
e.g. educational, conversational, fast-paced, cinematic

## Research Questions (3-5 things to verify)
-

## Estimated Length
X minutes

Keep it tight. This brief is the contract for the whole production."""

    brief_text = await cloud.complete(
        system=system,
        messages=[{"role": "user", "content": f"Create a video brief for: {project.topic}"}],
        task_id=task_id,
    )

    output_dir = project.output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    brief_path = output_dir / "brief.md"
    brief_path.write_text(brief_text)

    project.brief_path = str(brief_path)
    project.current_stage = 0
    project.status = "brief"
    project.save()

    await log(task_id=task_id, stage="brief", action="file_write", path=str(brief_path))
    return brief_path


# ---------------------------------------------------------------------------
# Stage 1: Research
# ---------------------------------------------------------------------------

async def stage_research(
    project: YouTubeProject,
    *,
    task_id: str | None = None,
    web_search: bool = False,
) -> Path:
    """Compile research notes for the video."""
    await log(task_id=task_id, stage="research", action="start")

    brief = ""
    if project.brief_path and Path(project.brief_path).exists():
        brief = Path(project.brief_path).read_text()

    system = """You are a research assistant for YouTube video production.
Given a video brief, compile thorough research notes.

Format as Markdown with sections:
# Research: [Topic]

## Key Facts & Statistics
(cite sources inline as [Source Name])

## Expert Perspectives
Notable quotes or viewpoints on this topic

## Common Misconceptions
What people get wrong

## Story Angles & Examples
Concrete examples and stories that could illustrate points

## Gaps & Uncertainties
Things that need verification or where sources disagree

## Sources to Cite
- [Source 1]: brief description
- [Source 2]: brief description

Flag anything you're uncertain about with [VERIFY]."""

    content = f"Video topic: {project.topic}\n\nBrief:\n{brief}" if brief else f"Video topic: {project.topic}"

    research_text = await cloud.complete(
        system=system,
        messages=[{"role": "user", "content": content}],
        task_id=task_id,
        max_tokens=6000,
    )

    output_dir = project.output_dir()
    research_path = output_dir / "research.md"
    research_path.write_text(research_text)

    project.research_path = str(research_path)
    project.current_stage = 1
    project.status = "research"
    project.save()

    await log(task_id=task_id, stage="research", action="file_write", path=str(research_path))
    return research_path


# ---------------------------------------------------------------------------
# Stage 2: Script
# ---------------------------------------------------------------------------

async def stage_script(
    project: YouTubeProject,
    *,
    task_id: str | None = None,
    word_count: int = 1500,
) -> Path:
    """Draft the video script."""
    await log(task_id=task_id, stage="script", action="start")

    brief = ""
    research = ""
    if project.brief_path and Path(project.brief_path).exists():
        brief = Path(project.brief_path).read_text()
    if project.research_path and Path(project.research_path).exists():
        research = Path(project.research_path).read_text()

    system = f"""You are a YouTube scriptwriter. Write scripts that are:
- Conversational and direct — written for the ear, not the eye
- Structured but natural — no stiff academic tone
- Engaging from the first line — hooks immediately
- Built for a {project.target_length_minutes}-minute video (~{word_count} words)

Format:
[HOOK] - Opening 30 seconds
[INTRO] - Brief setup (30-60 sec)
[SECTION 1: Name] - Main content
[SECTION 2: Name]
[SECTION 3: Name]
[CTA] - Call to action (final 30 sec)

Use stage directions sparingly: (pause), (show graph), (cut to B-roll: ...)
Yellow highlight [FACT CHECK] anything uncertain."""

    content_parts = [f"Topic: {project.topic}"]
    if brief:
        content_parts.append(f"\nBrief:\n{brief}")
    if research:
        content_parts.append(f"\nResearch:\n{research[:3000]}")  # Limit context

    script_text = await cloud.complete(
        system=system,
        messages=[{"role": "user", "content": "\n\n".join(content_parts)}],
        task_id=task_id,
        max_tokens=8000,
    )

    output_dir = project.output_dir()
    script_path = output_dir / "script.md"
    script_path.write_text(script_text)

    # Word count estimate
    word_count_actual = len(script_text.split())
    minutes_estimate = round(word_count_actual / 150, 1)

    project.script_path = str(script_path)
    project.current_stage = 2
    project.status = "script"
    project.save()

    await log(
        task_id=task_id,
        stage="script",
        action="file_write",
        path=str(script_path),
        words=word_count_actual,
        minutes=minutes_estimate,
    )
    return script_path


# ---------------------------------------------------------------------------
# Stage 3: Voice (ElevenLabs)
# ---------------------------------------------------------------------------

ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1"


async def stage_voice(
    project: YouTubeProject,
    *,
    task_id: str | None = None,
    voice_id: str = "",
    model_id: str = "eleven_multilingual_v2",
) -> Path:
    """Generate voiceover using ElevenLabs."""
    await log(task_id=task_id, stage="voice", action="start")

    if not project.script_path or not Path(project.script_path).exists():
        raise FileNotFoundError("Script not found. Run stage_script first.")

    script_text = Path(project.script_path).read_text()

    # Strip stage directions for voice synthesis
    import re
    clean_text = re.sub(r"\[.*?\]", "", script_text)
    clean_text = re.sub(r"\(.*?\)", "", clean_text)
    clean_text = re.sub(r"\n{3,}", "\n\n", clean_text).strip()

    cfg = get_config()
    api_key = getattr(cfg, "elevenlabs", None)
    if hasattr(cfg, "elevenlabs"):
        api_key = cfg.elevenlabs.api_key if hasattr(cfg.elevenlabs, "api_key") else ""
    else:
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")

    if not api_key:
        # Create a placeholder file so the pipeline can continue
        output_dir = project.output_dir()
        voice_path = output_dir / "voice_final.wav"
        voice_path.write_text(
            "[PLACEHOLDER — ElevenLabs API key not configured]\n"
            f"Script ({len(clean_text.split())} words ready for synthesis)"
        )
        project.voice_path = str(voice_path)
        project.save()
        await log(task_id=task_id, stage="voice", action="placeholder", reason="no_api_key")
        return voice_path

    if not voice_id:
        raise ValueError(
            "voice_id required for ElevenLabs synthesis. "
            "Get your voice ID from elevenlabs.io/app/voice-lab"
        )

    output_dir = project.output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    voice_path = output_dir / "voice_final.mp3"

    # ElevenLabs TTS call
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    payload = {
        "text": clean_text,
        "model_id": model_id,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{ELEVENLABS_API_URL}/text-to-speech/{voice_id}",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        voice_path.write_bytes(response.content)

    project.voice_path = str(voice_path)
    project.current_stage = 3
    project.status = "voice"
    project.save()

    size_mb = voice_path.stat().st_size / 1_048_576
    await log(
        task_id=task_id,
        stage="voice",
        action="file_write",
        path=str(voice_path),
        size_mb=f"{size_mb:.1f}",
    )
    return voice_path


# ---------------------------------------------------------------------------
# Stage 4: Video — DaVinci Resolve project stub
# ---------------------------------------------------------------------------

def stage_video_project(project: YouTubeProject, *, task_id: str | None = None) -> Path:
    """Create a DaVinci Resolve project stub with notes."""
    output_dir = project.output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create a project notes file that opens in DaVinci
    notes_path = output_dir / "video_production_notes.md"
    notes = f"""# Video Production: {project.topic}

## Assets
- Script: {project.script_path or 'see script.md'}
- Voice: {project.voice_path or 'pending ElevenLabs synthesis'}

## DaVinci Resolve Project
File: {output_dir}/project.drp (create new project in Resolve)
Timeline: 16:9, 1080p60 or 4K30 (match your camera)

## Structure
1. **Hook** (0:00-0:30) — Grabbing opener, no title card yet
2. **Intro + Title** (0:30-1:00) — Introduce yourself, topic, value
3. **Main Content** (1:00-{project.target_length_minutes - 1}:00)
   - Follow script sections
   - B-roll on all stats and claims
   - Cut to talking head on analysis
4. **CTA** ({project.target_length_minutes - 1}:00-end)

## B-roll Notes
- [Mark in script where B-roll is needed]
- Sources: Pexels, Unsplash, Storyblocks, own footage

## Export Settings
Format: H.264 (YouTube) or H.265
Resolution: Match source
Bitrate: 50Mbps+
File: export.mp4
"""
    notes_path.write_text(notes)

    # Create a placeholder .drp reference
    drp_ref_path = output_dir / "project_drp_instructions.md"
    drp_ref_path.write_text(
        f"# DaVinci Resolve Project\n\n"
        f"1. Open DaVinci Resolve\n"
        f"2. File → New Project → Name: '{project.topic[:40]}'\n"
        f"3. Import voice file: {project.voice_path or 'voice_final.wav'}\n"
        f"4. Import your footage\n"
        f"5. Follow: {notes_path}\n"
        f"6. Export as: {output_dir}/export.mp4\n"
    )

    project.video_project_path = str(output_dir)
    project.current_stage = 4
    project.status = "video"
    project.save()

    log_sync = lambda **kw: None  # Use sync log for non-async context
    return notes_path


# ---------------------------------------------------------------------------
# Stage 5: Thumbnail
# ---------------------------------------------------------------------------

async def stage_thumbnail_brief(
    project: YouTubeProject,
    *,
    task_id: str | None = None,
) -> Path:
    """Generate a thumbnail design brief for Canva or Figma."""
    await log(task_id=task_id, stage="thumbnail", action="start")

    brief_text = ""
    if project.brief_path and Path(project.brief_path).exists():
        brief_text = Path(project.brief_path).read_text()

    system = """You are a YouTube thumbnail designer.
Create a thumbnail design brief that a designer can execute in Canva or Figma.

Format:
# Thumbnail Brief: [Title]

## Concept
One sentence: what this thumbnail communicates at a glance

## Text (3-5 words max — what goes on the thumbnail)
LARGE TEXT:
SECONDARY TEXT (optional):

## Visual Elements
- Foreground:
- Background:
- Color scheme (hex codes):
- Face/person: yes/no (for face-forward thumbnails)

## Style Reference
e.g. "Bold MrBeast style" / "Clean professional tech" / "Dramatic cinematic"

## Canva Template Suggestion
Start with: [template type]

## Size
1280 × 720px (YouTube standard)

Keep it punchy. Thumbnails compete at 200px wide on mobile."""

    brief = await cloud.complete(
        system=system,
        messages=[{
            "role": "user",
            "content": f"Topic: {project.topic}\n\nVideo brief:\n{brief_text[:1000]}"
        }],
        task_id=task_id,
    )

    output_dir = project.output_dir()
    thumb_brief_path = output_dir / "thumbnail_brief.md"
    thumb_brief_path.write_text(brief)

    # Create Canva instructions
    canva_path = output_dir / "thumbnail_canva_instructions.md"
    canva_path.write_text(
        f"# Thumbnail — Canva Instructions\n\n"
        f"1. Go to canva.com\n"
        f"2. Search 'YouTube Thumbnail' → 1280×720\n"
        f"3. Follow this brief: {thumb_brief_path}\n"
        f"4. Export as PNG: {output_dir}/thumbnail.png\n\n"
        f"---\n\n{brief}"
    )

    project.current_stage = 5
    project.status = "thumbnail"
    project.save()

    await log(task_id=task_id, stage="thumbnail", action="brief_written", path=str(thumb_brief_path))
    return thumb_brief_path


# ---------------------------------------------------------------------------
# Stage 6: Publish via n8n
# ---------------------------------------------------------------------------

async def stage_publish(
    project: YouTubeProject,
    *,
    task_id: str | None = None,
    title: str = "",
    description: str = "",
    tags: list[str] | None = None,
) -> str:
    """Prepare and trigger YouTube publish via n8n workflow."""
    await log(task_id=task_id, stage="publish", action="start")

    if not title:
        title = project.topic

    # Build and save n8n workflow draft
    workflow = youtube_publish_workflow(
        title=title,
        description=description or f"Auto-generated description for: {title}",
        video_path=project.video_export_path or f"{project.output_dir()}/export.mp4",
        thumbnail_path=project.thumbnail_path or f"{project.output_dir()}/thumbnail.png",
    )
    draft_path = save_workflow_draft(f"yt-publish-{project.id}", workflow)

    await log(
        task_id=task_id,
        stage="publish",
        action="workflow_draft_saved",
        path=str(draft_path),
    )

    # Try n8n
    client = N8NClient()
    if await client.is_running():
        # Create workflow (inactive — user must activate)
        try:
            created = await client.create_workflow(workflow)
            workflow_url = f"{client.base_url}/workflow/{created.get('id', '')}"
            await log(
                task_id=task_id,
                stage="publish",
                action="n8n_workflow_created",
                url=workflow_url,
            )
            return (
                f"Publish workflow created in n8n (inactive).\n"
                f"Review and activate: {workflow_url}\n"
                f"Draft saved: {draft_path}"
            )
        except Exception as exc:
            await log(task_id=task_id, stage="publish", action="n8n_error", error=str(exc))

    return (
        f"n8n not running. Publish workflow draft saved:\n{draft_path}\n\n"
        f"When ready:\n"
        f"1. Start n8n: n8n start\n"
        f"2. Import: {draft_path}\n"
        f"3. Add YouTube OAuth credentials\n"
        f"4. Activate and trigger"
    )


# ---------------------------------------------------------------------------
# Full pipeline runner
# ---------------------------------------------------------------------------

async def run_pipeline(
    topic: str,
    *,
    task_id: str | None = None,
    channel: str = "",
    target_length: int = 10,
    approval_cb=None,
) -> YouTubeProject:
    """Run the full YouTube production pipeline with checkpoints."""
    project_id = uuid.uuid4().hex[:8]
    project = YouTubeProject(
        id=project_id,
        topic=topic,
        channel=channel,
        target_length_minutes=target_length,
    )
    project.save()

    await log(task_id=task_id, action="yt_pipeline_start", topic=topic[:60], project_id=project_id)

    async def checkpoint(stage_name: str, files: list[str]) -> bool:
        """Show checkpoint and wait for approval."""
        msg = (
            f"\n{'='*60}\n"
            f"[CHECKPOINT] After: {stage_name}\n"
            f"Files ready:\n" +
            "\n".join(f"  → {f}" for f in files) +
            f"\n{'='*60}\n"
            f"Continue to next stage? [y/n]: "
        )
        print(msg, end="", flush=True)

        if approval_cb:
            return await approval_cb(stage_name)

        import asyncio
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(None, input)
        return answer.strip().lower() in ("y", "yes", "")

    # Stage 0: Brief
    print(f"\n[Stage 0] Generating brief for: {topic}")
    brief_path = await stage_brief(project, task_id=task_id)
    print(f"Brief: {brief_path}")
    if not await checkpoint("Brief", [str(brief_path)]):
        return project

    # Stage 1: Research
    print(f"\n[Stage 1] Compiling research...")
    research_path = await stage_research(project, task_id=task_id)
    print(f"Research: {research_path}")

    # Stage 2: Script
    print(f"\n[Stage 2] Drafting script...")
    script_path = await stage_script(project, task_id=task_id)
    word_count = len(Path(str(script_path)).read_text().split())
    minutes = round(word_count / 150, 1)
    print(f"Script: {script_path}")
    print(f"  {word_count} words, ~{minutes} min")
    if not await checkpoint("Script", [str(script_path)]):
        return project

    # Stage 3: Voice
    print(f"\n[Stage 3] Voice synthesis (ElevenLabs)...")
    print("  [Run 'ares setup' to configure ElevenLabs voice_id]")
    voice_path = await stage_voice(project, task_id=task_id)
    print(f"Voice: {voice_path}")
    if not await checkpoint("Voice", [str(voice_path)]):
        return project

    # Stage 4: Video notes
    print(f"\n[Stage 4] Creating DaVinci Resolve production notes...")
    video_notes = stage_video_project(project, task_id=task_id)
    print(f"Video notes: {video_notes}")
    if not await checkpoint("Video export", [str(video_notes)]):
        return project

    # Stage 5: Thumbnail brief
    print(f"\n[Stage 5] Writing thumbnail brief (Canva/Figma)...")
    thumb_path = await stage_thumbnail_brief(project, task_id=task_id)
    print(f"Thumbnail brief: {thumb_path}")
    if not await checkpoint("Thumbnail", [str(thumb_path)]):
        return project

    # Stage 6: Publish
    print(f"\n[Stage 6] Preparing publish workflow (n8n)...")
    print("  [Hard gate — requires explicit approval before anything goes public]")
    print("  Ready to prepare publish workflow? [y/n]: ", end="", flush=True)
    import asyncio
    loop = asyncio.get_event_loop()
    answer = await loop.run_in_executor(None, input)
    if answer.strip().lower() not in ("y", "yes"):
        print("  Publish skipped. Run 'ares goal \"publish YouTube video <id>\"' when ready.")
        return project

    result = await stage_publish(project, task_id=task_id, title=topic)
    print(f"\n{result}")

    project.status = "published"
    project.save()

    await log(task_id=task_id, action="yt_pipeline_done", project_id=project_id)
    return project
