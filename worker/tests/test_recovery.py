"""Recovering failed, missing, and changed footage: driven through the worker, observed through MCP as Codex would."""

import os
import shutil
from pathlib import Path

from conftest import ScriptedSpeech, ScriptedVision, make_clip, sha256
from test_creator_controls import clips_by_name, worker_cli
from test_mcp import call, payload
from test_project import A_ROLL, B_ROLL, corpus, line_project

from clipcon_worker.pipeline import Worker


def originals(folder: Path) -> dict[str, str]:
    return {p.name: sha256(p) for p in sorted(folder.iterdir()) if p.is_file()}


def overview(home: Path, pid: str) -> dict:
    out = payload(call(home, ("get_project_overview", {"project_id": pid}))[0])
    return {c["original_filename"]: c for c in out["clips"]} | {"_counts": out["status_counts"]}


def test_a_failed_clip_is_retried_in_place_without_disturbing_the_rest(home, tmp_path):
    from clipcon_worker.vision import ServiceUnavailable

    folder = corpus(tmp_path / "shoot")
    before = originals(folder)
    vision = ScriptedVision(B_ROLL, fail={"broll-2-drip.mp4"})
    worker = Worker(home, speech=ScriptedSpeech(A_ROLL), vision=vision)
    pid = worker.create_project("Gravity filter tutorial")["id"]
    worker.import_folder(pid, folder)
    clips = clips_by_name(worker, pid)
    drip = clips["broll-2-drip.mp4"]
    assert drip["status"] == "failed" and drip["segments"] == []
    worker_cli(home, "set-note", "--clip", drip["id"], "--text", "The drip shot matters most.")
    worker_cli(home, "set-excluded", "--project", pid, "--excluded", "yes", drip["id"])
    good = {n: (c["revision"], [s["id"] for s in c["segments"]]) for n, c in clips.items() if n != drip["original_filename"]}

    # The model service is down: nothing about the clip changes, and the error says why.
    def down(request):
        raise ServiceUnavailable("Ollama is not running")
    vision.on_describe = down
    try:
        worker.retry(pid, [drip["id"]])
    except ServiceUnavailable:
        pass
    assert clips_by_name(worker, pid)["broll-2-drip.mp4"]["status"] == "failed"
    vision.on_describe = lambda request: None

    vision.fail.clear()
    stages = []
    outcome = worker.retry(pid, [drip["id"]], progress=lambda stage, detail: stages.append((stage, detail["clip_id"])))

    assert outcome["clips"] == [{"clip_id": drip["id"], "original_filename": "broll-2-drip.mp4", "status": "ready",
                                 "error": None}]
    assert [s for s, _ in stages][:3] == ["fingerprinting", "probing", "sampling_frames"]
    assert ("describing", drip["id"]) in stages and stages[-1] == ("ready", drip["id"])
    after = clips_by_name(worker, pid)
    retried = after["broll-2-drip.mp4"]
    assert retried["id"] == drip["id"] and retried["segments"] and retried["revision"] == 1
    assert retried["note"]["text"] == "The drip shot matters most." and retried["excluded"] is True
    # The other clips' published context was never touched.
    assert {n: (c["revision"], [s["id"] for s in c["segments"]]) for n, c in after.items()
            if n != "broll-2-drip.mp4"} == good
    state = overview(home, pid)
    assert state["_counts"] == {"ready": 4} and state["broll-2-drip.mp4"]["error"] is None
    assert "status_note" not in state["broll-2-drip.mp4"]
    assert originals(folder) == before  # indexing, notes, exclusion and retry left every original unchanged


