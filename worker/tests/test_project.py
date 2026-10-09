"""A whole Project: a folder of A-roll and B-roll imported through the worker, queried through MCP."""

from pathlib import Path

from conftest import ScriptedSpeech, ScriptedVision, make_clip
from test_mcp import call, payload

from clipcon_worker.pipeline import Worker
from clipcon_worker.speech import TranscriptSpan

A_ROLL = [
    TranscriptSpan(0.0, 4.0, "Today we build a gravity water filter from two buckets."),
    TranscriptSpan(4.5, 9.0, "Pour the dirty water into the top bucket."),
    TranscriptSpan(9.5, 13.0, "The filter holds two litres per hour."),
    TranscriptSpan(13.5, 17.5, "Actually, I mean two litres per minute, not per hour."),
    TranscriptSpan(18.0, 22.0, "Pour the dirty water into the top bucket."),
]

B_ROLL = {
    "broll-1-pour.mp4": "Hands pour murky water from a jug into a white bucket.",
    "broll-2-drip.mp4": "Clear water drips from a spigot into a glass.",
    "broll-3-cartridge.mp4": "Close-up of a ceramic filter cartridge on a table.",
}


def corpus(folder: Path) -> Path:
    folder.mkdir()
    make_clip(folder / "a-roll.mp4", seconds=23.0)
    for name in B_ROLL:
        make_clip(folder / name, seconds=6.0, audio=False)
    (folder / "notes.txt").write_text("not footage")
    (folder / ".hidden.mp4").write_bytes(b"")
    return folder


def test_a_folder_becomes_one_project_and_a_failed_clip_preserves_the_rest(home, tmp_path):
    folder = corpus(tmp_path / "shoot")
    worker = Worker(home, speech=ScriptedSpeech(A_ROLL), vision=ScriptedVision(B_ROLL, fail={"broll-2-drip.mp4"}))
    project = worker.create_project("Gravity filter tutorial")

    outcome = worker.import_folder(project["id"], folder)

    clips = {c["original_filename"]: c for c in payload(
        call(home, ("get_project_overview", {"project_id": project["id"]}))[0])["clips"]}
    assert set(clips) == {"a-roll.mp4", *B_ROLL}  # only video files, no hidden ones
    assert clips["broll-2-drip.mp4"]["status"] == "failed" and clips["broll-2-drip.mp4"]["segment_count"] == 0
    assert "broll-2-drip.mp4" in clips["broll-2-drip.mp4"]["error"]
    ready = {n for n, c in clips.items() if c["status"] == "ready"}
    assert ready == {"a-roll.mp4", "broll-1-pour.mp4", "broll-3-cartridge.mp4"}
    assert clips["a-roll.mp4"]["role"] == "a-roll" and clips["broll-1-pour.mp4"]["role"] == "b-roll"
    assert {r["original_filename"]: r["status"] for r in outcome["clips"]} == {
        n: c["status"] for n, c in clips.items()}


def test_completed_clips_stay_retrievable_while_others_are_processing(home, tmp_path):
    folder = corpus(tmp_path / "shoot")
    vision = ScriptedVision(B_ROLL)
    worker = Worker(home, speech=ScriptedSpeech(A_ROLL), vision=vision)
    project = worker.create_project("Gravity filter tutorial")
    pid = project["id"]
    during = {}

    def observe(request):
        if request.original_filename == "broll-2-drip.mp4" and not during:
            during["overview"], during["search"] = (payload(r) for r in call(
                home, ("get_project_overview", {"project_id": pid}),
                ("search_footage", {"project_id": pid, "query": "water"})))
    vision.on_describe = observe

    worker.import_folder(pid, folder)

    states = {c["original_filename"]: (c["status"], c["segment_count"]) for c in during["overview"]["clips"]}
    assert states["a-roll.mp4"][0] == "ready" and states["broll-1-pour.mp4"][0] == "ready"
    assert states["broll-2-drip.mp4"] == ("indexing", 0)  # being described: nothing published yet
    assert states["broll-3-cartridge.mp4"] == ("pending", 0)
    stage = {c["original_filename"]: c["stage"] for c in during["overview"]["clips"]}
    assert stage["broll-2-drip.mp4"] == "describing" and stage["a-roll.mp4"] is None
    assert during["overview"]["status_counts"] == {"ready": 2, "indexing": 1, "pending": 1}
    found = {r["original_filename"] for r in during["search"]["results"]}
    assert "a-roll.mp4" in found and "broll-1-pour.mp4" in found
    assert "broll-2-drip.mp4" not in found  # its partial analysis is not ready evidence
    assert all(r["status"] == "ready" for r in during["search"]["results"])


