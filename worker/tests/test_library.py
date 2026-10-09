"""The Footage library: sources shared by Project memberships, migrated from the Project-owned index, managed
through the worker entry points the app uses and observed through MCP as Codex would."""

from pathlib import Path

import pytest
from conftest import ScriptedSpeech, ScriptedVision, sha256
from legacy_index import build_legacy_index
from test_creator_controls import worker_cli
from test_mcp import call, payload
from test_project import A_ROLL, B_ROLL

from clipcon_worker.pipeline import Worker


@pytest.fixture(scope="session")
def legacy_cache(tmp_path_factory):
    return tmp_path_factory.mktemp("legacy")


def overview(home, pid) -> dict:
    return {c["original_filename"]: c for c in payload(
        call(home, ("get_project_overview", {"project_id": pid}))[0])["clips"]}


def test_migrating_a_legacy_index_keeps_context_notes_exclusions_and_held_references(home, tmp_path, legacy_cache):
    legacy = build_legacy_index(home, tmp_path, legacy_cache)
    tutorial, ideas = legacy["tutorial"], legacy["ideas"]
    old_a, old_b = legacy["clips"]["tutorial"], legacy["clips"]["ideas"]
    speech, vision = ScriptedSpeech(A_ROLL), ScriptedVision(B_ROLL)

    worker = Worker(home, speech=speech, vision=vision)  # opening the index migrates it

    assert (speech.calls, vision.calls) == (0, 0)  # migration starts no inference
    a, b = overview(home, tutorial), overview(home, ideas)
    assert set(a) == set(old_a) and set(b) == set(old_b)
    # The same file imported into two Projects is now one Source clip with one analysis and two memberships.
    pour_a, pour_b = a["broll-1-pour.mp4"], b["broll-1-pour.mp4"]
    assert pour_a["clip_id"] == pour_b["clip_id"] == old_a["broll-1-pour.mp4"]["id"]
    assert pour_a["excluded"] is False and pour_b["excluded"] is True  # exclusion stays with its Project
    assert a["broll-3-cartridge.mp4"]["excluded"] is True
    assert b["old-cutaway.mp4"]["status"] == "missing"  # unavailable source keeps its context
    assert b["old-cutaway.mp4"]["segment_count"] >= 1

    # Every reference the agent was given before still resolves, in its original Project's scope.
    for segment_id, before in legacy["held"].items():
        if before["segment"]["clip_id"] == old_b["broll-1-pour.mp4"]["id"]:
            continue  # the consolidated duplicate: checked below
        ctx = payload(call(home, ("get_segment_context", {"segment_id": segment_id}))[0])
        for key in ("transcript", "observations", "interpretation", "excluded"):
            assert ctx[key] == before[key], (segment_id, key)
        assert ctx["segment"]["project_id"] == before["segment"]["project_id"]
        assert [n["text"] for n in ctx["creator_notes"]] == [n["text"] for n in before["creator_notes"]]
        assert {r["segment_id"] for r in ctx["relationships"]} == {r["segment_id"] for r in before["relationships"]}

    # The duplicate's old Segment IDs name what happened instead of addressing another source's context.
    dup_segment = old_b["broll-1-pour.mp4"]["segments"][0]["id"]
    [failed] = call(home, ("get_segment_context", {"segment_id": dup_segment}))
    assert failed.is_error
    message = failed.content[0].text
    assert pour_a["clip_id"] in message and ideas in message and "Kitchen: pour" not in message

    # Notes stay with the Project they were written for.
    shared_segment = old_a["broll-1-pour.mp4"]["segments"][0]["id"]
    in_tutorial, in_ideas = (payload(r) for r in call(
        home, ("get_segment_context", {"segment_id": shared_segment, "project_id": tutorial}),
        ("get_segment_context", {"segment_id": shared_segment, "project_id": ideas})))
    assert [n["text"] for n in in_tutorial["creator_notes"]] == ["Tutorial: use the slow pour."]
    assert [n["text"] for n in in_ideas["creator_notes"]] == ["Kitchen: pour for the lemonade idea."]
    assert in_ideas["excluded"] is True and in_tutorial["excluded"] is False

    # Legacy whole-clip roles are not passed off as verified Segment roles.
    snapshot = {c["original_filename"]: c for c in worker.snapshot(tutorial)["clips"]}
    for seg in snapshot["broll-1-pour.mp4"]["segments"]:
        assert seg["role"]["suggested"] == "needs_review" and seg["role"]["creator"] is None
        assert "before Segment roles" in seg["role"]["basis"]

    # Reopening is idempotent.
    Worker(home, speech=speech, vision=vision)
    assert overview(home, tutorial) == a
    assert (speech.calls, vision.calls) == (0, 0)

    # Context analysed by the previous recipe stays current (not stale), and adding it to another Project
    # reuses it; only an explicit re-analysis upgrades it to per-Segment roles.
    from clipcon_worker.pipeline import RECIPE
    current = Worker(home, speech=speech, vision=vision, recipe={**RECIPE, "segment_target_seconds": 1.0})
    assert {c["status"] for c in current.check_sources(tutorial)["clips"]} == {"ready"}
    third = current.create_project("Third idea")["id"]
    pour = Path(legacy["folder"]) / "broll-1-pour.mp4"
    before = sha256(pour)
    assert current.import_clip(third, pour)["reused"] is True and (speech.calls, vision.calls) == (0, 0)
    current.retry(third, [pour_a["clip_id"]])
    assert vision.calls > 0
    upgraded = {c["original_filename"]: c for c in current.snapshot(third)["clips"]}["broll-1-pour.mp4"]
    assert {s["role"]["suggested"] for s in upgraded["segments"]} == {"b-roll"}
    assert sha256(pour) == before


