# ARES — Autonomous Reasoning & Execution System

ARES is a local AI assistant and persistent background operator. It runs as a macOS daemon on a Mac Studio (primary) and syncs state to a MacBook (secondary) via iCloud Drive.

**ARES is not a chatbot, not a pipeline framework, and not a code generator.** It is an autonomous operator that uses real tools the same way a skilled human contractor would — producing files you can open, edit, and hand to another person without any special instructions.

---

## The Core Standard

Every decision about tooling and output format passes this test:

> *"Could a skilled freelance human pick up what ARES produced and continue the work — without special tools or instructions?"*

- Scripts → Google Docs / Markdown (not custom formats)
- Video projects → DaVinci Resolve (`.drp`), not hidden ffmpeg pipelines
- Workflows → n8n (`localhost:5678`), visible and editable
- Audio → standard WAV/MP3
- Research → Markdown files, readable anywhere
- Memory → plain TOML and JSONL, openable in any text editor

---

## Installation

```bash
# Clone and install
git clone <repo>
cd ARES-Autonomous-Reasoning-Execution-System
bash install.sh
```

Or manually:
```bash
pip install -e .
ares init
```

**Requirements:** Python 3.11+, macOS (for full feature set)

---

## Quick Start

```bash
# 1. Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# 2. First-time setup (discovery conversation)
ares setup

# 3. Start the daemon
ares start

# 4. Give ARES a goal
ares goal "make a YouTube video about the history of the internet"

# 5. Check status
ares status
```

---

## CLI Reference

```
ares start               Launch daemon (--register-launchd to register as launchd service)
ares stop                Graceful shutdown
ares goal "…"            Give ARES a high-level goal
ares status              What is ARES currently doing
ares tools               Manage the tool registry
ares tools list          List all registered tools (--probe to check installs)
ares tools install [x]   Propose and install a tool
ares tools add           Add a new tool to the registry
ares memory show         Browse memory summary
ares memory path         Show memory directory path
ares log                 Tail the audit log (-f to follow, -n for line count)
ares pause               Pause current task (I'm taking over)
ares resume              Resume after manual takeover
ares setup               Run first-time discovery conversation
ares init                Initialize directories and default config
ares version             Show version
```

---

## File Layout

```
~/.ares/
├── config/ares.toml              Main config, human-editable
├── memory/
│   ├── episodic/                 JSONL task logs with outcomes
│   ├── preferences/              How user likes things done (Markdown + TOML)
│   ├── tools/registry.toml       Tool registry — installed tools and quirks
│   ├── knowledge/                Research notes (Markdown)
│   └── projects/                 Per-project context and state (TOML)
├── tasks/
│   ├── queue.jsonl               Active task queue
│   └── archive.jsonl             Completed tasks
├── n8n-workflows/                Exported n8n workflow JSON (version-controlled)
├── logs/exec.log                 Full audit log — every action, timestamped
└── cache/                        Machine-local, NOT synced
```

All files are plain text. Open in any editor.

---

## Architecture

### Tech Stack

| Component | Choice | Reason |
|-----------|--------|--------|
| Language | Python 3.11+, async | Fast async I/O, mature ecosystem |
| HTTP | httpx | Async, clean API |
| LLM (cloud) | Anthropic claude-sonnet-4-6 | Complex reasoning, vision |
| LLM (local) | LM Studio at localhost:1234 | Sensitive/bulk tasks, no API cost |
| Config/memory | Plain TOML + JSONL | Human-readable, iCloud-syncable |
| IPC | Unix socket at ~/.ares/ares.sock | Low latency, no port conflicts |
| Scheduling | macOS launchd | Native, restarts on crash |
| Workflows | n8n at localhost:5678 | Visual, editable by a human |
| No frameworks | No LangChain/AutoGen/CrewAI | ARES is its own loop |

### LLM Routing

| Condition | Backend |
|-----------|---------|
| Task is sensitive/personal | Local LM Studio |
| Complex reasoning, vision | Cloud (claude-sonnet-4-6) |
| High-volume / bulk generation | Local (save API costs) |
| Local produces worse results | Escalate to cloud |

