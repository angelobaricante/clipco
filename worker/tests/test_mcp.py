"""Import footage through the worker, then query it through the stdio MCP boundary Codex uses."""

import asyncio
import json
import sys
from pathlib import Path

from conftest import SPANS, RecordedSpeech, RecordedVision

from mcp import Client, StdioServerParameters

from clipcon_worker.pipeline import Worker

SERVER = Path(sys.executable).parent / "clipcon-mcp"


def call(home: Path, *calls: tuple[str, dict]) -> list:
    """Start clipcon-mcp as Codex would and run tool calls in one session."""

    async def run():
        params = StdioServerParameters(command=str(SERVER), args=["--home", str(home)])
        async with Client(params) as client:
            return [await client.call_tool(name, args) for name, args in calls]

    return asyncio.run(run())


def payload(result) -> dict:
    """Structured result; its text twin must carry the same metadata."""
    assert not result.is_error, result.content
    text = json.loads(result.content[0].text)
    assert text == result.structured_content
    return result.structured_content


def imported(home: Path, clip: Path) -> tuple[dict, dict]:
    worker = Worker(home, speech=RecordedSpeech(SPANS), vision=RecordedVision())
    project = worker.create_project("Water filter tutorial", context="Explain how the filter works")
    outcome = worker.import_clip(project["id"], clip)
    return project, outcome


def test_overview_lists_projects_then_one_projects_inventory(home, clip):
    project, outcome = imported(home, clip)

    listing, overview = call(home, ("get_project_overview", {}),
                             ("get_project_overview", {"project_id": project["id"]}))

    assert [p["project_id"] for p in payload(listing)["projects"]] == [project["id"]]
    assert payload(overview)["clips"][0]["status"] == "ready"
    data = payload(overview)
    assert data["project"]["name"] == "Water filter tutorial"
    assert data["project"]["context"] == "Explain how the filter works"
    [clip_info] = data["clips"]
    assert clip_info["clip_id"] == outcome["clip_id"]
    assert clip_info["original_filename"] == "talking-head.mp4"
    assert clip_info["status"] == "ready"
    assert clip_info["revision"] == outcome["revision"]
    assert clip_info["segment_count"] >= 1
    assert 11.5 <= clip_info["duration"] <= 12.5

    # Identities and ranges stay stable when unchanged footage is imported again (index reuse).
    Worker(home, speech=RecordedSpeech(SPANS), vision=RecordedVision()).import_clip(project["id"], clip)
    [again] = payload(call(home, ("get_project_overview", {"project_id": project["id"]}))[0])["clips"]
    assert again == clip_info


