"""Local agent registration; inspecting configuration does not contact an AI provider."""

import fcntl
import json
import os
import shlex
import shutil
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path

from .mcp_check import codex_state, find_codex

CLIENTS = ("codex", "claude-code", "claude-desktop")


def claude_config(client: str) -> Path:
    if client == "claude-desktop":
        return Path(os.environ.get("CLIPCO_CLAUDE_DESKTOP_CONFIG",
                                   Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"))
    if directory := os.environ.get("CLAUDE_CONFIG_DIR"):
        return Path(directory) / ".claude.json"
    return Path.home() / ".claude.json"


def find_claude() -> str | None:
    if configured := os.environ.get("CLIPCO_CLAUDE"):
        return configured if Path(configured).is_file() else None
    return shutil.which("claude", path=f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:"
                        + os.environ.get("PATH", ""))


def read_config(path: Path) -> tuple[bytes | None, dict]:
    raw = path.read_bytes() if path.exists() else None
    config = json.loads(raw) if raw is not None else {}
    if not isinstance(config, dict) or not isinstance(config.get("mcpServers", {}), dict):
        raise ValueError("The existing agent configuration is invalid. Repair it in the agent before connecting.")
    return raw, config


def matches(entry: dict, command: list[str]) -> bool:
    return (isinstance(entry, dict) and entry.get("type", "stdio") == "stdio"
            and entry.get("command") == command[0] and entry.get("args", []) == command[1:]
            and not entry.get("env"))


def client_status(client: str, command: list[str], codex: dict | None = None) -> dict:
    name = {"codex": "Codex", "claude-code": "Claude Code", "claude-desktop": "Claude Desktop"}[client]
    result = {"id": client, "name": name, "installed": False, "configured": False,
              "state": "not_installed", "error": None, "config_path": None,
              "setup_command": None, "setup_json": None,
              "guidance": "Start a new agent session after connecting, then ask it to list your Clipco Projects."}
    if client == "codex":
        c = codex if codex is not None else codex_state(find_codex())
        result["installed"] = c["path"] is not None and Path(c["path"]).is_file()
        result["setup_command"] = "codex mcp add clipco -- " + shlex.join(command)
        result["error"] = c["error"]
        result["configured"] = c["registered"] and c["registered_command"] == command and c.get("enabled", True)
        result["state"] = ("error" if c["error"] else "configured" if result["configured"]
                           else "conflict" if c["registered"] else "not_configured" if result["installed"]
                           else "not_installed")
        return result

    path = claude_config(client)
    result["config_path"] = str(path)
    entry = {"command": command[0], "args": command[1:]}
    if client == "claude-code":
        entry["type"] = "stdio"
        result["installed"] = find_claude() is not None
        result["setup_command"] = "claude mcp add --scope user --transport stdio clipco -- " + shlex.join(command)
    else:
        desktop = Path(os.environ.get("CLIPCO_CLAUDE_DESKTOP_APP", "/Applications/Claude.app"))
        result["installed"] = any(p.exists() for p in (desktop, Path.home() / "Applications/Claude.app"))
        result["guidance"] = "Quit and reopen Claude Desktop to load Clipco, then look for its footage tools in a chat."
    result["setup_json"] = json.dumps({"mcpServers": {"clipco": entry}}, indent=2)
    try:
        _, config = read_config(path)
        servers = config.get("mcpServers", {})
        saved = servers.get("clipco")
        result["configured"] = saved is not None and matches(saved, command) and not saved.get("disabled", False)
        result["state"] = ("configured" if result["configured"] else "conflict" if "clipco" in servers
                           else "not_configured" if result["installed"] else "not_installed")
    except (OSError, ValueError) as error:
        result["state"], result["error"] = "error", str(error)
    return result


def statuses(command: list[str], codex: dict) -> list[dict]:
    return [client_status(client, command, codex if client == "codex" else None) for client in CLIENTS]


def merge_registration(path: Path, entry: dict | None) -> None:
    """Add or remove only our named entry, preserving unrelated settings and refusing invalid JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".clipco-lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.is_symlink():
            raise ValueError("Agent configuration is a symbolic link. Use manual setup in the agent.")
        raw, config = read_config(path)
        servers = config.setdefault("mcpServers", {})
        if entry is None:
            if "clipco" not in servers:
                return
            del servers["clipco"]
        elif "clipco" in servers:
            if servers["clipco"] == entry:
                return
            raise ValueError("A different Clipco registration already exists. Review it in the agent before connecting.")
        if entry is not None:
            servers["clipco"] = entry
        encoded = (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode()
        fd, temporary = tempfile.mkstemp(prefix=".clipco-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            if (path.read_bytes() if path.exists() else None) != raw:
                raise ValueError("Agent settings changed during setup. Retry after it finishes saving.")
            if raw is not None:
                backup = path.with_name(path.name + f".clipco-backup-{uuid.uuid4().hex}")
                with backup.open("xb") as output:
                    os.chmod(backup, 0o600)
                    output.write(raw)
                os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def connect(client: str, command: list[str]) -> None:
    state = client_status(client, command)
    if state["configured"]:
        return
    if state["state"] == "conflict":
        raise ValueError("Clipco is already registered with different settings or disabled. Review it in the agent first.")
    if state["error"]:
        raise ValueError(state["error"])
    if not state["installed"]:
        raise ValueError(f"Install {state['name']} first, then check setup again.")
    if client == "codex":
        executable = find_codex()
        result = subprocess.run([str(executable), "mcp", "add", "clipco", "--", *command],
                                capture_output=True, text=True, timeout=20)
        if result.returncode:
            # Do not echo arbitrary client output (which may contain private settings).
            raise ValueError("Codex could not save Clipco's registration. Use manual setup or check its settings.")
    else:
        entry = {"command": command[0], "args": command[1:]}
        if client == "claude-code":
            entry["type"] = "stdio"
        merge_registration(claude_config(client), entry)
    if not client_status(client, command)["configured"]:
        raise ValueError("The registration could not be verified. Check the agent's settings.")


def disconnect(client: str, command: list[str]) -> None:
    """Remove only the named Clipco registration, including disabled/stale registrations."""
    state = client_status(client, command)
    if state["error"]:
        raise ValueError(state["error"])
    if state["state"] not in ("configured", "conflict"):
        return
    if client == "codex":
        result = subprocess.run([str(find_codex()), "mcp", "remove", "clipco"],
                                capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise ValueError("Codex could not remove Clipco's registration. Check its settings.")
    else:
        merge_registration(claude_config(client), None)
    if client_status(client, command)["state"] in ("configured", "conflict"):
        raise ValueError("The connection is still registered. Check the agent's settings.")