def test_reimporting_unchanged_footage_reuses_context_without_inference_or_unready_states(home, tmp_path):
    folder = corpus(tmp_path / "shoot")
    speech, vision = ScriptedSpeech(A_ROLL), ScriptedVision(B_ROLL)
    worker = Worker(home, speech=speech, vision=vision)
    project = worker.create_project("Gravity filter tutorial")
    worker.import_folder(project["id"], folder)
    before = payload(call(home, ("get_project_overview", {"project_id": project["id"]}))[0])
    calls = (speech.calls, vision.calls)
    seen = {}

    def observe(stage, detail):
        if stage == "fingerprinting" and not seen:  # while the first source is being checked
            seen.update(payload(call(home, ("get_project_overview", {"project_id": project["id"]}))[0]))

    again = Worker(home, speech=speech, vision=vision).import_folder(project["id"], folder, progress=observe)

    assert (speech.calls, vision.calls) == calls
    assert all(c["status"] == "ready" for c in again["clips"])
    assert seen and all(c["status"] == "ready" for c in seen["clips"])  # never withdrawn while checking
    assert payload(call(home, ("get_project_overview", {"project_id": project["id"]}))[0]) == before


def line_project(home: Path, tmp_path: Path) -> tuple[dict, Worker]:
    """The tutorial folder analysed with one Segment per spoken line, so related lines land in different Segments."""
    from clipcon_worker.pipeline import RECIPE

    folder = corpus(tmp_path / "shoot")
    worker = Worker(home, speech=ScriptedSpeech(A_ROLL), vision=ScriptedVision(B_ROLL),
                    recipe={**RECIPE, "segment_target_seconds": 1.0})
    project = worker.create_project("Gravity filter tutorial")
    worker.import_folder(project["id"], folder)
    return project, worker


def test_a_spoken_correction_is_linked_to_the_earlier_statement_without_erasing_it(home, tmp_path):
    project, _ = line_project(home, tmp_path)
    pid = project["id"]

    correction, earlier = (payload(r) for r in call(
        home, ("search_footage", {"project_id": pid, "query": "two litres per minute"}),
        ("search_footage", {"project_id": pid, "query": "holds two litres per hour"})))

    top = correction["results"][0]
    assert top["excerpt"] == "Actually, I mean two litres per minute, not per hour."
    [link] = [r for r in top["relationships"] if r["kind"] == "spoken_correction"]
    assert link["related_as"] == "earlier_statement"
    assert link["excerpt"] == "The filter holds two litres per hour."
    assert link["suggested"] is True
    assert 9.5 - 1e-6 <= link["start"] < link["end"] <= 13.5 + 1e-6  # the earlier line's own Segment

    # The earlier statement stays in the index, pointing forward to its correction.
    original = earlier["results"][0]
    assert original["excerpt"] == "The filter holds two litres per hour."
    assert original["segment_id"] == link["segment_id"]
    [back] = [r for r in original["relationships"] if r["kind"] == "spoken_correction"]
    assert back["related_as"] == "correction" and back["segment_id"] == top["segment_id"]

    ctx = payload(call(home, ("get_segment_context", {"segment_id": top["segment_id"], "window_seconds": 0}))[0])
    [rel] = [r for r in ctx["relationships"] if r["kind"] == "spoken_correction"]
    spoken = {e["text"]: e for e in rel["evidence"]}
    assert set(spoken) == {"The filter holds two litres per hour.",
                           "Actually, I mean two litres per minute, not per hour."}
    assert all(e["transcript_id"].startswith("trn_") and 0 <= e["start"] < e["end"] for e in spoken.values())
    assert "preferred" not in rel