def test_search_returns_a_bounded_grounded_page_with_continuation_and_honest_empty_sets(home, tmp_path):
    from conftest import make_clip

    from clipcon_worker.pipeline import RECIPE
    from clipcon_worker.speech import TranscriptSpan

    spans = [TranscriptSpan(i * 2.0, i * 2.0 + 1.8, f"Step {i + 1}: rinse the filter cartridge.") for i in range(7)]
    spans.append(TranscriptSpan(14.0, 15.8, "Actually, I mean the upper tank, not the chamber."))
    worker = Worker(home, speech=RecordedSpeech(spans), vision=RecordedVision(),
                    recipe={**RECIPE, "segment_target_seconds": 1.0})  # one Segment per spoken line
    project = worker.create_project("Water filter tutorial")
    clip = make_clip(tmp_path / "a-roll.mp4", seconds=16.0)
    outcome = worker.import_clip(project["id"], clip)
    pid = project["id"]

    first, rest, correction, nothing = (payload(r) for r in call(
        home,
        ("search_footage", {"project_id": pid, "query": "rinse the filter cartridge"}),
        ("search_footage", {"project_id": pid, "query": "rinse the filter cartridge", "offset": 5}),
        ("search_footage", {"project_id": pid, "query": "upper tank"}),
        ("search_footage", {"project_id": pid, "query": "volcano eruption"}),
    ))

    assert len(first["results"]) == 5
    assert first["total_matches"] == 7 and first["truncated"] is True and first["next_offset"] == 5
    assert len(rest["results"]) == 2 and rest["truncated"] is False and rest["next_offset"] is None
    seen = [m["segment_id"] for m in first["results"] + rest["results"]]
    assert len(set(seen)) == 7

    top = correction["results"][0]
    assert top["excerpt"] == "Actually, I mean the upper tank, not the chamber."
    assert top["evidence_basis"] == "transcript"
    assert top["clip_id"] == outcome["clip_id"] and top["project_id"] == pid
    assert top["original_filename"] == "a-roll.mp4"
    assert top["status"] == "ready" and top["revision"] == outcome["revision"]
    assert 14.0 - 1e-6 <= top["start"] < top["end"] <= 16.1

    assert nothing["results"] == [] and nothing["total_matches"] == 0 and nothing["truncated"] is False
    # A filename word alone does not make every Segment of the clip relevant.
    by_name = payload(call(home, ("search_footage", {"project_id": pid, "query": "a-roll"}))[0])
    assert by_name["results"] == []
    capped = payload(call(home, ("search_footage", {"project_id": pid, "query": "rinse", "limit": 50}))[0])
    assert len(capped["results"]) <= 10
    for page in (first, rest, correction):
        assert all(len(m["excerpt"]) <= 240 for m in page["results"])


def test_segment_context_expands_surrounding_transcript_with_evidence_kinds_and_provenance(home, tmp_path):
    from conftest import make_clip

    from clipcon_worker.pipeline import RECIPE
    from clipcon_worker.speech import TranscriptSpan

    spans = [TranscriptSpan(0.0, 3.0, "First, fill the upper chamber."),
             TranscriptSpan(3.5, 6.0, "Actually, I mean the upper tank, not the chamber."),
             TranscriptSpan(6.5, 9.0, "Then wait for the water to drip through.")]
    worker = Worker(home, speech=RecordedSpeech(spans), vision=RecordedVision(),
                    recipe={**RECIPE, "segment_target_seconds": 1.0})
    project = worker.create_project("Water filter tutorial")
    outcome = worker.import_clip(project["id"], make_clip(tmp_path / "a-roll.mp4", seconds=10.0))
    [hit] = payload(call(home, ("search_footage", {"project_id": project["id"], "query": "upper tank"}))[0])["results"][:1]

    [ctx] = (payload(r) for r in call(home, ("get_segment_context", {"segment_id": hit["segment_id"],
                                                                     "window_seconds": 5})))

    assert ctx["segment"]["segment_id"] == hit["segment_id"]
    assert ctx["segment"]["clip_id"] == outcome["clip_id"] and ctx["segment"]["project_id"] == project["id"]
    assert ctx["segment"]["original_filename"] == "a-roll.mp4"
    assert (ctx["segment"]["start"], ctx["segment"]["end"]) == (hit["start"], hit["end"])
    assert ctx["status"] == "ready" and ctx["revision"] == outcome["revision"]
    lines = [(t["text"], t["in_segment"]) for t in ctx["transcript"]]
    assert lines == [("First, fill the upper chamber.", False),
                     ("Actually, I mean the upper tank, not the chamber.", True),
                     ("Then wait for the water to drip through.", False)]
    assert all(0 <= t["start"] < t["end"] <= 10.1 for t in ctx["transcript"])
    [*observations] = ctx["observations"]
    assert observations and all(o["frame_id"].startswith("frm_") and hit["start"] <= o["time"] <= hit["end"]
                                for o in observations)
    assert ctx["interpretation"]["text"] == "The speaker introduces the test pattern."
    assert ctx["interpretation"]["model"] == "fixture"
    cited = set(ctx["interpretation"]["evidence_ids"])
    assert cited and cited <= {t["transcript_id"] for t in ctx["transcript"]} | {o["frame_id"] for o in observations}
    assert ctx["provenance"]["speech"]["model"] == "fixture" and ctx["provenance"]["vision"]["model"] == "fixture"
    assert ctx["provenance"]["recipe_version"] == RECIPE["version"]
    assert ctx["provenance"]["speech_language"] == "en"
    assert ctx["not_yet_available"] == ["creator_notes"]  # absent, not "none exist"
    assert "creator_notes" not in ctx
    [correction] = ctx["relationships"]
    assert (correction["kind"], correction["related_as"]) == ("spoken_correction", "earlier_statement")
    assert correction["excerpt"] == "First, fill the upper chamber."