def shoot(tmp_path):
    """The tutorial shoot analysed into one Project, plus a second Project for another idea."""
    from test_project import line_project

    project, worker = line_project(home := tmp_path / "clipcon-home", tmp_path)
    ideas = worker.create_project("Kitchen ideas")
    return home, worker, project["id"], ideas["id"]


def test_adding_a_source_to_a_second_project_reuses_its_analysis_with_separate_notes(tmp_path):
    from conftest import make_clip

    home, worker, tutorial, ideas = shoot(tmp_path)
    pour_path = tmp_path / "shoot" / "broll-1-pour.mp4"
    before = sha256(pour_path)
    calls = (worker.speech.calls, worker.vision.calls)
    shared = overview(home, tutorial)["broll-1-pour.mp4"]

    # The same file is imported into the second Project.
    imported = worker.import_clip(ideas, pour_path)
    assert imported["reused"] is True and imported["clip_id"] == shared["clip_id"]
    # A different file with the same name is different footage: a new source, analysed on its own.
    other = tmp_path / "elsewhere"
    other.mkdir()
    lookalike = Worker(home, speech=ScriptedSpeech(A_ROLL), vision=ScriptedVision(B_ROLL)).import_clip(
        ideas, make_clip(other / "broll-1-pour.mp4", seconds=5.0, audio=False))
    assert lookalike["reused"] is False and lookalike["clip_id"] != shared["clip_id"]

    assert (worker.speech.calls, worker.vision.calls) == calls  # the shared source was not re-analysed
    in_ideas = [c for c in payload(call(home, ("get_project_overview", {"project_id": ideas}))[0])["clips"]
                if c["clip_id"] == shared["clip_id"]][0]
    assert (in_ideas["revision"], in_ideas["segment_count"]) == (shared["revision"], shared["segment_count"])

    worker_cli(home, "set-note", "--project", tutorial, "--clip", shared["clip_id"], "--text", "Slow pour.")
    worker_cli(home, "set-note", "--project", ideas, "--clip", shared["clip_id"], "--text", "Lemonade pour.")
    worker_cli(home, "set-excluded", "--project", ideas, "--excluded", "yes", shared["clip_id"])
    segment = [c for c in worker.snapshot(tutorial)["clips"] if c["id"] == shared["clip_id"]][0]["segments"][0]["id"]
    a, b, held = (payload(r) for r in call(
        home, ("get_segment_context", {"segment_id": segment, "project_id": tutorial}),
        ("get_segment_context", {"segment_id": segment, "project_id": ideas}),
        ("get_segment_context", {"segment_id": segment})))  # a reference held from before sharing
    assert ([n["text"] for n in a["creator_notes"]], a["excluded"]) == (["Slow pour."], False)
    assert ([n["text"] for n in b["creator_notes"]], b["excluded"]) == (["Lemonade pour."], True)
    assert [n["text"] for n in held["creator_notes"]] == ["Slow pour."]  # never the newly shared Project's
    assert payload(call(home, ("search_footage", {"project_id": tutorial, "query": "lemonade"}))[0])["results"] == []
    # The choices persist when the index is reopened, and remain reversible.
    def excluded_in_ideas():
        clips = payload(call(home, ("get_project_overview", {"project_id": ideas}))[0])["clips"]
        return {c["clip_id"]: c["excluded"] for c in clips}[shared["clip_id"]]
    assert excluded_in_ideas() is True
    worker_cli(home, "set-excluded", "--project", ideas, "--excluded", "no", shared["clip_id"])
    assert excluded_in_ideas() is False
    assert sha256(pour_path) == before


