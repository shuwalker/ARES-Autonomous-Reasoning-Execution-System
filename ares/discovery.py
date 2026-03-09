"""Discovery conversation — first-run onboarding for ARES.

Before entering any new domain of work, ARES runs a discovery conversation
to understand what the user already has and how they like to work.

ARES builds around what exists, not over it.
"""

from __future__ import annotations

import asyncio
import tomli_w
from pathlib import Path
from typing import Any

from .config import ares_paths, get_config, write_default_config
from .memory import write_preference, append_preference_note
from .tools.registry import ensure_builtin_tools, load_registry, mark_installed


# ---------------------------------------------------------------------------
# Domain discovery questions
# ---------------------------------------------------------------------------

YOUTUBE_QUESTIONS = [
    ("video_editor", "What do you currently use for video editing?",
     ["DaVinci Resolve", "Final Cut Pro", "Premiere Pro", "None yet"]),
    ("audio_tool", "How do you handle voiceover / narration?",
     ["ElevenLabs (AI)", "I record it myself", "Hired voice talent", "No voiceover yet"]),
    ("project_storage", "Where do you store video project files?",
     ["~/Documents/YouTube", "iCloud Drive", "External drive", "Dropbox / Google Drive"]),
    ("thumbnail_tool", "What do you use for thumbnails?",
     ["Canva", "Figma", "Photoshop", "Nothing consistent yet"]),
    ("involvement", "How involved do you want to be in the production process?",
     ["Review every stage", "Review script + final video only", "Mostly hands-off, flag issues"]),
    ("channel_status", "What's your YouTube channel status?",
     ["Active channel, regular uploads", "Starting fresh", "Dormant, want to restart"]),
]

GENERAL_QUESTIONS = [
    ("google_account", "Do you have a Google account for Drive / Docs?",
     ["Yes, using it", "Yes but rarely", "No"]),
    ("notion_user", "Do you use Notion for notes / planning?",
     ["Yes, actively", "Have an account, don't use it much", "No"]),
    ("n8n_status", "Is n8n installed or have you used it before?",
     ["Running locally", "Used before, not running", "New to n8n"]),
]


# ---------------------------------------------------------------------------
# Interactive conversation
# ---------------------------------------------------------------------------

async def _ask(question: str, options: list[str], allow_free: bool = True) -> str:
    """Ask the user a question with numbered options."""
    print(f"\n{question}")
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    if allow_free:
        print(f"  {len(options) + 1}. Other (type your answer)")

    while True:
        raw = await _input_async("→ ")
        raw = raw.strip()
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(options):
                return options[n - 1]
            elif allow_free and n == len(options) + 1:
                return await _input_async("Your answer: ")
        elif raw:
            return raw
        print("  Please enter a number or type your answer.")


async def _input_async(prompt: str = "") -> str:
    """Read a line from stdin asynchronously."""
    loop = asyncio.get_event_loop()
    if prompt:
        print(prompt, end="", flush=True)
    return await loop.run_in_executor(None, input)


# ---------------------------------------------------------------------------
# Discovery flows
# ---------------------------------------------------------------------------