def test_unknown_references_are_reported_not_invented(home, clip):
    imported(home, clip)

    [ctx, search] = call(home, ("get_segment_context", {"segment_id": "seg_doesnotexist"}),
                         ("search_footage", {"project_id": "prj_doesnotexist", "query": "filter"}))

    assert ctx.is_error and "seg_doesnotexist" in ctx.content[0].text
    assert search.is_error and "prj_doesnotexist" in search.content[0].text


def test_preview_is_a_bounded_sampled_frame_with_its_source_reference(home, clip):
    import base64
    import subprocess

    project, outcome = imported(home, clip)
    [hit] = payload(call(home, ("search_footage", {"project_id": project["id"], "query": "colour bars"}))[0])["results"]
    ctx = payload(call(home, ("get_segment_context", {"segment_id": hit["segment_id"]}))[0])
    second = ctx["observations"][-1]["frame_id"]

    default, chosen, wrong = call(home, ("get_segment_preview", {"segment_id": hit["segment_id"]}),
                                  ("get_segment_preview", {"segment_id": hit["segment_id"], "frame_id": second}),
                                  ("get_segment_preview", {"segment_id": hit["segment_id"], "frame_id": "frm_nope"}))

    for res in (default, chosen):
        meta = payload(res)
        [image] = [c for c in res.content if c.type == "image"]
        assert image.mime_type == "image/jpeg"
        data = base64.b64decode(image.data)
        assert data[:2] == b"\xff\xd8" and len(data) == meta["frame"]["bytes"] <= 200_000
        assert meta["frame"]["frame_id"] in {o["frame_id"] for o in ctx["observations"]}
        assert hit["start"] <= meta["frame"]["time"] <= hit["end"]
        assert meta["segment"]["clip_id"] == outcome["clip_id"]
        assert meta["segment"]["original_filename"] == "talking-head.mp4"
        assert meta["frame"]["width"] <= 512
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width", "-of", "csv=p=0", "-"],
                               input=data, capture_output=True, check=True)
        assert int(probe.stdout) == meta["frame"]["width"]
    assert payload(chosen)["frame"]["frame_id"] == second
    assert wrong.is_error and "frm_nope" in wrong.content[0].text


