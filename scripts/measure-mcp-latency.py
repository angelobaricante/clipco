"""Warm retrieval latency through the real stdio MCP server, as Codex would call it.

  worker/.venv/bin/python scripts/measure-mcp-latency.py PROJECT_ID "query" [PROJECT_ID "query"]...

Reads the index only (CLIPCO_HOME or the app's default). Prints server start-up plus handshake time,
then each tool call's latency over 5 repeats and the size of what it returned.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from mcp import Client, StdioServerParameters

HOME = os.environ.get("CLIPCO_HOME", str(Path.home() / "Library/Application Support/Clipco"))
SERVER = str(Path(sys.executable).parent / "clipco-mcp")
REPEATS = 5


def size(result) -> int:
    return sum(len(getattr(part, "text", None) or getattr(part, "data", "") or "") for part in result.content)


async def measure(pairs: list[tuple[str, str]]) -> None:
    t0 = time.monotonic()
    async with Client(StdioServerParameters(command=SERVER, args=["--home", HOME])) as client:
        print(f"server start-up + handshake: {(time.monotonic() - t0) * 1000:.0f} ms")
        calls = [("get_project_overview", {"project_id": pairs[0][0]})]
        calls += [("search_footage", {"project_id": pid, "query": q}) for pid, q in pairs]
        segment = None
        for name, arguments in calls:
            times = []
            for _ in range(REPEATS):
                t = time.monotonic()
                result = await client.call_tool(name, arguments)
                times.append((time.monotonic() - t) * 1000)
            if name == "search_footage" and segment is None:
                results = json.loads(result.content[0].text).get("results", [])
                segment = results[0]["segment_id"] if results else None
            label = f"{name}({arguments.get('query', '')!r})" if "query" in arguments else name
            print(f"{label}: {min(times):.1f}-{max(times):.1f} ms, {size(result)} chars")
        for name in ("get_segment_context", "get_segment_preview", "resolve_media") if segment else ():
            t = time.monotonic()
            result = await client.call_tool(name, {"segment_id": segment})
            print(f"{name}: {(time.monotonic() - t) * 1000:.1f} ms, {size(result)} chars")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or len(args) % 2:
        raise SystemExit(__doc__)
    asyncio.run(measure(list(zip(args[::2], args[1::2]))))
