"""Summarise a Codex session log (~/.codex/sessions/**/rollout-*.jsonl) per discovery request.

Every number comes from what Codex recorded: token counts from its usage records, tool calls from its
completed items, tool-result size from what was handed back to the model. Nothing is estimated from
text length, and categories the log does not expose are listed as unavailable.
"""

import argparse
import json
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

UNAVAILABLE = [
    "billed image tokens: images returned to the model are counted, but their token cost is inside input_tokens",
    "tool result tokens: only the text characters and image count returned to the model are recorded",
]


def tool_name(item: dict) -> str | None:
    kind = item.get("type")
    if kind == "McpToolCall":
        return f"mcp:{item.get('server')}.{item.get('tool')}"
    return {"CommandExecution": "shell", "ImageView": "image_view", "FileChange": "file_change",
            "Extension": f"extension:{item.get('kind')}"}.get(kind)


# Where Clipco keeps its index: a direct-inspection route that reads these is not a clean baseline.
INDEX_MARKERS = ("Application Support/Clipco", "index.sqlite", "clipco-mcp", "clipco-worker")


def reads_clipco_index(item: dict) -> bool:
    command = item.get("command")
    text = " ".join(command) if isinstance(command, list) else str(command or "")
    return item.get("type") == "CommandExecution" and any(m in text for m in INDEX_MARKERS)


def failed(item: dict) -> bool:
    return item.get("status") not in (None, "completed") or item.get("exit_code") not in (None, 0)


def output_parts(output) -> list[dict]:
    if isinstance(output, str):
        return [{"type": "input_text", "text": output}]
    return output if isinstance(output, list) else []


def summarize_rollout(lines: list[str]) -> dict:
    meta, model, total = {}, None, None
    turns: dict[str, dict] = {}
    current = None
    for line in lines:
        if not line.strip():
            continue
        event = json.loads(line)
        kind, payload = event.get("type"), event.get("payload") or {}
        sub = payload.get("type") if isinstance(payload, dict) else None
        at = datetime.fromisoformat(event["timestamp"])
        if kind == "session_meta":
            meta = payload
        elif kind == "turn_context":
            model = payload.get("model", model)
        elif sub == "task_started":
            current = payload["turn_id"]
            turns[current] = {"turn_id": current, "answer": None, "_start": at, "_end": None, "model_requests": 0,
                              "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
                              "reasoning_output_tokens": 0, "_tools": Counter(), "failed_tool_calls": 0,
                              "tool_result_text_chars": 0, "tool_result_images": 0, "clipco_index_reads": 0}
        elif kind == "token_usage_record" and payload.get("turn_id") in turns:
            turn, usage = turns[payload["turn_id"]], payload["usage"]
            turn["model_requests"] += 1
            for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"):
                turn[key] += usage.get(key, 0)
        elif sub == "token_count" and payload.get("info"):
            total = payload["info"]["total_token_usage"]
        elif sub == "item_completed" and payload.get("turn_id") in turns:
            item, turn = payload["item"], turns[payload["turn_id"]]
            if name := tool_name(item):
                turn["_tools"][name] += 1
                turn["failed_tool_calls"] += failed(item)
                turn["clipco_index_reads"] += reads_clipco_index(item)
        elif sub in ("function_call_output", "custom_tool_call_output") and current in turns:
            for part in output_parts(payload.get("output")):
                if part.get("type") == "input_image":
                    turns[current]["tool_result_images"] += 1
                else:
                    turns[current]["tool_result_text_chars"] += len(part.get("text", ""))
        elif sub == "task_complete" and payload.get("turn_id") in turns:
            turns[payload["turn_id"]]["_end"] = at
            turns[payload["turn_id"]]["answer"] = payload.get("last_agent_message")

    out = []
    for turn in turns.values():
        start, end, tools = turn.pop("_start"), turn.pop("_end"), turn.pop("_tools")
        turn["wall_seconds"] = round((end - start).total_seconds(), 2) if end else None
        turn["uncached_input_tokens"] = turn["input_tokens"] - turn["cached_input_tokens"]
        turn["tool_calls"] = dict(tools)
        out.append(turn)
    return {"model": model, "cli_version": meta.get("cli_version"), "session_id": meta.get("id"),
            "turns": out, "session_total": total, "unavailable": UNAVAILABLE}


# --- Running the comparison -------------------------------------------------------------------------------
#
# Both routes get the same prompt, model and settings: a scratch working folder they may write to (sampled
# frames, extracted audio) and the footage folder, outside it, which the sandbox leaves read-only. The only
# difference is whether the clipco MCP server is enabled. Other configured MCP servers are disabled on both
# routes so they add no tool overhead to either. Request 1 starts a session (initial discovery); the rest
# resume it, and request 1 is asked again at the end (repeat / cache reuse).

PROMPT = ("The raw footage for this video is in {footage} (read-only; use the current folder for any scratch "
          "files). {query} Answer with each original filename and its "
          "source time range in seconds. Only find footage: do not edit, render or write files. "
          "If a footage index tool is available, you may use it.")