def test_repeated_takes_are_related_without_choosing_one(home, tmp_path):
    project, _ = line_project(home, tmp_path)

    found = payload(call(home, ("search_footage", {"project_id": project["id"],
                                                   "query": "pour the dirty water into the top bucket"}))[0])

    takes = [r for r in found["results"] if r["excerpt"] == "Pour the dirty water into the top bucket."]
    assert [(t["start"] < 9.0, t["start"] >= 18.0 - 1e-6) for t in takes] == [(True, False), (False, True)]
    first, second = takes
    [link] = [r for r in first["relationships"] if r["kind"] == "repeated_take"]
    [back] = [r for r in second["relationships"] if r["kind"] == "repeated_take"]
    assert link["segment_id"] == second["segment_id"] and back["segment_id"] == first["segment_id"]
    assert link["related_as"] == back["related_as"] == "other_take"
    assert first["score"] == second["score"]  # repetition alone does not rank one take above the other
    assert "preferred" not in link and "preferred" not in back
    # Two different lines are not takes of each other.
    assert not any(r["kind"] == "repeated_take" for t in found["results"] if t not in takes
                   for r in t["relationships"])


def test_supporting_broll_is_suggested_from_observed_footage_not_invented(home, tmp_path):
    project, _ = line_project(home, tmp_path)
    pid = project["id"]

    explanation, footage = (payload(r) for r in call(
        home, ("search_footage", {"project_id": pid, "query": "pour the dirty water into the top bucket"}),
        ("search_footage", {"project_id": pid, "query": "murky water jug"})))

    a_roll = explanation["results"][0]
    assert a_roll["original_filename"] == "a-roll.mp4"
    suggested = [r for r in a_roll["relationships"] if r["kind"] == "supporting_broll"]
    assert suggested[0]["original_filename"] == "broll-1-pour.mp4"
    assert suggested[0]["related_as"] == "suggested_broll" and suggested[0]["suggested"] is True
    assert suggested[0]["excerpt"] == B_ROLL["broll-1-pour.mp4"]  # what was observed in its sampled frames
    assert "pour" in suggested[0]["basis"] and "bucket" in suggested[0]["basis"]
    assert "broll-3-cartridge.mp4" not in {r["original_filename"] for r in suggested}

    broll = footage["results"][0]
    assert broll["original_filename"] == "broll-1-pour.mp4" and broll["evidence_basis"] != "transcript"
    back = [r for r in broll["relationships"] if r["kind"] == "supporting_broll"]
    assert back and all(r["related_as"] == "a_roll_explanation" for r in back)
    assert "Pour the dirty water into the top bucket." in {r["excerpt"] for r in back}

    ctx = payload(call(home, ("get_segment_context", {"segment_id": a_roll["segment_id"]}))[0])
    [rel] = [r for r in ctx["relationships"] if r["segment_id"] == suggested[0]["segment_id"]]
    assert {e["text"] for e in rel["evidence"]} == {"Pour the dirty water into the top bucket.",
                                                    B_ROLL["broll-1-pour.mp4"]}
    assert all(("transcript_id" in e) != ("frame_id" in e) for e in rel["evidence"])


def test_native_search_reads_the_saved_index_without_any_model_service(home, tmp_path):
    import json
    import os
    import subprocess
    import sys

    project, _ = line_project(home, tmp_path)
    query = {"project_id": project["id"], "query": "two litres per minute"}
    worker_cli = Path(sys.executable).parent / "clipcon-worker"

    proc = subprocess.run(
        [str(worker_cli), "--home", str(home), "--whisper-model", str(tmp_path / "absent.bin"),
         "search", "--project", project["id"], "--query", query["query"]],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "OLLAMA_HOST": "127.0.0.1:9"})  # nothing listens there: no model can be reached

    [event] = [json.loads(line) for line in proc.stdout.splitlines()]
    assert event["event"] == "result", proc.stderr
    assert event["search"] == payload(call(home, ("search_footage", query))[0])  # the same results Codex gets


def test_a_folder_of_links_registers_each_original_once(home, tmp_path):
    originals = corpus(tmp_path / "shoot")
    links = tmp_path / "selects"
    links.mkdir()
    for name in ("a-roll.mp4", "broll-1-pour.mp4"):
        (links / name).symlink_to(originals / name)
    worker = Worker(home, speech=ScriptedSpeech(A_ROLL), vision=ScriptedVision(B_ROLL))
    project = worker.create_project("Selects")

    outcome = worker.import_folder(project["id"], links)

    clips = payload(call(home, ("get_project_overview", {"project_id": project["id"]}))[0])["clips"]
    assert sorted(c["original_filename"] for c in clips) == ["a-roll.mp4", "broll-1-pour.mp4"]
    assert all(c["status"] == "ready" for c in clips + outcome["clips"])


