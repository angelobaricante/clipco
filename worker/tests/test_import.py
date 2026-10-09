from conftest import SPANS, RecordedSpeech, RecordedVision

from clipco_worker.pipeline import Worker


def test_importing_a_clip_saves_source_grounded_context(home, clip):
    worker = Worker(home, speech=RecordedSpeech(SPANS), vision=RecordedVision())
    project = worker.create_project("Water filter tutorial", context="Explain how the filter works")

    result = worker.import_clip(project["id"], clip)

    snap = worker.snapshot(project["id"])
    assert snap["project"]["context"] == "Explain how the filter works"
    [saved] = snap["clips"]
    assert saved["id"] == result["clip_id"]
    assert saved["status"] == "ready"
    assert saved["original_filename"] == "talking-head.mp4"
    assert saved["source_path"] == str(clip)
    assert 11.5 <= saved["duration"] <= 12.5  # measured by FFmpeg, not assumed
    assert saved["segments"], "a ready clip has segments"
    for seg in saved["segments"]:
        assert 0 <= seg["start"] < seg["end"] <= saved["duration"]
        # transcript, sampled observations and interpretation are distinct kinds of evidence
        assert all(t["start"] >= seg["start"] - 1e-6 and t["end"] <= seg["end"] + 1e-6 for t in seg["transcript"])
        assert seg["observations"] and all(o["frame"]["time"] <= saved["duration"] for o in seg["observations"])
        assert seg["interpretation"]["text"]
        assert seg["interpretation"]["model"] == "fixture"
    spoken = " ".join(t["text"] for s in saved["segments"] for t in s["transcript"])
    assert "Actually, I mean the colour bars." in spoken


def test_evidence_the_model_invents_is_not_trusted(home, clip):
    worker = Worker(home, speech=RecordedSpeech(SPANS), vision=RecordedVision(invent_ids=True))
    project = worker.create_project("Tutorial")

    worker.import_clip(project["id"], clip)

    [saved] = worker.snapshot(project["id"])["clips"]
    for seg in saved["segments"]:
        sampled = {o["frame"]["id"] for o in seg["observations"]}
        known = sampled | {t["id"] for t in seg["transcript"]}
        assert "A frame that was never sampled." not in [o["text"] for o in seg["observations"]]
        assert set(seg["interpretation"]["evidence_ids"]) <= known
        assert {"f999", "t999"} <= set(seg["interpretation"]["rejected_refs"])


def test_reload_reuses_saved_context_without_reinference_and_leaves_original_untouched(home, clip):
    from conftest import sha256

    before = sha256(clip)
    speech, vision = RecordedSpeech(SPANS), RecordedVision()
    first = Worker(home, speech=speech, vision=vision)
    project = first.create_project("Tutorial")
    first.import_clip(project["id"], clip)
    saved = first.snapshot(project["id"])
    calls = (speech.calls, vision.calls)

    reloaded = Worker(home, speech=speech, vision=vision)  # e.g. app restart
    assert reloaded.snapshot(project["id"]) == saved
    again = reloaded.import_clip(project["id"], clip)

    assert again["reused"] is True
    assert (speech.calls, vision.calls) == calls
    assert reloaded.snapshot(project["id"])["clips"][0]["segments"] == saved["clips"][0]["segments"]
    assert sha256(clip) == before
    assert sorted(p.name for p in clip.parent.iterdir()) == ["talking-head.mp4"]


def test_changed_analysis_configuration_reanalyses_with_the_same_clip_identity(home, clip):
    speech, vision = RecordedSpeech(SPANS), RecordedVision()
    worker = Worker(home, speech=speech, vision=vision)
    project = worker.create_project("Tutorial")
    first = worker.import_clip(project["id"], clip)

    vision.identity = {"engine": "recorded-vision", "model": "fixture-v2"}
    second = worker.import_clip(project["id"], clip)

    assert second["reused"] is False
    assert second["clip_id"] == first["clip_id"]
    assert second["revision"] == first["revision"] + 1
    [saved] = worker.snapshot(project["id"])["clips"]
    assert saved["segments"][0]["interpretation"]["model"] == "fixture-v2"


def test_inference_failure_marks_the_clip_failed_without_partial_context(home, clip):
    import pytest
    from clipco_worker.vision import InferenceError

    worker = Worker(home, speech=RecordedSpeech(SPANS), vision=RecordedVision(fail=True))
    project = worker.create_project("Tutorial")
    stages = []

    with pytest.raises(InferenceError):
        worker.import_clip(project["id"], clip, progress=lambda stage, detail: stages.append(stage))

    [saved] = worker.snapshot(project["id"])["clips"]
    assert saved["status"] == "failed"
    assert "recorded failure" in saved["error"]
    assert saved["segments"] == []
    assert stages[-1] == "failed" and "describing" in stages
    assert not any((home / "frames").rglob("*.jpg"))


