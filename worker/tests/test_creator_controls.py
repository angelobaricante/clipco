"""Creator notes and exclusions, written through the worker CLI the app uses, then read through MCP as Codex would."""

import json
import subprocess
import sys
from pathlib import Path

from test_mcp import call, payload
from test_project import line_project

WORKER = Path(sys.executable).parent / "clipco-worker"


def worker_cli(home: Path, *args: str) -> dict:
    proc = subprocess.run([str(WORKER), "--home", str(home), *args], capture_output=True, text=True, timeout=30)
    event = json.loads(proc.stdout.splitlines()[-1])
    assert event["event"] == "result", proc.stderr
    return event


def clips_by_name(worker, project_id: str) -> dict:
    return {c["original_filename"]: c for c in worker.snapshot(project_id)["clips"]}


def test_a_creator_note_is_returned_as_creator_context_next_to_the_unchanged_evidence(home, tmp_path):
    project, worker = line_project(home, tmp_path)
    broll = clips_by_name(worker, project["id"])["broll-1-pour.mp4"]
    segment = broll["segments"][0]["id"]
    before = payload(call(home, ("get_segment_context", {"segment_id": segment}))[0])

    worker_cli(home, "set-note", "--clip", broll["id"], "--text", "Shot on the balcony; the jug holds 2 litres.")

    ctx = payload(call(home, ("get_segment_context", {"segment_id": segment}))[0])
    [note] = ctx["creator_notes"]
    assert note["text"] == "Shot on the balcony; the jug holds 2 litres."
    assert note["clip_id"] == broll["id"] and note["updated_at"] > 0
    assert "creator" in ctx["provenance"]["creator_notes"]
    assert "not_yet_available" not in ctx
    # The note augments the saved evidence; it replaces none of it.
    assert (ctx["transcript"], ctx["observations"], ctx["interpretation"]) == (
        before["transcript"], before["observations"], before["interpretation"])


def test_search_finds_footage_by_what_only_the_creator_noted(home, tmp_path):
    project, worker = line_project(home, tmp_path)
    broll = clips_by_name(worker, project["id"])["broll-3-cartridge.mp4"]
    query = {"project_id": project["id"], "query": "sponsor product"}
    assert payload(call(home, ("search_footage", query))[0])["results"] == []

    worker_cli(home, "set-note", "--clip", broll["id"], "--text", "This is the sponsor product; show its logo.")

    [hit] = payload(call(home, ("search_footage", query))[0])["results"]
    assert hit["clip_id"] == broll["id"]
    assert (hit["evidence_basis"], hit["excerpt"]) == ("creator_note", "This is the sponsor product; show its logo.")

    worker_cli(home, "set-note", "--clip", broll["id"], "--text", "  ")  # cleared
    assert payload(call(home, ("search_footage", query))[0])["results"] == []
    ctx = payload(call(home, ("get_segment_context", {"segment_id": hit["segment_id"]}))[0])
    assert ctx["creator_notes"] == []


def test_an_excluded_clip_leaves_new_default_searches_until_it_is_included_again(home, tmp_path):
    from clipco_worker.pipeline import Worker

    project, worker = line_project(home, tmp_path)
    pid = project["id"]
    broll = clips_by_name(worker, pid)["broll-1-pour.mp4"]
    pour = {"project_id": pid, "query": "murky water jug"}
    explained = {"project_id": pid, "query": "pour the dirty water into the top bucket"}
    [retrieved] = [r for r in payload(call(home, ("search_footage", pour))[0])["results"]
                   if r["clip_id"] == broll["id"]]  # context the agent already holds
    held = payload(call(home, ("get_segment_context", {"segment_id": retrieved["segment_id"]}))[0])

    worker_cli(home, "set-excluded", "--project", pid, "--excluded", "yes", broll["id"])

    found, a_roll, overview, ctx, everything = (payload(r) for r in call(
        home, ("search_footage", pour), ("search_footage", explained),
        ("get_project_overview", {"project_id": pid}),
        ("get_segment_context", {"segment_id": retrieved["segment_id"]}),
        ("search_footage", {**pour, "include_excluded": True})))
    assert all(r["clip_id"] != broll["id"] for r in found["results"])
    assert all(rel["clip_id"] != broll["id"] for r in a_roll["results"] for rel in r["relationships"])
    [listed] = [c for c in overview["clips"] if c["clip_id"] == broll["id"]]
    assert listed["excluded"] is True and listed["status"] == "ready"
    # What the agent already retrieved still resolves; it is marked excluded, not withdrawn or rewritten.
    assert ctx["excluded"] is True and "not revoked" in ctx["exclusion_note"]
    assert held["excluded"] is False
    assert {k: v for k, v in ctx.items() if k not in ("excluded", "exclusion_note")} == {
        k: v for k, v in held.items() if k not in ("excluded", "exclusion_note")}
    assert {r["clip_id"] for r in everything["results"]} >= {broll["id"]}
    assert all(r["excluded"] == (r["clip_id"] == broll["id"]) for r in everything["results"])

    # The choice persists in the index (a new worker sees it), and including the clip restores it.
    assert clips_by_name(Worker(home, worker.speech, worker.vision), pid)["broll-1-pour.mp4"]["excluded"] is True
    worker_cli(home, "set-excluded", "--project", pid, "--excluded", "no", broll["id"])
    again = payload(call(home, ("search_footage", pour))[0])
    assert retrieved["segment_id"] in {r["segment_id"] for r in again["results"]}
    assert any(rel["clip_id"] == broll["id"] for r in payload(call(home, ("search_footage", explained))[0])["results"]
               for rel in r["relationships"])


