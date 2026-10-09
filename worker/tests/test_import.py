from conftest import SPANS, RecordedSpeech, RecordedVision

from clipcon_worker.pipeline import Worker


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
    from clipcon_worker.vision import InferenceError

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