async def run_discovery() -> None:
    """Run the full first-time discovery conversation."""
    write_default_config()
    ensure_builtin_tools()

    print("\n" + "=" * 60)
    print("  ARES — First-Time Setup")
    print("=" * 60)
    print("""
Before I set anything up, I want to understand what you already
have and how you like to work. I'll build around what you have,
not over it.

This takes about 2 minutes.
""")

    prefs: dict[str, Any] = {}

    # General questions
    print("\n── General Setup ──────────────────────────────────────────")
    for key, question, options in GENERAL_QUESTIONS:
        answer = await _ask(question, options)
        prefs[key] = answer
        write_preference(key, answer)

    # YouTube questions
    print("\n── YouTube Production ─────────────────────────────────────")
    for key, question, options in YOUTUBE_QUESTIONS:
        answer = await _ask(question, options)
        prefs[key] = answer
        write_preference(key, answer)

    # API keys
    print("\n── API Keys ────────────────────────────────────────────────")
    print("\nI need a few API keys to work fully. These will be stored")
    print("in your config file (~/.ares/config/ares.toml).\n")

    import os
    import tomllib

    cfg_path = ares_paths()["config"] / "ares.toml"
    cfg_data: dict[str, Any] = {}
    if cfg_path.exists():
        with open(cfg_path, "rb") as fh:
            cfg_data = tomllib.load(fh)

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        anthropic_key = (await _input_async(
            "Anthropic API key (for cloud reasoning, leave blank to skip): "
        )).strip()

    elevenlabs_key = (await _input_async(
        "ElevenLabs API key (for voice synthesis, leave blank to skip): "
    )).strip()

    n8n_key = (await _input_async(
        "n8n API key (if running locally with auth, leave blank to skip): "
    )).strip()

    # Write config
    cfg_data.setdefault("llm", {})["cloud_api_key"] = anthropic_key
    cfg_data.setdefault("elevenlabs", {})["api_key"] = elevenlabs_key
    cfg_data.setdefault("n8n", {})["api_key"] = n8n_key

    with open(cfg_path, "wb") as fh:
        tomli_w.dump(cfg_data, fh)

    # Check what tools are already installed
    print("\n── Checking installed tools ────────────────────────────────")
    from .tools.registry import probe_all_tools
    tool_status = probe_all_tools()
    registry = load_registry()

    installed = [k for k, v in tool_status.items() if v]
    missing = [k for k, v in tool_status.items() if not v]

    if installed:
        print(f"Found: {', '.join(installed)}")
    if missing:
        print(f"Not detected: {', '.join(missing)}")
        print("(Run 'ares tools install <name>' to install any of these)")

    # Write summary note
    summary_lines = [
        "## Discovery Summary",
        "",
        "**General:**",
    ]
    for key, question, _ in GENERAL_QUESTIONS:
        summary_lines.append(f"- {question}: {prefs.get(key, '—')}")
    summary_lines.append("")
    summary_lines.append("**YouTube:**")
    for key, question, _ in YOUTUBE_QUESTIONS:
        summary_lines.append(f"- {question}: {prefs.get(key, '—')}")

    append_preference_note("\n".join(summary_lines))

    print("\n" + "=" * 60)
    print("  Setup complete.")
    print("=" * 60)
    print(f"""
Your preferences are saved at:
  {ares_paths()['memory_preferences']}/profile.toml

Next steps:
  • Run 'ares start' to launch the daemon
  • Run 'ares goal "make a YouTube video about X"' to give ARES work
  • Run 'ares tools list' to see the tool registry

I'll build around your existing tools. Let me know when you're ready.
""")


async def run_domain_discovery(domain: str) -> None:
    """Run discovery for a specific domain (e.g., 'youtube', 'podcast')."""
    print(f"\nBefore I set anything up for {domain}, I want to understand")
    print("what you already have and how you like to work.\n")

    domain_questions: dict[str, list[tuple[str, str, list[str]]]] = {
        "youtube": [(k, q, o) for k, q, o in YOUTUBE_QUESTIONS],
        "podcast": [
            ("podcast_daw", "What DAW do you use for audio?",
             ["GarageBand", "Logic Pro", "Audacity", "Adobe Audition", "None yet"]),
            ("podcast_host", "Where do you host your podcast?",
             ["Spotify for Podcasters", "Buzzsprout", "Podbean", "Not set up yet"]),
        ],
    }

    questions = domain_questions.get(domain.lower(), [])
    if not questions:
        print(f"No specific questions for domain '{domain}'. Using general discovery.")
        await run_discovery()
        return

    prefs: dict[str, Any] = {}
    for key, question, options in questions:
        answer = await _ask(question, options)
        prefs[key] = answer
        write_preference(f"{domain}_{key}", answer)

    print(f"\nGot it. I'll tailor the {domain} workflow to what you have.")
    note = f"## {domain.title()} Domain Discovery\n\n"
    for key, question, _ in questions:
        note += f"- {question}: {prefs.get(key, '—')}\n"
    append_preference_note(note)