def test_library_reuse_respects_roles_reuse_permission_and_each_projects_exclusion(tmp_path):
    home, worker, tutorial, ideas = shoot(tmp_path)
    pour = overview(home, tutorial)["broll-1-pour.mp4"]["clip_id"]
    worker.add_to_project(ideas, [pour])
    worker_cli(home, "set-note", "--project", tutorial, "--clip", pour, "--text", "Tutorial-only: jug is borrowed.")
    worker_cli(home, "set-note", "--project", ideas, "--clip", pour, "--text", "Kitchen: lemonade pour.")
    third = worker.create_project("Camping video")["id"]
    jug = {"scope": "library", "project_id": third, "query": "murky water jug"}
    narration = {"scope": "library", "query": "pour the dirty water into the top bucket"}

    def library(args):
        return payload(call(home, ("search_footage", args))[0])

    # A-roll stays with its Project: its spoken explanation is never a reusable candidate.
    assert all(r["role"] == "b-roll" for r in library(narration)["results"])
    assert "a-roll.mp4" not in {r["original_filename"] for r in library(narration)["results"]}

    # Excluded in the tutorial, allowed in the kitchen Project: the shared source is still a candidate, drawing
    # only on the allowed membership; the tutorial's note never appears, in results or expansion.
    worker_cli(home, "set-excluded", "--project", tutorial, "--excluded", "yes", pour)
    [hit] = [r for r in library(jug)["results"] if r["clip_id"] == pour]
    assert [o["project_id"] for o in hit["origins"]] == [ideas] and hit["relationships"] == []
    ctx = payload(call(home, ("get_segment_context", {"segment_id": hit["segment_id"], "scope": "library",
                                                      "project_id": third}))[0])
    assert [n["text"] for n in ctx["creator_notes"]] == ["Kitchen: lemonade pour."]
    assert ctx["relationships"] == [] and "borrowed" not in str(ctx)
    assert library({**jug, "query": "borrowed"})["results"] == []

    # Excluded everywhere it belongs: no path remains.
    worker_cli(home, "set-excluded", "--project", ideas, "--excluded", "yes", pour)
    assert pour not in {r["clip_id"] for r in library(jug)["results"]}
    [refused] = call(home, ("get_segment_context", {"segment_id": hit["segment_id"], "scope": "library"}))
    assert refused.is_error and "excluded" in refused.content[0].text
    worker_cli(home, "set-excluded", "--project", ideas, "--excluded", "no", pour)
    worker_cli(home, "set-excluded", "--project", tutorial, "--excluded", "no", pour)

    # Reuse permission off blocks every cross-project candidate and expansion, but not its own Projects.
    worker_cli(home, "set-reuse", "--allowed", "no", pour)
    assert pour not in {r["clip_id"] for r in library(jug)["results"]}
    for tool, args in (("get_segment_context", {}), ("get_segment_preview", {}), ("resolve_media", {})):
        [blocked] = call(home, (tool, {"segment_id": hit["segment_id"], "scope": "library", "project_id": third}))
        assert blocked.is_error and "not allowed reuse" in blocked.content[0].text
    own = library({**jug, "project_id": ideas})["results"]
    assert [o["project_id"] for r in own if r["clip_id"] == pour for o in r["origins"]] == [ideas]
    in_project = payload(call(home, ("search_footage", {"project_id": tutorial, "query": "murky water jug"}))[0])
    assert pour in {r["clip_id"] for r in in_project["results"]}  # Project search is unchanged
    assert overview(home, tutorial)["broll-1-pour.mp4"]["reuse_allowed"] is False

    # Reversible, and persisted in the index.
    worker_cli(home, "set-reuse", "--allowed", "yes", pour)
    assert pour in {r["clip_id"] for r in library(jug)["results"]}