def test_a_missing_original_is_reported_everywhere_and_restored_without_losing_context(home, tmp_path):
    project, worker = line_project(home, tmp_path)
    pid, folder = project["id"], tmp_path / "shoot"
    pour = clips_by_name(worker, pid)["broll-1-pour.mp4"]
    segment = pour["segments"][0]["id"]
    worker_cli(home, "set-note", "--clip", pour["id"], "--text", "Slow pour, use for the intro.")
    before = originals(folder)
    elsewhere = tmp_path / "external-drive"
    elsewhere.mkdir()
    moved = Path(shutil.move(folder / "broll-1-pour.mp4", elsewhere / "pour-take-2.mp4"))

    # Before Clipcon re-checks anything, MCP already refuses to treat the cached description as accessible media.
    state, found, media = (payload(r) for r in call(
        home, ("get_project_overview", {"project_id": pid}),
        ("search_footage", {"project_id": pid, "query": "murky water jug"}),
        ("resolve_media", {"segment_id": segment})))
    [listed] = [c for c in state["clips"] if c["clip_id"] == pour["id"]]
    assert listed["status"] == "missing" and "restores or locates" in listed["status_note"]
    [hit] = [r for r in found["results"] if r["clip_id"] == pour["id"]]
    assert hit["status"] == "missing" and hit["status_note"]
    assert media["available"] is False and media["state"] == "missing" and "path" not in media
    assert media["index_status"] == "missing"  # one answer per clip, whichever tool asks
    app ={c["original_filename"]: c for c in worker_cli(home, "snapshot", "--project", pid)["snapshot"]["clips"]}
    assert app["broll-1-pour.mp4"]["status"] == "missing" and "Move it back" in app["broll-1-pour.mp4"]["error"]

    # A retry cannot analyse what is not there; it says what to do instead.
    [retried] = worker_cli(home, "retry", "--project", pid, pour["id"])["clips"]
    assert retried["status"] == "missing" and str(folder / "broll-1-pour.mp4") in retried["error"]

    # Another file is not accepted as this clip: its context and relationships stay with the original footage.
    try:
        worker.relink(pid, pour["id"], folder / "broll-3-cartridge.mp4")
        raise AssertionError("relinked to different footage")
    except ValueError as e:
        assert "not the same footage" in str(e) or "already clip" in str(e)
    impostor = make_clip(elsewhere / "impostor.mp4", seconds=6.0, audio=False)
    with open(impostor, "ab") as f:
        f.write(b"different bytes")
    try:
        worker.relink(pid, pour["id"], impostor)
        raise AssertionError("relinked to different footage")
    except ValueError as e:
        assert "not the same footage" in str(e)

    [relinked] = worker.relink(pid, pour["id"], moved)["clips"]
    assert relinked == {"clip_id": pour["id"], "original_filename": "pour-take-2.mp4", "status": "ready",
                        "error": None}
    ctx, media = (payload(r) for r in call(home, ("get_segment_context", {"segment_id": segment}),
                                           ("resolve_media", {"segment_id": segment})))
    assert ctx["status"] == "ready" and ctx["creator_notes"][0]["text"] == "Slow pour, use for the intro."
    assert ctx["segment"]["original_filename"] == "pour-take-2.mp4"
    assert media["available"] is True and media["path"] == str(moved)
    assert sha256(moved) == before["broll-1-pour.mp4"]

    # Moving it back is noticed by a source check, and the clip is ready at its first place again.
    shutil.move(moved, folder / "broll-1-pour.mp4")
    assert overview(home, pid)["pour-take-2.mp4"]["status"] == "missing"
    worker.check_sources(pid)
    assert overview(home, pid)["pour-take-2.mp4"]["status"] == "missing"  # recorded, until it is located
    worker.relink(pid, pour["id"], folder / "broll-1-pour.mp4")
    assert overview(home, pid)["_counts"] == {"ready": 4}
    assert originals(folder) == before