def test_with_default_segments_a_correction_in_the_same_segment_still_exposes_both_statements(home, tmp_path):
    folder = corpus(tmp_path / "shoot")
    worker = Worker(home, speech=ScriptedSpeech(A_ROLL), vision=ScriptedVision(B_ROLL))  # ~30 s Segments
    project = worker.create_project("Gravity filter tutorial")
    worker.import_folder(project["id"], folder)

    found = payload(call(home, ("search_footage", {"project_id": project["id"],
                                                   "query": "two litres per minute"}))[0])

    top = found["results"][0]
    assert top["original_filename"] == "a-roll.mp4"
    [link] = [r for r in top["relationships"] if r["kind"] == "spoken_correction"]
    assert link["related_as"] == "within_segment" and link["segment_id"] == top["segment_id"]
    assert link["excerpt"] == ("The filter holds two litres per hour. "
                               "Actually, I mean two litres per minute, not per hour.")
    ids = [(r["relationship_id"], r["related_as"]) for r in top["relationships"]]
    assert len(ids) == len(set(ids))  # one entry per relationship, not one per side


def test_footage_in_subfolders_joins_the_same_project(home, tmp_path):
    folder = corpus(tmp_path / "shoot")
    (folder / "B-roll").mkdir()
    (folder / "broll-3-cartridge.mp4").rename(folder / "B-roll" / "broll-3-cartridge.mp4")
    (folder / ".cache").mkdir()
    make_clip(folder / ".cache" / "proxy.mp4", seconds=2.0, audio=False)
    worker = Worker(home, speech=ScriptedSpeech(A_ROLL), vision=ScriptedVision(B_ROLL))
    project = worker.create_project("Gravity filter tutorial")

    worker.import_folder(project["id"], folder)

    clips = payload(call(home, ("get_project_overview", {"project_id": project["id"]}))[0])["clips"]
    assert sorted(c["original_filename"] for c in clips) == sorted(["a-roll.mp4", *B_ROLL])


def test_an_unavailable_model_service_stops_the_import_and_says_so(home, tmp_path):
    import pytest

    from clipcon_worker.vision import ServiceUnavailable

    folder = corpus(tmp_path / "shoot")
    vision = ScriptedVision(B_ROLL)

    def outage(request):
        if request.original_filename == "broll-2-drip.mp4":
            raise ServiceUnavailable("Ollama is not running")
    vision.on_describe = outage
    worker = Worker(home, speech=ScriptedSpeech(A_ROLL), vision=vision)
    project = worker.create_project("Gravity filter tutorial")

    with pytest.raises(ServiceUnavailable):
        worker.import_folder(project["id"], folder)

    states = {c["original_filename"]: c["status"] for c in payload(
        call(home, ("get_project_overview", {"project_id": project["id"]}))[0])["clips"]}
    assert states == {"a-roll.mp4": "ready", "broll-1-pour.mp4": "ready", "broll-2-drip.mp4": "failed",
                      "broll-3-cartridge.mp4": "pending"}


def test_a_roll_is_someone_speaking_to_camera_for_most_of_the_clip(home, tmp_path):
    folder = tmp_path / "shoot"
    folder.mkdir()
    for name in ("to-camera.mp4", "voice-over-screen.mp4"):
        make_clip(folder / name, seconds=23.0)
    make_clip(folder / "silent-broll.mp4", seconds=6.0)  # has an audio track, but nobody speaks
    speech = ScriptedSpeech([], A_ROLL, A_ROLL)  # import order: silent-broll, to-camera, voice-over-screen
    vision = ScriptedVision({}, facing_camera={"to-camera.mp4"})
    worker = Worker(home, speech=speech, vision=vision)
    project = worker.create_project("Roles")

    worker.import_folder(project["id"], folder)

    clips = {c["original_filename"]: c for c in worker.snapshot(project["id"])["clips"]}
    assert clips["to-camera.mp4"]["role"] == "a-roll"
    assert clips["voice-over-screen.mp4"]["role"] == "b-roll"  # speech alone, nobody addressing the camera
    assert clips["silent-broll.mp4"]["role"] == "b-roll"
    basis = clips["to-camera.mp4"]["role_basis"]
    assert "speech covers" in basis and "facing the camera" in basis