class FacingWhileTalking(ScriptedVision):
    """A recording that starts as a talking head (facing the camera only in its opening Segment)."""

    def describe(self, request):
        out = super().describe(request)
        return {**out, "speaker_facing_camera": request.start < 5.0}


def test_segments_of_a_mixed_recording_get_their_own_roles_and_creator_corrections(home, tmp_path):
    from conftest import RecordedSpeech, make_clip

    from clipcon_worker.speech import TranscriptSpan

    talk = [TranscriptSpan(0.0, 7.5, "Here is how the filter goes together on the counter."),
            TranscriptSpan(20.5, 28.0, "As you can see, the water comes out clear.")]  # said over other visuals
    worker = Worker(home, speech=RecordedSpeech(talk),
                    vision=FacingWhileTalking({"mixed-take.mp4": "Hands pour murky water from a jug."},
                                              facing_camera=set()))
    project = worker.create_project("Filter vlog")["id"]
    other = worker.create_project("Another idea")["id"]
    clip_id = worker.import_clip(project, make_clip(tmp_path / "mixed-take.mp4", seconds=30.0))["clip_id"]

    [clip] = worker_cli(home, "snapshot", "--project", project)["snapshot"]["clips"]
    ranges = [(s["start"], s["end"], s["role"]["suggested"]) for s in clip["segments"]]
    assert ranges == [(0.0, 7.5, "a-roll"), (7.5, 20.5, "b-roll"), (20.5, 30.0, "mixed")]
    assert all(s["role"]["creator"] is None and "speech covers" in s["role"]["basis"] for s in clip["segments"])
    assert clip["role_summary"]["text"] == "A-roll and B-roll, 1 to review"
    talking, cutaway, voiceover = (s["id"] for s in clip["segments"])

    def reusable():
        found = payload(call(home, ("search_footage", {"scope": "library", "project_id": other,
                                                       "query": "murky water jug"}))[0])["results"]
        return {r["segment_id"] for r in found}

    assert reusable() == {cutaway}  # only the silent cutaway; the narration and the Mixed part are not offered
    in_project = payload(call(home, ("search_footage", {"project_id": project, "query": "murky water jug"}))[0])
    assert {r["segment_id"] for r in in_project["results"]} == {talking, cutaway, voiceover}  # all reviewable

    # The creator decides the voice-over part is usable B-roll: attributed separately, and now reusable.
    corrected = worker_cli(home, "set-segment-role", "--segment", voiceover, "--role", "b-roll")["role"]
    assert (corrected["suggested"], corrected["creator"], corrected["effective"]) == ("mixed", "b-roll", "b-roll")
    assert reusable() == {cutaway, voiceover}
    ctx = payload(call(home, ("get_segment_context", {"segment_id": voiceover, "scope": "library"}))[0])
    assert ctx["segment_role"] == {**ctx["segment_role"], "role": "b-roll", "suggested": "mixed", "creator": "b-roll"}
    [clip] = worker.snapshot(project)["clips"]
    assert clip["role_summary"]["text"] == "A-roll and B-roll"

    # Corrections are reversible, and a creator can also withdraw a suggested cutaway.
    worker_cli(home, "set-segment-role", "--segment", voiceover, "--role", "suggested")
    worker_cli(home, "set-segment-role", "--segment", cutaway, "--role", "needs_review")
    assert reusable() == set()
    assert clip_id == clip["id"]

    # A re-analysis that draws different Segment boundaries cannot silently drop the creator's decision.
    from clipcon_worker.pipeline import RECIPE
    regrouped = Worker(home, speech=worker.speech, vision=worker.vision,
                       recipe={**RECIPE, "silent_gap_seconds": 1000.0})
    regrouped.retry(project, [clip_id])
    [clip] = worker_cli(home, "snapshot", "--project", project)["snapshot"]["clips"]
    assert [(c["start"], c["end"], c["role"]) for c in clip["unmatched_role_corrections"]] == [
        (7.5, 20.5, "needs_review")]


