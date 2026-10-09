"""App worker commands against isolated client settings and real stdio MCP."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pytest

WORKER = Path(sys.executable).parent / "clipco-worker"

@pytest.fixture
def agents(tmp_path):
    root = tmp_path / "agent settings with spaces"
    root.mkdir()
    codex = root / "codex-adapter"
    codex.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p = Path(os.environ["CLIPCO_TEST_CODEX_CONFIG"])
c = json.loads(p.read_text()) if p.exists() else {}
a = sys.argv[1:]
if a == ["--version"]:
    print("codex test adapter")
elif a[:3] == ["mcp", "get", "clipco"]:
    if "clipco" not in c: sys.exit(1)
    print(json.dumps(c["clipco"]))
elif a[:4] == ["mcp", "add", "clipco", "--"]:
    c["clipco"] = {"enabled": True, "transport": {"command": a[4], "args": a[5:]}}
    p.write_text(json.dumps(c))
elif a == ["mcp", "remove", "clipco"]:
    c.pop("clipco", None)
    p.write_text(json.dumps(c))
else:
    sys.exit(2)
''')
    codex.chmod(0o755)
    desktop = root / "Claude.app"
    desktop.mkdir()
    env = {**os.environ, "CLIPCO_HOME": str(root / "index"), "CLIPCO_CODEX": str(codex),
           "CLIPCO_TEST_CODEX_CONFIG": str(root / "codex.json"), "CLIPCO_CLAUDE": str(codex),
           "CLAUDE_CONFIG_DIR": str(root), "CLIPCO_CLAUDE_DESKTOP_APP": str(desktop),
           "CLIPCO_CLAUDE_DESKTOP_CONFIG": str(root / "claude_desktop_config.json")}
    invoke(env, "create-project", "--name", "Adapter fixture")
    return root, env

def invoke(env, *args, succeeds=True):
    result = subprocess.run([str(WORKER), *args], capture_output=True, text=True, env=env, timeout=30)
    event = json.loads(result.stdout.splitlines()[-1])
    assert (result.returncode == 0) == succeeds, (event, result.stderr)
    return event

def client(event, name):
    return next(a for a in event["mcp"]["agents"] if a["id"] == name)

def test_status_separates_helper_readiness_from_registration(agents):
    _, env = agents
    event = invoke(env, "mcp-status")
    assert event["mcp"]["ok"] is True
    assert len(event["mcp"]["tools"]) == 5
    assert event["mcp"]["project_count"] == 1
    for name in ("codex", "claude-code", "claude-desktop"):
        assert client(event, name)["state"] == "not_configured"
        assert client(event, name)["configured"] is False

@pytest.mark.parametrize("name,file", [("claude-code", ".claude.json"),
                                      ("claude-desktop", "claude_desktop_config.json")])
def test_connect_preserves_settings_backs_up_and_is_idempotent(agents, name, file):
    root, env = agents
    path = root / file
    original = b'{"preferences":{"theme":"dark"},"mcpServers":{"other":{"command":"keep-me"}}}\n'
    path.write_bytes(original)
    event = invoke(env, "connect-agent", "--client", name)
    assert client(event, name)["configured"] is True
    saved = json.loads(path.read_text())
    assert saved["preferences"] == {"theme": "dark"}
    assert saved["mcpServers"]["other"] == {"command": "keep-me"}
    registration = saved["mcpServers"]["clipco"]
    assert [registration["command"], *registration["args"]] == event["mcp"]["server_command"]
    assert list(root.glob(file + ".clipco-backup-*"))[0].read_bytes() == original
    before = path.read_bytes(), path.stat().st_mtime_ns
    invoke(env, "connect-agent", "--client", name)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert len(list(root.glob(file + ".clipco-backup-*"))) == 1

@pytest.mark.parametrize("contents", [b'{"mcpServers":{"clipco":{"command":"different"}}}',
                                       b'{"mcpServers":[]}', b'{broken', b'[]',
                                       b'{"mcpServers":{"clipco":null}}'])
def test_invalid_or_conflicting_settings_untouched(agents, contents):
    root, env = agents
    path = root / "claude_desktop_config.json"
    path.write_bytes(contents)
    invoke(env, "connect-agent", "--client", "claude-desktop", succeeds=False)
    assert path.read_bytes() == contents
    assert not list(root.glob("claude_desktop_config.json.clipco-backup-*"))

def test_codex_preserves_other_servers_and_refuses_conflict(agents):
    root, env = agents
    path = root / "codex.json"
    path.write_text(json.dumps({"other": {"keep": True}}))
    event = invoke(env, "connect-agent", "--client", "codex")
    assert client(event, "codex")["configured"]
    config = json.loads(path.read_text())
    assert config["other"] == {"keep": True}
    before = path.read_bytes()
    invoke(env, "connect-agent", "--client", "codex")
    assert path.read_bytes() == before
    config["clipco"]["transport"]["args"] = ["--home", "wrong index"]
    path.write_text(json.dumps(config))
    before = path.read_bytes()
    invoke(env, "connect-agent", "--client", "codex", succeeds=False)
    assert path.read_bytes() == before

def test_missing_agent_and_symlink_cannot_be_connected(agents):
    root, env = agents
    invoke({**env, "CLIPCO_CLAUDE": str(root / "absent")},
           "connect-agent", "--client", "claude-code", succeeds=False)
    assert not (root / ".claude.json").exists()
    target = root / "target.json"
    target.write_text('{}')
    (root / "claude_desktop_config.json").symlink_to(target)
    invoke(env, "connect-agent", "--client", "claude-desktop", succeeds=False)
    assert target.read_text() == '{}'

def test_real_claude_code_recognizes_user_registration(agents):
    # No chat/model call: installed CLI reads isolated config and checks only the local helper.
    claude = shutil.which("claude")
    if not claude:
        pytest.skip("Claude Code not installed")
    _, env = agents
    env = {**env, "CLIPCO_CLAUDE": claude}
    event = invoke(env, "connect-agent", "--client", "claude-code")
    result = subprocess.run([claude, "mcp", "get", "clipco"], env=env, capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert event["mcp"]["server_command"][0] in result.stdout
    assert "User" in result.stdout

def test_unavailable_footage_tools_do_not_write_agent_settings(agents):
    root, env = agents
    config = root / "claude_desktop_config.json"
    config.write_bytes(b'{"preferences":{"keep":true}}')
    before = config.read_bytes()
    (root / "index" / "index.sqlite").write_bytes(b'not a valid footage index')
    event = invoke(env, "connect-agent", "--client", "claude-desktop", succeeds=False)
    assert "footage tools are unavailable" in event["message"]
    assert config.read_bytes() == before


@pytest.mark.parametrize("name,file", [("codex", "codex.json"), ("claude-code", ".claude.json"),
                                      ("claude-desktop", "claude_desktop_config.json")])
def test_disconnect_then_reconnect_preserves_other_settings(agents, name, file):
    root, env = agents
    path = root / file
    other = {"command": "keep-me"}
    config = {"other": other} if name == "codex" else {"preferences": {"keep": True}, "mcpServers": {"other": other}}
    path.write_text(json.dumps(config))
    invoke(env, "connect-agent", "--client", name)
    event = invoke(env, "disconnect-agent", "--client", name)
    assert client(event, name)["state"] == "not_configured"
    assert json.loads(path.read_text()) == config
    before = path.read_bytes(), path.stat().st_mtime_ns
    invoke(env, "disconnect-agent", "--client", name)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert client(invoke(env, "connect-agent", "--client", name), name)["configured"]

@pytest.mark.parametrize("name,file", [("codex", "codex.json"), ("claude-code", ".claude.json"),
                                      ("claude-desktop", "claude_desktop_config.json")])
def test_stale_connection_can_be_removed_and_connected(agents, name, file):
    root, env = agents
    path = root / file
    entry = {"command": "stale-helper", "disabled": True}
    config = {"clipco": {"enabled": False, "transport": entry}, "other": {"keep": True}} if name == "codex" else {"mcpServers": {"clipco": entry, "other": {"keep": True}}}
    path.write_text(json.dumps(config))
    assert client(invoke(env, "mcp-status"), name)["state"] == "conflict"
    invoke(env, "disconnect-agent", "--client", name)
    assert client(invoke(env, "connect-agent", "--client", name), name)["configured"]
    saved = json.loads(path.read_text())
    assert (saved if name == "codex" else saved["mcpServers"])["other"] == {"keep": True}


def test_disconnect_works_when_footage_tools_are_unavailable(agents):
    root, env = agents
    invoke(env, "connect-agent", "--client", "claude-desktop")
    (root / "index" / "index.sqlite").write_bytes(b'broken')
    event = invoke(env, "disconnect-agent", "--client", "claude-desktop")
    assert not event["mcp"]["ok"]
    assert not client(event, "claude-desktop")["configured"]