def test_media_resolution_validates_ranges_and_refuses_missing_or_changed_sources(home, clip):
    project, outcome = imported(home, clip)
    [hit] = payload(call(home, ("search_footage", {"project_id": project["id"], "query": "colour bars"}))[0])["results"]
    sid = hit["segment_id"]

    default, sub, beyond, backwards = call(
        home, ("resolve_media", {"segment_id": sid}),
        ("resolve_media", {"segment_id": sid, "start": 4.2, "end": 8.9}),
        ("resolve_media", {"segment_id": sid, "start": 2.0, "end": 99.0}),
        ("resolve_media", {"segment_id": sid, "start": 5.0, "end": 3.0}))

    media = payload(default)
    assert media["available"] is True and media["state"] == "available"
    assert media["path"] == str(clip) and media["file_url"] == clip.as_uri()
    assert (media["start"], media["end"]) == (hit["start"], hit["end"])
    assert 11.5 <= media["duration"] <= 12.5
    assert media["clip_id"] == outcome["clip_id"] and media["original_filename"] == "talking-head.mp4"
    assert "permission" in media["note"]
    assert (payload(sub)["start"], payload(sub)["end"]) == (4.2, 8.9)
    assert beyond.is_error and "duration" in beyond.content[0].text
    assert backwards.is_error

    import sqlite3
    with sqlite3.connect(home / "index.sqlite") as db:  # e.g. a refresh that failed after indexing
        db.execute("UPDATE source_clips SET status='failed'")
    unchanged_but_failed = payload(call(home, ("resolve_media", {"segment_id": sid}))[0])
    assert unchanged_but_failed["available"] is False and unchanged_but_failed["state"] == "failed"
    assert "path" not in unchanged_but_failed
    with sqlite3.connect(home / "index.sqlite") as db:
        db.execute("UPDATE source_clips SET status='ready'")

    with clip.open("ab") as f:  # the creator re-exported or edited the file in place
        f.write(b"\0" * 64)
    changed = payload(call(home, ("resolve_media", {"segment_id": sid}))[0])
    assert changed["available"] is False and changed["state"] == "changed"
    assert "path" not in changed and "file_url" not in changed

    clip.rename(clip.with_name("moved.mp4"))
    missing = payload(call(home, ("resolve_media", {"segment_id": sid}))[0])
    assert missing["available"] is False and missing["state"] == "missing"
    assert "path" not in missing and missing["original_filename"] == "talking-head.mp4"


def test_stdout_carries_only_protocol_messages(home, clip):
    import subprocess

    imported(home, clip)
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "raw", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_project_overview", "arguments": {}}},
    ]
    proc = subprocess.Popen([str(SERVER), "--home", str(home)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    replies = []
    for request in requests:
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        if "id" in request:
            replies.append(json.loads(proc.stdout.readline()))  # every stdout line must be JSON-RPC
    proc.stdin.close()
    replies += [json.loads(line) for line in proc.stdout]
    stderr = proc.stderr.read()
    proc.wait(timeout=10)

    assert all(r["jsonrpc"] == "2.0" for r in replies)
    by_id = {r["id"]: r for r in replies if "id" in r}
    tools = {t["name"]: t for t in by_id[2]["result"]["tools"]}
    assert set(tools) == {"get_project_overview", "search_footage", "get_segment_context",
                          "get_segment_preview", "resolve_media"}
    assert all(t["annotations"]["readOnlyHint"] is True for t in tools.values())
    assert not by_id[3]["result"].get("isError")
    assert "clipcon-mcp" in stderr


def test_the_apps_connection_check_runs_a_real_mcp_session_and_reports_codex_setup(home, clip, tmp_path):
    import os
    import shlex
    import subprocess

    project, _ = imported(home, clip)
    fake_codex = tmp_path / "codex"  # stands in for an installed Codex without Clipcon registered
    fake_codex.write_text("#!/bin/sh\n[ \"$1\" = --version ] && echo 'codex-cli 9.9.9' && exit 0\n"
                          "echo \"Error: No MCP server named 'clipcon' found.\" >&2; exit 1\n")
    fake_codex.chmod(0o755)

    proc = subprocess.run([str(SERVER.with_name("clipcon-worker")), "--home", str(home), "mcp-status"],
                          capture_output=True, text=True, env={**os.environ, "CLIPCON_CODEX": str(fake_codex)})

    status = json.loads(proc.stdout.splitlines()[-1])["mcp"]
    assert status["ok"] is True
    assert status["tools"] == ["get_project_overview", "search_footage", "get_segment_context",
                               "get_segment_preview", "resolve_media"]
    assert status["project_count"] == 1
    assert status["server_command"] == [str(SERVER), "--home", str(home)]
    assert status["add_command"] == f"codex mcp add clipcon -- {shlex.quote(str(SERVER))} --home {shlex.quote(str(home))}"
    assert status["codex"] == {"path": str(fake_codex), "version": "codex-cli 9.9.9", "registered": False,
                               "registered_command": None, "error": None}
    assert status["sdk_version"] and status["protocol_version"]
