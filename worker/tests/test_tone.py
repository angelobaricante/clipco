"""Emotional tone and reusable B-roll discovery: enriched through the worker entry points the app uses, observed
through MCP as Codex would. Scripted tone readings prove orchestration and policy only, not tone quality."""

import pytest
from conftest import ScriptedSpeech, ScriptedVision, make_clip
from test_creator_controls import worker_cli
from test_mcp import call, payload
from test_project import A_ROLL, B_ROLL, corpus

from clipco_worker.pipeline import Worker

TONES = {
    "broll-2-drip.mp4": {
        "tones": [("calm", "Slow single drops into a still glass."),
                  ("satisfying", "Clear water collecting where murky water went in.")],
        "connotations": [("patience", "Water gathering one drop at a time suggests slow, steady progress.")],
    },
    "broll-1-pour.mp4": {
        "tones": [("tense", "Murky water sloshing out of a jug looks messy and uncertain.")],
        "connotations": [("a messy beginning", "Dirty water going in before anything is clean.")],
    },
    "broll-3-cartridge.mp4": {"tones": [], "connotations": []},  # analysed, nothing supported
}


def library(home, **args) -> dict:
    return payload(call(home, ("search_footage", {"scope": "library", **args}))[0])


def test_tone_is_not_analyzed_until_explicitly_enriched_from_saved_evidence(home, tmp_path):
    speech, vision = ScriptedSpeech(A_ROLL), ScriptedVision(B_ROLL, tones=TONES)
    # Footage indexed before tone analysis existed.
    before_tone = Worker(home, speech=speech, vision=vision, tone_on_import=False)
    pid = before_tone.create_project("Gravity filter tutorial")["id"]
    before_tone.import_folder(pid, corpus(tmp_path / "shoot"))

    # Eligible B-roll stays discoverable by content, with its tone explicitly Not analyzed...
    found = library(home, query="water glass")["results"]
    assert found and {r["tone"]["state"] for r in found} == {"not_analyzed"}
    # ...but missing tone never satisfies a required tone.
    calm = library(home, query="water", tone="calm")
    assert calm["results"] == [] and calm["tone_not_analyzed_skipped"] >= 1

    # Explicit enrichment reuses the saved frames and transcript: no transcription, no new description.
    calls = (speech.calls, vision.calls)
    worker = Worker(home, speech=speech, vision=vision)
    outcome = worker.enrich_tone(pid)
    assert (speech.calls, vision.calls) == calls and vision.tone_calls > 0
    assert {c["status"] for c in outcome["clips"]} == {"ready"}

    [drip] = library(home, query="water", tone="peaceful")["results"]  # a synonym of a vocabulary tone
    assert drip["original_filename"] == "broll-2-drip.mp4"
    assert drip["tone"]["state"] == "suggested" and drip["tone"]["tones"] == ["calm", "satisfying"]
    ctx = payload(call(home, ("get_segment_context", {"segment_id": drip["segment_id"], "scope": "library"}))[0])
    tone = ctx["emotional_tone"]
    assert [s["tone"] for s in tone["suggested"]] == ["calm", "satisfying"]
    frames = {o["frame_id"] for o in ctx["observations"]}
    assert all(set(s["evidence_ids"]) <= frames for s in tone["suggested"])  # cites saved, real evidence
    assert tone["connotations"][0]["idea"] == "patience"
    assert tone["creator"] is None and "did not watch continuous video" in tone["limitations"]
    assert tone["model"] == vision.identity["model"]

    # Analysed with no supported tone differs from Not analyzed.
    cartridge = [r for r in library(home, query="ceramic filter cartridge")["results"]]
    assert cartridge[0]["tone"] == {**cartridge[0]["tone"], "state": "none_supported", "tones": []}

    # A creator correction is attributed separately and leaves the suggestions and evidence as they were.
    corrected = worker_cli(home, "set-segment-tones", "--segment", drip["segment_id"], "--tones", "calm,hopeful")
    assert corrected["tone"]["creator"] == ["calm", "hopeful"]
    [hope] = library(home, query="water", tone="hopeful")["results"]
    assert hope["segment_id"] == drip["segment_id"] and hope["tone"]["state"] == "creator"
    after = payload(call(home, ("get_segment_context", {"segment_id": drip["segment_id"], "scope": "library"}))[0])
    assert after["emotional_tone"]["suggested"] == tone["suggested"] and after["observations"] == ctx["observations"]
    worker_cli(home, "set-segment-tones", "--segment", drip["segment_id"], "--suggested")
    assert library(home, query="water", tone="hopeful")["results"] == []


    # Already enriched footage is not analysed again; an unknown tone is refused, not guessed.
    tone_calls = vision.tone_calls
    worker.enrich_tone(pid)
    assert vision.tone_calls == tone_calls
    [refused] = call(home, ("search_footage", {"scope": "library", "query": "water", "tone": "sparkly"}))
    assert refused.is_error and "calm" in refused.content[0].text

    # A re-analysis that draws different Segment boundaries keeps and shows the creator's tones, never drops them.
    worker_cli(home, "set-segment-tones", "--segment", drip["segment_id"], "--tones", "calm")
    from clipco_worker.pipeline import RECIPE
    Worker(home, speech=speech, vision=vision, recipe={**RECIPE, "silent_segment_seconds": 2.0}).retry(
        pid, [drip["clip_id"]])
    [clip] = [c for c in worker_cli(home, "snapshot", "--project", pid)["snapshot"]["clips"]
              if c["id"] == drip["clip_id"]]
    assert [c["tones"] for c in clip["unmatched_tone_corrections"]] == [["calm"]]


