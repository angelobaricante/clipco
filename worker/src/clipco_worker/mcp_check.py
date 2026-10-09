"""The app's Codex connection check: a real MCP session with clipco-mcp, plus Codex registration state."""

import asyncio
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from importlib.metadata import version
from pathlib import Path

from mcp import Client, StdioServerParameters

# The Codex CLI bundled with the ChatGPT app is newer than most standalone installs.
BUNDLED_CODEX = Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex")


def find_codex() -> Path | None:
    if configured := os.environ.get("CLIPCO_CODEX"):
        return Path(configured)
    if BUNDLED_CODEX.exists():
        return BUNDLED_CODEX
    found = shutil.which("codex", path=f"/opt/homebrew/bin:/usr/local/bin:{os.environ.get('PATH', '')}")
    return Path(found) if found else None


def codex_state(codex: Path | None) -> dict:
    state = {"path": str(codex) if codex else None, "version": None, "registered": False,
             "registered_command": None, "error": None}
    if codex is None or not codex.exists():
        return state

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(codex), *args], capture_output=True, text=True, timeout=20)

    try:
        state["version"] = run("--version").stdout.strip() or None
        got = run("mcp", "get", "clipco", "--json")
        if got.returncode == 0:
            transport = json.loads(got.stdout).get("transport", {})
            state["enabled"] = json.loads(got.stdout).get("enabled", True)
            state["registered"] = True
            state["registered_command"] = [transport.get("command") or "", *(transport.get("args") or [])]
    except (OSError, subprocess.SubprocessError, ValueError) as e:  # report it; never fail the whole check
        state["error"] = f"{type(e).__name__}: {e}"
    return state


async def session(command: list[str]) -> dict:
    started = time.monotonic()
    async with Client(StdioServerParameters(command=command[0], args=command[1:])) as client:
        connected = time.monotonic()
        tools = [t.name for t in (await client.list_tools()).tools]
        overview = await client.call_tool("get_project_overview", {})
        if overview.is_error:
            raise RuntimeError(overview.content[0].text)
        return {"tools": tools, "project_count": len(overview.structured_content["projects"]),
                "protocol_version": client.protocol_version,
                "server_version": client.server_info.version if client.server_info else None,
                "connect_ms": round((connected - started) * 1000),
                "overview_ms": round((time.monotonic() - connected) * 1000)}


def connection_status(home: Path) -> dict:
    command = [str(Path(sys.executable).parent / "clipco-mcp"), "--home", str(home)]
    status = {"server_command": command, "add_command": "codex mcp add clipco -- " + shlex.join(command),
              "sdk_version": version("mcp"), "codex": codex_state(find_codex())}
    from .agent_connections import statuses
    status["agents"] = statuses(command, status["codex"])
    try:
        status |= {"ok": True, "error": None, **asyncio.run(asyncio.wait_for(session(command), timeout=15))}
    except Exception as e:  # the check reports what failed instead of crashing the app's sheet
        status |= {"ok": False, "error": f"{type(e).__name__}: {e}", "tools": [], "project_count": None,
                   "protocol_version": None}
    return status