def configured_mcp_servers(config: Path) -> list[str]:
    import tomllib
    try:
        return list(tomllib.loads(config.read_text()).get("mcp_servers", {}))
    except (OSError, tomllib.TOMLDecodeError):
        return []


def run_route(codex: str, route: str, model: str, footage: Path, queries: list[str], sessions: Path,
              servers: list[str], workdir: Path) -> dict:
    disabled = [s for s in servers if route == "baseline" or s != "clipco"]
    overrides = [arg for s in disabled for arg in ("-c", f"mcp_servers.{s}.enabled=false")]
    # `exec resume` takes no -s/-C, so the sandbox is pinned by config for every request alike.
    common = ["--json", "--skip-git-repo-check", "-m", model, "-c", 'sandbox_mode="workspace-write"', *overrides]
    session_id, started = None, time.time()
    for n, query in enumerate([*queries, queries[0]]):
        prompt = PROMPT.format(footage=footage, query=query)
        cmd = ([codex, "exec", *common, "-s", "workspace-write", "-C", str(workdir), prompt] if session_id is None
               else [codex, "exec", "resume", *common, session_id, prompt])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"{route} request {n + 1} failed: {proc.stderr.strip()[-2000:]}")
        session_id = session_id or next((json.loads(l).get("thread_id") for l in proc.stdout.splitlines()
                                         if '"thread_id"' in l), None)
        if session_id is None:  # never guess: another Codex session could be writing logs meanwhile
            raise RuntimeError(f"{route}: Codex printed no thread_id, so its session log can't be identified")
    rollouts = sorted((p for p in sessions.rglob(f"rollout-*{session_id}.jsonl") if p.stat().st_mtime >= started),
                      key=lambda p: p.stat().st_mtime)
    if not rollouts:
        raise RuntimeError(f"no Codex session log for {session_id} under {sessions}")
    summary = summarize_rollout(rollouts[-1].read_text().splitlines())
    labels = [f"request {i + 1}" for i in range(len(queries))] + ["request 1 again, same session"]
    for turn, label in zip(summary["turns"], labels):
        turn["request"] = label
    return {"route": route, "disabled_mcp_servers": disabled, "session_log": str(rollouts[-1]), **summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clipco-benchmark",
                                     description="Compare direct inspection with Clipco MCP retrieval in Codex.")
    parser.add_argument("--codex", default="/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex")
    parser.add_argument("--model", required=True, help="the same Codex model for both routes")
    parser.add_argument("--footage", type=Path, required=True, help="folder holding the Project's originals")
    parser.add_argument("--queries", type=Path, required=True, help='JSON: [{"request": ..., "expected": [...]}]')
    parser.add_argument("--out", type=Path, default=Path.home() / ".clipco" / "evidence")
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--routes", nargs="+", default=["baseline", "mcp"], choices=["baseline", "mcp"])
    parser.add_argument("--send-footage-to-codex", action="store_true",
                        help="required: Codex sends what it inspects (frames, transcripts, index context) to OpenAI")
    args = parser.parse_args(argv)
    if not args.send_footage_to_codex:
        parser.error("both routes send footage-derived content to OpenAI and spend Codex credits; "
                     "pass --send-footage-to-codex once the creator has agreed")

    spec = json.loads(args.queries.read_text())
    queries = [q["request"] for q in spec]
    servers = configured_mcp_servers(args.codex_home / "config.toml")
    report = {"recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"), "model": args.model,
              "footage": str(args.footage), "requests": spec, "routes": []}
    for route in args.routes:
        print(f"running {route} route ({len(queries) + 1} requests)…", file=sys.stderr)
        with tempfile.TemporaryDirectory(prefix=f"clipco-bench-{route}-") as workdir:
            report["routes"].append(run_route(args.codex, route, args.model, args.footage.resolve(), queries,
                                              args.codex_home / "sessions", servers, Path(workdir)))
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"benchmark-{datetime.now().astimezone():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(table(report))
    print(f"\nReport: {path}\nGrade each answer against `expected` by hand before quoting any result.")
    if any(t["clipco_index_reads"] for r in report["routes"] if r["route"] == "baseline" for t in r["turns"]):
        print("WARNING: the baseline read Clipco's own index through the shell; it is not a clean baseline.")
    return 0


def table(report: dict) -> str:
    rows = [("| Route | Request | Input | Cached | Uncached | Output | Requests | Tools | Failed | Result chars | "
             "Images | Index reads | Wall s |"), "|" + "---|" * 13]
    for route in report["routes"]:
        for t in route["turns"]:
            tools = ", ".join(f"{k}×{v}" for k, v in t["tool_calls"].items()) or "none"
            rows.append(f"| {route['route']} | {t.get('request', t['turn_id'])} | {t['input_tokens']} | "
                        f"{t['cached_input_tokens']} | {t['uncached_input_tokens']} | {t['output_tokens']} | "
                        f"{t['model_requests']} | {tools} | {t['failed_tool_calls']} | "
                        f"{t['tool_result_text_chars']} | {t['tool_result_images']} | {t['clipco_index_reads']} | "
                        f"{t['wall_seconds']} |")
    return "\n".join(rows)


if __name__ == "__main__":
    raise SystemExit(main())