def test_the_apps_snapshot_shows_notes_exclusions_and_suggested_relationships_for_review(home, tmp_path):
    project, worker = line_project(home, tmp_path)
    pid = project["id"]
    clips = clips_by_name(worker, pid)
    worker_cli(home, "set-excluded", "--project", pid, "--excluded", "yes", clips["broll-1-pour.mp4"]["id"])
    worker_cli(home, "set-note", "--clip", clips["a-roll.mp4"]["id"], "--text", "Use the second take.")

    snapshot = {c["original_filename"]: c for c in worker_cli(home, "snapshot", "--project", pid)["snapshot"]["clips"]}

    a_roll = snapshot["a-roll.mp4"]
    assert a_roll["note"]["text"] == "Use the second take." and a_roll["excluded"] is False
    assert snapshot["broll-1-pour.mp4"]["excluded"] is True and snapshot["broll-1-pour.mp4"]["note"] is None
    related = [r for s in a_roll["segments"] for r in s["relationships"]]
    kinds = {(r["kind"], r["related_as"]) for r in related}
    assert {("spoken_correction", "earlier_statement"), ("spoken_correction", "correction")} <= kinds
    # The creator still sees suggestions that point at an excluded clip, marked as such.
    to_excluded = [r for r in related if r["kind"] == "supporting_broll"
                   and r["clip_id"] == clips["broll-1-pour.mp4"]["id"]]
    assert to_excluded and all(r["excluded"] is True and r["suggested"] is True for r in to_excluded)
    assert all(r["excluded"] is False for r in related if r["clip_id"] == a_roll["id"])


def test_notes_and_exclusions_can_be_saved_while_other_footage_is_being_analysed(home, tmp_path):
    from conftest import ScriptedSpeech, ScriptedVision
    from test_project import A_ROLL, B_ROLL, corpus

    from clipco_worker.pipeline import Worker

    folder = corpus(tmp_path / "shoot")
    vision = ScriptedVision(B_ROLL)
    worker = Worker(home, speech=ScriptedSpeech(A_ROLL), vision=vision)
    project = worker.create_project("Gravity filter tutorial")
    during = {}

    def edit_while_describing(request):  # the indexer is mid-import in this process
        if request.original_filename == "broll-2-drip.mp4" and not during:
            pour = clips_by_name(worker, project["id"])["broll-1-pour.mp4"]
            during["note"] = worker_cli(home, "set-note", "--clip", pour["id"], "--text", "Use the slow pour.")
            during["excluded"] = worker_cli(home, "set-excluded", "--project", project["id"], "--excluded", "yes",
                                            pour["id"])
    vision.on_describe = edit_while_describing

    worker.import_folder(project["id"], folder)

    assert during["note"]["note"]["text"] == "Use the slow pour." and during["excluded"]["excluded"] is True
    pour = clips_by_name(worker, project["id"])["broll-1-pour.mp4"]
    assert pour["status"] == "ready" and pour["excluded"] is True and pour["note"]["text"] == "Use the slow pour."
