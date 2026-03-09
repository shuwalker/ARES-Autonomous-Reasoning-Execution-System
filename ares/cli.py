"""ARES CLI — entry points.

ares start               launch daemon (register as launchd service)
ares stop                graceful shutdown
ares goal "…"          give ARES a high-level goal
ares status              what is ARES currently doing
ares tools               show installed tool registry
ares tools install [x]   propose and install a tool
ares memory show         browse memory
ares log                 tail the audit log
ares pause               pause current task (I'm taking over)
ares resume              resume after manual takeover
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

from .config import ares_paths, get_config, write_default_config
from .audit import tail_log, log_sync
from .memory import list_episodic, read_preferences, list_knowledge, list_projects
from .tools.registry import load_registry, probe_all_tools, register_tool, ToolEntry


console = Console()


# ---------------------------------------------------------------------------
# IPC helpers
# ---------------------------------------------------------------------------

def _send_ipc(cmd: dict[str, Any]) -> dict[str, Any]:
    """Send a command to the running daemon via Unix socket."""
    sock_path = str(ares_paths()["socket"])
    if not os.path.exists(sock_path):
        return {"error": "Daemon not running (socket not found). Run 'ares start' first."}

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(10.0)
            s.connect(sock_path)
            s.sendall(json.dumps(cmd).encode())
            data = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
            return json.loads(data.decode())
    except (ConnectionRefusedError, FileNotFoundError):
        return {"error": "Daemon not running."}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# launchd plist helper
# ---------------------------------------------------------------------------

LAUNCHD_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ares.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>{ares_bin}</string>
        <string>start</string>
        <string>--daemon</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_dir}/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>ANTHROPIC_API_KEY</key>
        <string>{anthropic_key}</string>
    </dict>
</dict>
</plist>
"""


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------

@click.group()
def main() -> None:
    """ARES — Autonomous Reasoning & Execution System."""
    pass


# ---------------------------------------------------------------------------
# ares start
# ---------------------------------------------------------------------------

@main.command()
@click.option("--daemon", is_flag=True, default=False, help="Run as background daemon (used by launchd)")
@click.option("--register-launchd", is_flag=True, default=False, help="Register as a launchd service")
def start(daemon: bool, register_launchd: bool) -> None:
    """Launch ARES daemon."""
    write_default_config()

    if register_launchd:
        _register_launchd()
        return

    if daemon:
        # Actually run the daemon loop
        from .daemon import start_daemon
        console.print("[bold green]ARES starting...[/bold green]")
        start_daemon()
        return

    # Interactive mode: check if already running
    response = _send_ipc({"cmd": "status"})
    if "error" not in response:
        console.print("[yellow]ARES is already running.[/yellow]")
        _print_status(response)
        return

    # Launch as background process
    ares_bin = sys.argv[0]
    log_dir = ares_paths()["logs"]
    proc = subprocess.Popen(
        [ares_bin, "start", "--daemon"],
        stdout=open(log_dir / "stdout.log", "a"),
        stderr=open(log_dir / "stderr.log", "a"),
        start_new_session=True,
    )
    console.print(f"[bold green]ARES started[/bold green] (pid {proc.pid})")
    console.print(f"Logs: {log_dir}/stderr.log")
    console.print("Run 'ares status' to check.")