def test_library_only_footage_needs_no_project_and_copies_are_grouped(home, tmp_path):
    import shutil

    from conftest import make_clip

    stock = tmp_path / "stock"
    stock.mkdir()
    make_clip(stock / "jug-pour.mp4", seconds=6.0, audio=False)
    shutil.copy2(stock / "jug-pour.mp4", stock / "jug-pour copy.mp4")  # the same footage twice
    worker = Worker(home, speech=ScriptedSpeech(A_ROLL), vision=ScriptedVision(
        {"jug-pour.mp4": "Hands pour murky water from a jug.", "jug-pour copy.mp4": "Hands pour murky water from a jug."}))

    outcome = worker.import_sources(None, [stock])  # straight into the library, no placeholder Project

    assert {c["status"] for c in outcome["clips"]} == {"ready"}
    listing = payload(call(home, ("get_project_overview", {}))[0])
    assert listing["projects"] == [] and listing["library"]["standalone_count"] == 2
    found = payload(call(home, ("search_footage", {"scope": "library", "query": "murky water jug"}))[0])
    [hit] = found["results"]  # one candidate for the duplicated footage, naming the other copy
    assert hit["origins"] == [] and hit["project_id"] is None and len(hit["duplicate_clip_ids"]) == 1
    media = payload(call(home, ("resolve_media", {"segment_id": hit["segment_id"], "scope": "library"}))[0])
    assert media["available"] is True and Path(media["path"]).parent == stock.resolve()
    assert "does not document events" in found["scope_note"]
    [missing_scope] = call(home, ("search_footage", {"query": "murky water jug"}))
    assert missing_scope.is_error  # no implicit Project: the agent must choose a scope


def test_removing_a_source_from_the_library_during_its_analysis_publishes_nothing(home, tmp_path):
    from conftest import make_clip

    vision = ScriptedVision(B_ROLL)
    worker = Worker(home, speech=ScriptedSpeech(A_ROLL), vision=vision)
    pid = worker.create_project("Gravity filter tutorial")["id"]
    original = make_clip(tmp_path / "broll-1-pour.mp4", seconds=6.0, audio=False)
    before = sha256(original)
    removed = {}

    def remove_while_describing(request):  # the creator removes it while the worker is mid-analysis
        if not removed:
            [clip] = worker.snapshot(pid)["clips"]
            removed.update(worker_cli(home, "remove-from-library", clip["id"]))
    vision.on_describe = remove_while_describing

    outcome = worker.import_clip(pid, original)

    assert outcome["removed"] is True and removed["projects"] == [pid]
    assert payload(call(home, ("get_project_overview", {"project_id": pid}))[0])["clips"] == []
    assert payload(call(home, ("get_project_overview", {}))[0])["library"]["source_count"] == 0
    assert not (home / "frames" / outcome["clip_id"]).exists()
    assert sha256(original) == before


def test_a_transcript_line_stretched_over_a_measured_silence_does_not_hide_the_cutaway(home, tmp_path):
    import subprocess

    from conftest import RecordedSpeech

    from clipcon_worker.speech import TranscriptSpan

    clip = tmp_path / "talk-then-cutaway.mp4"  # a tone, silent from 8 s to 22 s
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24:duration=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
                    "-af", "volume=enable='between(t,8,22)':volume=0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(clip)], check=True)
    # Like whisper.cpp with VAD on real footage: one short line claims to last across the silence.
    stretched = [TranscriptSpan(0.5, 21.5, "Here is how the filter goes together."),
                 TranscriptSpan(22.5, 29.0, "And the water comes out clear.")]
    worker = Worker(home, speech=RecordedSpeech(stretched),
                    vision=FacingWhileTalking({"talk-then-cutaway.mp4": "Hands pour murky water from a jug."},
                                              facing_camera=set()))
    pid = worker.create_project("Filter vlog")["id"]
    worker.import_clip(pid, clip)

    [c] = worker.snapshot(pid)["clips"]
    first_line = c["segments"][0]["transcript"][0]
    assert 7.5 < first_line["end"] <= 8.5  # bounded by the measured silence, not the claimed 21.5 s
    roles = [(round(s["start"]), round(s["end"]), s["role"]["suggested"]) for s in c["segments"]]
    assert roles[1][2] == "b-roll" and 7 <= roles[1][0] <= 9 and roles[1][1] == 22