def test_changed_content_is_stale_until_refreshed_and_old_ids_stay_attributable(home, tmp_path):
    project, worker = line_project(home, tmp_path)
    pid, folder = project["id"], tmp_path / "shoot"
    clips = clips_by_name(worker, pid)
    cartridge = clips["broll-3-cartridge.mp4"]
    held = cartridge["segments"][0]["id"]  # context an agent already retrieved
    worker_cli(home, "set-note", "--clip", cartridge["id"], "--text", "Sponsor's cartridge.")
    worker_cli(home, "set-excluded", "--project", pid, "--excluded", "yes", cartridge["id"])
    untouched = {n: [s["id"] for s in c["segments"]] for n, c in clips.items() if n != "broll-3-cartridge.mp4"}

    # Touched but identical: flagged by the quick check, then confirmed unchanged by the content check.
    path = folder / "broll-3-cartridge.mp4"
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 60))
    assert overview(home, pid)["broll-3-cartridge.mp4"]["status"] == "stale"
    worker.check_sources(pid)
    assert overview(home, pid)["broll-3-cartridge.mp4"]["status"] == "ready"

    make_clip(path, seconds=8.0, audio=False)  # re-exported in place: different footage at the same path
    state, ctx, media = (payload(r) for r in call(
        home, ("get_project_overview", {"project_id": pid}), ("get_segment_context", {"segment_id": held}),
        ("resolve_media", {"segment_id": held})))
    [listed] = [c for c in state["clips"] if c["clip_id"] == cartridge["id"]]
    assert listed["status"] == "stale" and "do not rely" in listed["status_note"]
    assert ctx["status"] == "stale" and ctx["status_note"]
    assert media["available"] is False and "path" not in media

    worker.check_sources(pid)
    stored = clips_by_name(worker, pid)["broll-3-cartridge.mp4"]
    assert stored["status"] == "stale" and "content changed" in stored["error"]
    assert [s["id"] for s in stored["segments"]] == [held]  # still attributable, not silently replaced

    calls = worker.vision.calls
    worker.retry(pid, [cartridge["id"]])
    refreshed = clips_by_name(worker, pid)["broll-3-cartridge.mp4"]
    assert worker.vision.calls > calls and refreshed["status"] == "ready" and refreshed["revision"] == 2
    assert refreshed["id"] == cartridge["id"] and held not in [s["id"] for s in refreshed["segments"]]
    assert refreshed["note"]["text"] == "Sponsor's cartridge." and refreshed["excluded"] is True
    assert 7.5 <= refreshed["duration"] <= 8.5
    assert {n: [s["id"] for s in c["segments"]] for n, c in clips_by_name(worker, pid).items()
            if n != "broll-3-cartridge.mp4"} == untouched

    [old] = call(home, ("get_segment_context", {"segment_id": held}))
    assert old.is_error
    assert "re-analysed" in old.content[0].text and cartridge["id"] in old.content[0].text


def test_changed_analysis_settings_mark_context_stale_until_it_is_refreshed(home, tmp_path):
    project, worker = line_project(home, tmp_path)
    pid = project["id"]
    calls = worker.vision.calls

    same = Worker(home, speech=worker.speech, vision=worker.vision, recipe=worker.recipe)
    assert {c["status"] for c in same.check_sources(pid)["clips"]} == {"ready"}
    assert worker.vision.calls == calls  # checking is not re-analysing

    changed = Worker(home, speech=worker.speech, vision=worker.vision,
                     recipe={**worker.recipe, "frames_per_segment": 1})
    outcome = changed.check_sources(pid)["clips"]
    assert {c["status"] for c in outcome} == {"stale"}
    assert all("analysis recipe" in c["error"] for c in outcome)
    assert overview(home, pid)["_counts"] == {"stale": 4}
    found = payload(call(home, ("search_footage", {"project_id": pid, "query": "two litres per minute"}))[0])
    assert found["results"] and all(r["status"] == "stale" and r["status_note"] for r in found["results"])

    a_roll = clips_by_name(worker, pid)["a-roll.mp4"]["id"]
    from clipcon_worker.vision import ServiceUnavailable

    def down(request):
        raise ServiceUnavailable("Ollama is not running")
    worker.vision.on_describe = down
    try:
        changed.retry(pid, [a_roll])
        raise AssertionError("retried without the model service")
    except ServiceUnavailable:
        pass
    assert overview(home, pid)["a-roll.mp4"]["status"] == "stale"  # an outage does not downgrade saved context
    worker.vision.on_describe = lambda request: None
    changed.retry(pid, [a_roll])
    state = overview(home, pid)
    assert state["a-roll.mp4"]["status"] == "ready" and state["_counts"] == {"ready": 1, "stale": 3}
    assert worker.vision.calls > calls