def _register_launchd() -> None:
    """Write and load a launchd plist."""
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / "com.ares.daemon.plist"

    ares_bin = sys.argv[0]
    log_dir = ares_paths()["logs"]
    cfg = get_config()
    key = cfg.llm.cloud_api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    content = LAUNCHD_PLIST_TEMPLATE.format(
        ares_bin=ares_bin,
        log_dir=log_dir,
        anthropic_key=key,
    )
    plist_path.write_text(content)

    result = subprocess.run(
        ["launchctl", "load", "-w", str(plist_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        console.print(f"[green]Registered as launchd service.[/green]")
        console.print(f"Plist: {plist_path}")
    else:
        console.print(f"[red]launchctl error:[/red] {result.stderr}")


# ---------------------------------------------------------------------------
# ares stop
# ---------------------------------------------------------------------------

@main.command()
def stop() -> None:
    """Gracefully stop ARES."""
    response = _send_ipc({"cmd": "stop"})
    if "error" in response:
        console.print(f"[red]{response['error']}[/red]")
    else:
        console.print(f"[green]{response.get('message', 'Stopped.')}[/green]")


# ---------------------------------------------------------------------------
# ares goal
# ---------------------------------------------------------------------------

@main.command()
@click.argument("goal_text", nargs=-1, required=True)
def goal(goal_text: tuple[str, ...]) -> None:
    """Give ARES a high-level goal."""
    full_goal = " ".join(goal_text)
    response = _send_ipc({"cmd": "goal", "goal": full_goal})
    if "error" in response:
        # Daemon not running — queue the goal directly
        console.print(f"[yellow]Daemon not running. Queuing goal for next start.[/yellow]")
        from .tasks.queue import new_task, enqueue
        task = new_task(full_goal)
        enqueue(task)
        console.print(f"Goal queued as [bold]{task.id}[/bold]: {full_goal[:80]}")
    else:
        console.print(f"[green]{response.get('message', 'Goal received.')}[/green]")


# ---------------------------------------------------------------------------
# ares status
# ---------------------------------------------------------------------------

@main.command()
def status() -> None:
    """Show what ARES is currently doing."""
    response = _send_ipc({"cmd": "status"})
    if "error" in response:
        console.print(f"[red]ARES is not running.[/red]  {response['error']}")

        # Show queued tasks from disk
        from .tasks.queue import list_active
        active = list_active()
        if active:
            console.print(f"\n[yellow]{len(active)} tasks queued on disk:[/yellow]")
            for t in active:
                console.print(f"  [{t.status}] {t.id}: {t.goal[:60]}")
        return

    _print_status(response)


def _print_status(data: dict[str, Any]) -> None:
    state = "[green]RUNNING[/green]" if data.get("running") else "[red]STOPPED[/red]"
    paused = " [yellow](PAUSED)[/yellow]" if data.get("paused") else ""
    console.print(f"Status: {state}{paused}")

    current = data.get("current_goal")
    if current:
        console.print(f"Working on: [bold]{current}[/bold]")

    queue = data.get("queue", [])
    if queue:
        table = Table(title="Task Queue", show_header=True)
        table.add_column("ID")
        table.add_column("Goal")
        table.add_column("Status")
        for t in queue:
            table.add_row(t["id"], t["goal"], t["status"])
        console.print(table)
    else:
        console.print("Queue: empty")


# ---------------------------------------------------------------------------
# ares pause / resume
# ---------------------------------------------------------------------------

@main.command()
def pause() -> None:
    """Pause ARES — I'm taking over."""
    response = _send_ipc({"cmd": "pause"})
    if "error" in response:
        console.print(f"[red]{response['error']}[/red]")
    else:
        console.print(f"[yellow]Paused.[/yellow] {response.get('message', '')}")
        console.print("Files are yours. Run 'ares resume' when done.")


@main.command()
def resume() -> None:
    """Resume ARES after manual takeover."""
    response = _send_ipc({"cmd": "resume"})
    if "error" in response:
        console.print(f"[red]{response['error']}[/red]")
    else:
        console.print(f"[green]Resumed.[/green] {response.get('message', '')}")


# ---------------------------------------------------------------------------
# ares log
# ---------------------------------------------------------------------------

@main.command(name="log")
@click.option("-n", "--lines", default=50, help="Number of lines to show")
@click.option("-f", "--follow", is_flag=True, default=False, help="Follow the log")
def log_cmd(lines: int, follow: bool) -> None:
    """Tail the ARES audit log."""
    paths = ares_paths()
    log_path = paths["logs"] / "exec.log"

    if not log_path.exists():
        console.print("[yellow]No log yet.[/yellow]")
        return

    if follow:
        import time
        console.print(f"[dim]Tailing {log_path}...[/dim]")
        with open(log_path) as fh:
            fh.seek(0, 2)  # Seek to end
            while True:
                line = fh.readline()
                if line:
                    print(line, end="")
                else:
                    time.sleep(0.5)
    else:
        entries = tail_log(lines)
        for entry in entries:
            console.print(entry)


# ---------------------------------------------------------------------------
# ares tools
# ---------------------------------------------------------------------------

@main.group()
def tools() -> None:
    """Manage the ARES tool registry."""
    pass


@tools.command(name="list")
@click.option("--probe", is_flag=True, default=False, help="Check which tools are actually installed")
def tools_list(probe: bool) -> None:
    """Show registered tools."""
    if probe:
        console.print("[dim]Probing tool installations...[/dim]")
        probe_all_tools()

    registry = load_registry()
    if not registry:
        console.print("[yellow]No tools registered.[/yellow]")
        console.print("Run 'ares tools init' to populate with defaults.")
        return

    table = Table(title="ARES Tool Registry", show_header=True)
    table.add_column("Key")
    table.add_column("Name")
    table.add_column("Installed")
    table.add_column("Version")
    table.add_column("Description")

    for key, entry in sorted(registry.items()):
        installed = "[green]✓[/green]" if entry.installed else "[dim]✗[/dim]"
        table.add_row(key, entry.name, installed, entry.version or "—", entry.description[:50])

    console.print(table)


@tools.command(name="init")
def tools_init() -> None:
    """Populate registry with built-in tool definitions."""
    from .tools.registry import ensure_builtin_tools
    ensure_builtin_tools()
    console.print("[green]Built-in tools registered.[/green]")
    tools_list.invoke(click.Context(tools_list, info_name="list"))


@tools.command(name="install")
@click.argument("tool_key")
def tools_install(tool_key: str) -> None:
    """Propose and install a tool."""
    from .tools.registry import get_tool, check_tool_installed, mark_installed
    import subprocess

    entry = get_tool(tool_key)
    if entry is None:
        console.print(f"[red]Tool '{tool_key}' not in registry.[/red]")
        console.print("Run 'ares tools list' to see registered tools.")
        return

    installed, version = check_tool_installed(entry)
    if installed:
        console.print(f"[green]{entry.name} is already installed.[/green] (v{version})")
        return

    if not entry.install_command:
        console.print(f"[yellow]{entry.name} requires manual installation.[/yellow]")
        if entry.url:
            console.print(f"URL: {entry.url}")
        return

    console.print(Panel(
        f"[bold]Propose: install {entry.name}[/bold]\n\n"
        f"Reason: {entry.description}\n"
        f"Method: {entry.install_method}\n"
        f"Command: [code]{entry.install_command}[/code]\n\n"
        f"[dim]{entry.notes}[/dim]",
        title="ARES Tool Install Proposal",
    ))

    if not click.confirm("Approve installation?"):
        console.print("[yellow]Cancelled.[/yellow]")
        return

    console.print(f"Installing {entry.name}...")
    result = subprocess.run(entry.install_command, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        _, version = check_tool_installed(entry)
        mark_installed(tool_key, version)
        console.print(f"[green]Installed {entry.name}.[/green] (v{version})")
        log_sync(action="tool_installed", tool=tool_key, version=version)
    else:
        console.print(f"[red]Install failed:[/red]\n{result.stderr}")


@tools.command(name="add")
@click.argument("key")
@click.option("--name", prompt=True)
@click.option("--description", prompt=True)
@click.option("--install-method", default="brew")
@click.option("--install-command", default="")
@click.option("--check-command", default="")
@click.option("--url", default="")
@click.option("--notes", default="")
def tools_add(
    key: str,
    name: str,
    description: str,
    install_method: str,
    install_command: str,
    check_command: str,
    url: str,
    notes: str,
) -> None:
    """Add a new tool to the registry."""
    entry = ToolEntry(
        name=name,
        description=description,
        install_method=install_method,
        install_command=install_command,
        check_command=check_command,
        url=url,
        notes=notes,
    )
    register_tool(key, entry)
    console.print(f"[green]Tool '{key}' added to registry.[/green]")


# ---------------------------------------------------------------------------
# ares memory
# ---------------------------------------------------------------------------

@main.group()
def memory() -> None:
    """Browse ARES memory."""
    pass


@memory.command(name="show")
def memory_show() -> None:
    """Show memory summary."""
    paths = ares_paths()

    console.print(Panel(
        f"[bold]ARES Memory[/bold]\n"
        f"Home: {paths['home']}\n"
        f"Memory: {paths['memory']}",
        title="Memory System",
    ))

    # Episodic
    episodes = list_episodic(10)
    if episodes:
        table = Table(title="Recent Tasks (Episodic)", show_header=True)
        table.add_column("Task ID")
        table.add_column("Goal")
        table.add_column("Outcome")
        table.add_column("Completed")
        for ep in episodes:
            table.add_row(
                ep.get("task_id", ""),
                (ep.get("goal") or "")[:50],
                ep.get("outcome", ""),
                (ep.get("completed_at") or "—")[:19],
            )
        console.print(table)

    # Preferences
    prefs = read_preferences()
    if prefs:
        console.print("\n[bold]Preferences:[/bold]")
        for k, v in prefs.items():
            console.print(f"  {k}: {v}")

    # Knowledge
    knowledge = list_knowledge()
    if knowledge:
        console.print(f"\n[bold]Knowledge notes:[/bold] {', '.join(knowledge[:10])}")

    # Projects
    projects = list_projects()
    if projects:
        console.print(f"\n[bold]Projects:[/bold] {', '.join(projects[:10])}")


@memory.command(name="path")
def memory_path() -> None:
    """Show path to memory directory."""
    paths = ares_paths()
    console.print(str(paths["memory"]))


# ---------------------------------------------------------------------------
# ares setup
# ---------------------------------------------------------------------------

@main.command()
def setup() -> None:
    """First-time setup — discovery conversation + config."""
    from .discovery import run_discovery
    asyncio.run(run_discovery())


# ---------------------------------------------------------------------------
# ares init
# ---------------------------------------------------------------------------

@main.command(name="init")
def init_cmd() -> None:
    """Initialize ARES directories and default config."""
    paths = ares_paths()
    write_default_config()
    from .tools.registry import ensure_builtin_tools
    ensure_builtin_tools()

    console.print("[bold green]ARES initialized.[/bold green]")
    console.print(f"Home: {paths['home']}")
    console.print(f"Config: {paths['config'] / 'ares.toml'}")
    console.print(f"Memory: {paths['memory']}")
    console.print(f"Logs: {paths['logs']}")
    console.print("\nNext steps:")
    console.print("  1. Set ANTHROPIC_API_KEY in your environment")
    console.print("  2. Run 'ares setup' for first-time domain discovery")
    console.print("  3. Run 'ares start' to launch the daemon")


# ---------------------------------------------------------------------------
# ares version
# ---------------------------------------------------------------------------

@main.command()
def version() -> None:
    """Show ARES version."""
    from . import __version__
    console.print(f"ARES v{__version__}")