ELSEWHERE = {
    "glass-drip.mp4": "Clear water drips from a spigot into a glass.",  # comparable to the tutorial's drip
    "kettle.mp4": "Water pours from a kettle into a mug; something steams on a busy counter.",
    "sunrise.mp4": "The sun rises over a misty lake.",
}
ELSEWHERE_TONES = {
    "glass-drip.mp4": TONES["broll-2-drip.mp4"],
    "kettle.mp4": {"tones": [("energetic", "A busy counter mid-morning.")], "connotations": []},
    "sunrise.mp4": {"tones": [("awe", "Wide misty lake as the light comes up."), ("calm", "Still water.")],
                    "connotations": [("a fresh start", "A new day beginning over still water.")]},
}


@pytest.fixture
def two_projects_and_standalone(home, tmp_path):
    """The filter tutorial, a morning-routine Project being edited, and stock footage in no Project."""
    worker = Worker(home, speech=ScriptedSpeech(A_ROLL), vision=ScriptedVision(
        {**B_ROLL, **ELSEWHERE}, tones={**TONES, **ELSEWHERE_TONES}))
    tutorial = worker.create_project("Gravity filter tutorial")["id"]
    morning = worker.create_project("Morning routine")["id"]
    worker.import_folder(tutorial, corpus(tmp_path / "shoot"))
    own = tmp_path / "morning"
    own.mkdir()
    for name, seconds in (("glass-drip.mp4", 7.0), ("kettle.mp4", 5.0)):
        worker.import_clip(morning, make_clip(own / name, seconds=seconds, audio=False))
    worker.import_clip(None, make_clip(tmp_path / "sunrise.mp4", seconds=8.0, audio=False))
    worker.enrich_tone(None)  # the creator asks for the whole library's tone
    return home, tutorial, morning


def names(results) -> list[str]:
    return [r["original_filename"] for r in results]


def test_library_discovery_ranks_by_suitability_and_emotional_fit_with_a_modest_project_preference(
        two_projects_and_standalone):
    home, tutorial, morning = two_projects_and_standalone

    # Better-fitting footage from another Project outranks weaker footage of the Project being edited.
    calm_water = library(home, query="calm water", project_id=morning)["results"]
    assert names(calm_water).index("broll-2-drip.mp4") < names(calm_water).index("kettle.mp4")
    assert "a-roll.mp4" not in names(calm_water)
    # Comparable candidates: the requesting Project's own footage comes first, from either side.
    assert names(calm_water)[0] == "glass-drip.mp4" and calm_water[0]["fit"]["current_project"] is True
    from_tutorial = names(library(home, query="calm water", project_id=tutorial)["results"])
    assert from_tutorial.index("broll-2-drip.mp4") < from_tutorial.index("glass-drip.mp4")

    # A literal request and a metaphorical one are explained differently.
    [literal] = [r for r in library(home, query="spigot glass", project_id=morning)["results"]
                 if r["original_filename"] == "broll-2-drip.mp4"]
    assert literal["fit"]["kind"] == "literal" and "spigot" in literal["fit"]["explanation"]
    patience = library(home, query="patience", project_id=morning)["results"]
    assert set(names(patience)) == {"broll-2-drip.mp4", "glass-drip.mp4"}
    other = [r for r in patience if r["original_filename"] == "broll-2-drip.mp4"][0]
    assert other["fit"]["kind"] == "metaphorical" and "patience" in other["fit"]["explanation"]
    assert set(other["fit"]["evidence_ids"]) and other["fit"]["current_project"] is False
    # Footage from elsewhere is never presented as a record of the requesting Project's events.
    assert "does not document" in other["fit"]["caution"]
    assert [r for r in patience if r["original_filename"] == "glass-drip.mp4"][0]["fit"]["caution"] is None

    # Standalone stock footage takes part with no Project at all.
    [fresh, *_] = library(home, query="a fresh start", project_id=morning)["results"]
    assert fresh["original_filename"] == "sunrise.mp4" and fresh["origins"] == []
    assert fresh["fit"]["kind"] == "metaphorical"

    # A purely emotional request is matched on tone and says so; nothing suitable means nothing returned.
    [tense] = library(home, query="a tense moment", project_id=morning)["results"]
    assert tense["original_filename"] == "broll-1-pour.mp4" and tense["fit"]["kind"] == "emotional"
    assert tense["fit"]["tones_matched"] == ["tense"]
    # Filler words of a mood request ("something") never pad the results with unrelated footage.
    assert library(home, query="something nostalgic", project_id=morning)["results"] == []
    assert names(library(home, query="something tense", project_id=morning)["results"]) == ["broll-1-pour.mp4"]
    # When the footage literally shows part of the request, it is a literal fit even if a metaphor also matches.
    [drip] = [r for r in library(home, query="water patience", project_id=morning)["results"]
              if r["original_filename"] == "broll-2-drip.mp4"]
    assert drip["fit"]["kind"] == "literal"

    # The Project scope is unchanged by any of this: no tone or metaphor evidence, no other Project's footage.
    in_project = payload(call(home, ("search_footage", {"project_id": morning, "query": "patience"}))[0])
    assert in_project["results"] == []