def test_removing_a_clip_from_a_project_keeps_it_in_the_library_until_removed_from_there(home, tmp_path):
    from conftest import sha256

    project, worker = line_project(home, tmp_path)
    pid = project["id"]
    clips = {c["original_filename"]: c for c in worker.snapshot(pid)["clips"]}
    broll = clips["broll-1-pour.mp4"]
    original = Path(broll["source_path"])
    before = sha256(original)
    old_segment = broll["segments"][0]["id"]

    worker.remove_clips(pid, [broll["id"]])

    overview, found, in_project, in_library, explained, listing = call(
        home, ("get_project_overview", {"project_id": pid}),
        ("search_footage", {"project_id": pid, "query": "murky water jug"}),
        ("get_segment_context", {"segment_id": old_segment, "project_id": pid}),
        ("get_segment_context", {"segment_id": old_segment, "scope": "library"}),
        ("search_footage", {"project_id": pid, "query": "pour the dirty water into the top bucket"}),
        ("get_project_overview", {}))
    assert "broll-1-pour.mp4" not in {c["original_filename"] for c in payload(overview)["clips"]}
    assert all(r["original_filename"] != "broll-1-pour.mp4" for r in payload(found)["results"])
    assert in_project.is_error  # no longer this Project's context
    assert payload(in_library)["creator_notes"] == [] and payload(in_library)["relationships"] == []
    assert all(rel["original_filename"] != "broll-1-pour.mp4"
               for r in payload(explained)["results"] for rel in r["relationships"])
    assert payload(listing)["library"]["standalone_count"] == 1
    assert (home / "frames" / broll["id"]).exists()  # its analysis is kept for reuse

    worker.remove_from_library([broll["id"]])

    [gone] = call(home, ("get_segment_context", {"segment_id": old_segment}))
    assert gone.is_error  # its Segments no longer exist
    assert original.exists() and sha256(original) == before
    assert not (home / "frames" / broll["id"]).exists()  # Clipcon's own frame cache is cleaned up


def test_deleting_a_project_leaves_other_projects_its_library_footage_and_all_originals(home, tmp_path):
    project, worker = line_project(home, tmp_path)
    other = worker.create_project("Another video")
    footage = [Path(c["source_path"]) for c in worker.snapshot(project["id"])["clips"]]

    worker.delete_project(project["id"])

    [listing, gone, reusable] = call(home, ("get_project_overview", {}),
                                     ("get_project_overview", {"project_id": project["id"]}),
                                     ("search_footage", {"scope": "library", "query": "murky water jug"}))
    assert [p["project_id"] for p in payload(listing)["projects"]] == [other["id"]]
    assert payload(listing)["library"] == {**payload(listing)["library"], "source_count": 4, "standalone_count": 4}
    assert gone.is_error
    [pour] = payload(reusable)["results"]
    assert pour["original_filename"] == "broll-1-pour.mp4" and pour["origins"] == []
    assert all(p.exists() for p in footage)


def test_several_chosen_clips_and_folders_join_one_project_once_each(home, tmp_path):
    shoot = corpus(tmp_path / "shoot")
    extra = tmp_path / "pickups"
    extra.mkdir()
    make_clip(extra / "broll-4-glass.mp4", seconds=6.0, audio=False)
    worker = Worker(home, speech=ScriptedSpeech(A_ROLL), vision=ScriptedVision(B_ROLL))
    project = worker.create_project("Gravity filter tutorial")

    # Two clips picked individually, one of them also inside a chosen folder, plus a non-video file.
    outcome = worker.import_sources(project["id"], [shoot / "a-roll.mp4", shoot / "broll-1-pour.mp4", extra,
                                                    shoot / "notes.txt"])

    clips = payload(call(home, ("get_project_overview", {"project_id": project["id"]}))[0])["clips"]
    assert sorted(c["original_filename"] for c in clips) == ["a-roll.mp4", "broll-1-pour.mp4", "broll-4-glass.mp4"]
    assert all(c["status"] == "ready" for c in clips) and len(outcome["clips"]) == 3

    again = worker.import_sources(project["id"], [extra, extra / "broll-4-glass.mp4"])
    assert [c["original_filename"] for c in again["clips"]] == ["broll-4-glass.mp4"]