def test_an_interpretation_citing_no_supplied_evidence_is_not_saved(home, clip):
    import pytest
    from clipco_worker.vision import InferenceError

    vision = RecordedVision(only_invented=True)
    worker = Worker(home, speech=RecordedSpeech(SPANS), vision=vision)
    project = worker.create_project("Tutorial")

    with pytest.raises(InferenceError, match="evidence"):
        worker.import_clip(project["id"], clip)

    assert vision.calls == 2  # one retry, then the clip fails
    [saved] = worker.snapshot(project["id"])["clips"]
    assert saved["status"] == "failed" and saved["segments"] == []


def test_the_detected_spoken_language_is_saved_with_the_clip(home, clip):
    from clipco_worker.speech import TranscriptSpan

    taglish = [TranscriptSpan(0.0, 5.0, "Ngayon, ipapakita ko kung paano gumagana ang water filter."),
               TranscriptSpan(5.0, 11.0, "Actually, hindi chamber, yung upper tank pala.")]
    worker = Worker(home, speech=RecordedSpeech(taglish, language="tl"), vision=RecordedVision())
    project = worker.create_project("Water filter")

    worker.import_clip(project["id"], clip)

    [saved] = worker.snapshot(project["id"])["clips"]
    assert saved["speech_language"] == "tl"
    spoken = [t["text"] for s in saved["segments"] for t in s["transcript"]]
    assert "Actually, hindi chamber, yung upper tank pala." in spoken


def test_non_speech_annotations_are_not_saved_as_transcript(home, clip):
    from clipco_worker.speech import TranscriptSpan

    spans = [TranscriptSpan(0.0, 3.0, "(speaking in foreign language)"),
             TranscriptSpan(3.0, 6.0, "[BLANK_AUDIO]"),
             TranscriptSpan(6.0, 9.0, "Ito yung upper tank."),
             TranscriptSpan(9.0, 11.0, "[Music]")]
    worker = Worker(home, speech=RecordedSpeech(spans, language="tl"), vision=RecordedVision())
    project = worker.create_project("Water filter")

    worker.import_clip(project["id"], clip)

    [saved] = worker.snapshot(project["id"])["clips"]
    assert [t["text"] for s in saved["segments"] for t in s["transcript"]] == ["Ito yung upper tank."]


def test_a_repetition_loop_from_speech_recognition_is_collapsed(home, clip):
    from clipco_worker.speech import TranscriptSpan

    looped = [TranscriptSpan(0.0, 2.0, "Tapos pipilihin ni ate doon."),
              TranscriptSpan(2.0, 3.0, "Check."), TranscriptSpan(3.0, 4.0, "Check."),  # a real short repeat stays
              *[TranscriptSpan(4.0 + i, 5.0 + i, "Wala, nage-handlet dito.") for i in range(7)]]
    worker = Worker(home, speech=RecordedSpeech(looped, language="tl"), vision=RecordedVision())
    project = worker.create_project("Site visit")

    worker.import_clip(project["id"], clip)

    [saved] = worker.snapshot(project["id"])["clips"]
    lines = [t["text"] for s in saved["segments"] for t in s["transcript"]]
    assert lines == ["Tapos pipilihin ni ate doon.", "Check.", "Check.", "Wala, nage-handlet dito."]


def test_evidence_cited_as_its_prompt_line_is_matched_to_the_supplied_id(home, clip):
    worker = Worker(home, speech=RecordedSpeech(SPANS), vision=RecordedVision(echo_prompt_lines=True))
    project = worker.create_project("Tutorial")

    worker.import_clip(project["id"], clip)

    [saved] = worker.snapshot(project["id"])["clips"]
    assert saved["status"] == "ready"
    for seg in saved["segments"]:
        assert seg["observations"] and all(o["frame"]["id"].startswith("frm_") for o in seg["observations"])
        assert seg["interpretation"]["evidence_ids"] and seg["interpretation"]["rejected_refs"] == []


def test_the_project_description_reaches_agents_but_not_the_clip_descriptions(home, tmp_path):
    """A clip is described from what it shows and says, not from what the creator hopes the video is about."""
    from conftest import make_clip
    from test_mcp import call, payload

    from clipco_worker.vision import SYSTEM_PROMPT, build_prompt

    vision = RecordedVision()
    worker = Worker(home, speech=RecordedSpeech([]), vision=vision)
    project = worker.create_project("Demo", "Showing how to use clipco")
    worker.import_clip(project["id"], make_clip(tmp_path / "silent.mp4", seconds=6.0, audio=False))

    prompts = [SYSTEM_PROMPT + build_prompt(r) for r in vision.requests]
    assert prompts and not any("clipco" in p.lower() or "how to use" in p for p in prompts)
    # With no speech, the model is told not to claim anyone is talking or explaining.
    assert all("no speech" in build_prompt(r) for r in vision.requests)
    assert "do not say anyone is speaking" in SYSTEM_PROMPT.lower()

    overview = payload(call(home, ("get_project_overview", {"project_id": project["id"]}))[0])
    assert overview["project"]["context"] == "Showing how to use clipco"
