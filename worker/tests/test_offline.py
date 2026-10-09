"""Offline proof: a live local import and search, recorded only when the internet is shown to be unreachable."""

import json
import subprocess

import pytest
from conftest import SPANS, RecordedSpeech, RecordedVision, make_clip, sha256
from test_creator_controls import WORKER

from clipcon_worker.offline import StillOnline, offline_proof, probe_internet
from clipcon_worker.pipeline import Worker

UNREACHABLE = {"internet_reachable": False, "method": "fixture",
               "targets": [{"target": "1.1.1.1:443", "reachable": False, "error": "No route to host"}]}
REACHABLE = {"internet_reachable": True, "method": "fixture",
             "targets": [{"target": "1.1.1.1:443", "reachable": True, "error": None}]}


def test_an_offline_run_indexes_a_new_clip_live_and_finds_it_locally(home, clip, tmp_path):
    before = sha256(clip)
    speech, vision = RecordedSpeech(SPANS), RecordedVision()
    worker = Worker(home, speech=speech, vision=vision)
    project = worker.create_project("Offline proof")

    report = offline_proof(worker, project["id"], clip, ["colour bars"], probe=lambda: UNREACHABLE)

    assert report["offline"] == UNREACHABLE
    assert report["import"]["live_inference"] is True and report["import"]["status"] == "ready"
    assert speech.calls == 1 and vision.calls >= 1
    assert report["import"]["segments"] >= 1 and report["import"]["elapsed_seconds"] >= 0
    [search] = report["searches"]
    assert search["query"] == "colour bars" and search["elapsed_ms"] >= 0
    assert search["top"][0]["original_filename"] == "talking-head.mp4"
    assert search["top"][0]["segment_id"].startswith("seg_")
    assert report["models"]["speech"] == speech.identity and report["models"]["vision"] == vision.identity
    assert report["verdict"] == {"offline_verified": True, "reasons": []}
    assert sha256(clip) == before


def test_reused_context_is_not_presented_as_live_offline_inference(home, clip):
    worker = Worker(home, speech=RecordedSpeech(SPANS), vision=RecordedVision())
    project = worker.create_project("Offline proof")
    worker.import_clip(project["id"], clip)  # indexed earlier, while online

    report = offline_proof(worker, project["id"], clip, ["colour bars"], probe=lambda: UNREACHABLE)

    assert report["import"]["live_inference"] is False
    assert report["verdict"]["offline_verified"] is False
    assert any("already indexed" in r for r in report["verdict"]["reasons"])


def test_nothing_is_indexed_while_the_internet_is_reachable(home, clip):
    speech, vision = RecordedSpeech(SPANS), RecordedVision()
    worker = Worker(home, speech=speech, vision=vision)
    project = worker.create_project("Offline proof")

    with pytest.raises(StillOnline) as refused:
        offline_proof(worker, project["id"], clip, ["colour bars"], probe=lambda: REACHABLE)

    assert "1.1.1.1:443" in str(refused.value)
    assert speech.calls == 0 and worker.snapshot(project["id"])["clips"] == []


def test_the_command_refuses_on_this_connected_machine_before_loading_any_model(home, tmp_path):
    if not probe_internet(timeout=2)["internet_reachable"]:
        pytest.skip("this machine is offline; the refusal path needs a reachable internet")
    clip = make_clip(tmp_path / "new.mp4", seconds=2.0)
    subprocess.run([str(WORKER), "--home", str(home), "create-project", "--name", "P"], check=True,
                   capture_output=True)
    pid = json.loads(subprocess.run([str(WORKER), "--home", str(home), "projects"], capture_output=True,
                                    text=True).stdout.splitlines()[-1])["projects"][0]["id"]
    proc = subprocess.run([str(WORKER), "--home", str(home), "offline-proof", "--project", pid, str(clip)],
                          capture_output=True, text=True, timeout=60)
    event = json.loads(proc.stdout.splitlines()[-1])
    assert proc.returncode == 1 and event["kind"] == "StillOnline"
    assert "reachable" in event["message"]