### Decision Authority

| Action | Authority |
|--------|-----------|
| Reading files, web research | Fully autonomous |
| Writing drafts, creating files | Fully autonomous |
| Installing CLI tools (Homebrew/npm) | Propose → proceed after 5 min silence |
| Installing GUI applications | Must have explicit approval |
| Building n8n workflows | Build draft → show before activating |
| Publishing content publicly | Always requires explicit approval |
| Deleting any file | Always requires explicit approval |
| Spending money (API, subscriptions) | Always requires explicit approval |

---

## YouTube Production Pipeline

The primary use case — end-to-end video production from idea to publish.

| Stage | Tool | Output | Format |
|-------|------|--------|--------|
| 0: Brief | Claude | `brief.md` | Markdown |
| 1: Research | Claude | `research.md` | Markdown |
| 2: Script | Claude | `script.md` | Markdown |
| 3: Voice | ElevenLabs | `voice_final.mp3` | MP3 |
| 4: Video | DaVinci Resolve | production notes + `export.mp4` | MP4 |
| 5: Thumbnail | Canva / Figma | `thumbnail_brief.md` + `thumbnail.png` | PNG 1280×720 |
| 6: Publish | n8n → YouTube Studio | live YouTube URL | — |

**Checkpoints** (ARES pauses and waits for approval):
- After brief → before research
- After script → before voice (user may want to edit)
- After voice → before video
- After video export → before thumbnail
- After thumbnail → **hard gate** before publish (always)

### Run the pipeline

```bash
ares goal "make a YouTube video about how GPS works"
```

Or from Python:
```python
import asyncio
from ares.workflows.youtube import run_pipeline

asyncio.run(run_pipeline("How GPS works", target_length=12))
```

---

## Memory System

ARES learns from every job.

After every completed workflow, ARES writes a retrospective:
- What worked
- What didn't work
- Preferences noticed (word count, timing, style)
- What to do differently next time

Retrospectives accumulate into a preference profile. The system gets better with each run.

```bash
ares memory show        # Summary of recent tasks and preferences
ares memory path        # Path to memory directory
```

---

## iCloud Sync

ARES syncs memory and task state to iCloud Drive for Mac Studio ↔ MacBook continuity.

Configure in `~/.ares/config/ares.toml`:
```toml
[sync]
enabled = true
icloud_path = ""  # Auto-detected on macOS
```

---

## n8n Workflows

Workflows live in `~/.ares/n8n-workflows/` as JSON files — editable, version-controllable.

ARES always builds a draft and shows it before activating anything.

Open n8n at http://localhost:5678 to view/edit active workflows.

---

## launchd Service (Mac Studio)

Register ARES as a persistent background service:

```bash
ares start --register-launchd
```

Or manually load the included plist:
```bash
# Edit com.ares.daemon.plist with your paths and API key first
cp com.ares.daemon.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.ares.daemon.plist
```

---

## Configuration

`~/.ares/config/ares.toml`:

```toml
[llm]
local_url = "http://localhost:1234/v1"
local_model = "local-model"
cloud_model = "claude-sonnet-4-6"
cloud_api_key = ""  # Or set ANTHROPIC_API_KEY env var

[n8n]
url = "http://localhost:5678"
api_key = ""

[sync]
enabled = true
icloud_path = ""  # Auto-detected

[decision]
cli_install_silence_minutes = 5
```

---

## Audit Log

Every action is logged to `~/.ares/logs/exec.log`:

```
2025-03-09T14:22:01Z  [TASK:yt-001]  stage=script  action=llm_call  model=claude-sonnet-4-6
2025-03-09T14:22:08Z  [TASK:yt-001]  stage=script  action=file_write  path=~/Documents/ARES/…
2025-03-09T14:22:14Z  [TASK:yt-001]  stage=script  action=checkpoint  message="Waiting for approval"
```

```bash
ares log          # Last 50 lines
ares log -n 100   # Last 100 lines
ares log -f       # Follow (like tail -f)
```
