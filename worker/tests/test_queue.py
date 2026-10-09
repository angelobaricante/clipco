"""Durable analysis jobs: register footage at once, then run it through a recoverable Sequential queue.

Jobs are driven at the worker entry point (JobQueue over a Worker) and the saved results are observed through
the stdio MCP boundary Codex uses.
"""

import time
from pathlib import Path

from conftest import SPANS, RecordedSpeech, RecordedVision, ScriptedVision, make_clip, sha256
from test_mcp import call, payload

from clipco_worker.jobs import JobQueue
from clipco_worker.pipeline import Worker


def overview(home: Path, project_id: str) -> dict:
    [result] = call(home, ("get_project_overview", {"project_id": project_id}))
    return {c["original_filename"]: c["status"] for c in payload(result)["clips"]}


def states(queue: JobQueue) -> dict[str, str]:
    return {j["original_filename"]: j["state"] for j in queue.list()["jobs"]}


def footage(tmp_path: Path) -> Path:
    folder = tmp_path / "drop"
    (folder / "day1" / "nested").mkdir(parents=True)
    make_clip(folder / "day1" / "intro.mp4", seconds=4)
    make_clip(folder / "day1" / "nested" / "pour.mov", seconds=4, audio=False)
    (folder / "day1" / "notes.txt").write_text("not a video")
    return folder


def test_dropped_items_register_promptly_without_models_and_summarise_what_was_skipped(home, tmp_path):
    folder = footage(tmp_path)
    loose = make_clip(tmp_path / "loose.mp4", seconds=4)
    before = {p: sha256(p) for p in folder.rglob("*.m*")}
    vision = RecordedVision()
    worker = Worker(home, speech=RecordedSpeech(SPANS), vision=vision)
    project = worker.create_project("Kitchen")
    queue = JobQueue(worker, ready=lambda: {"state": "service_unavailable", "detail": "Ollama is not running",
                                              "guidance": "Start Ollama"})

    # A folder, a file inside it again (overlap), a loose file, an unsupported file and a path that is gone.
    outcome = queue.enqueue_import(project["id"], [folder, folder / "day1" / "intro.mp4", loose,
                                                   folder / "day1" / "notes.txt", tmp_path / "gone.mp4"])

    assert sorted(j["original_filename"] for j in outcome["jobs"]) == ["intro.mp4", "loose.mp4", "pour.mov"]
    assert {s["reason"] for s in outcome["skipped"]} == {"unsupported", "inaccessible"}
    assert {Path(s["path"]).name for s in outcome["skipped"]} == {"notes.txt", "gone.mp4"}
    assert vision.calls == 0
    assert set(states(queue).values()) == {"queued"}
    assert overview(home, project["id"]) == {"intro.mp4": "pending", "loose.mp4": "pending", "pour.mov": "pending"}

    # Dropping the same footage again does not queue the same work twice.
    again = queue.enqueue_import(project["id"], [folder])
    assert again["jobs"] == [] and len(again["already_queued"]) == 2
    assert len(queue.list()["jobs"]) == 3

    # Setup is incomplete: running waits instead of failing or publishing anything.
    queue.run()
    assert set(states(queue).values()) == {"waiting"}
    assert queue.list()["jobs"][0]["error"] == "Ollama is not running"
    assert overview(home, project["id"]) == {"intro.mp4": "pending", "loose.mp4": "pending", "pour.mov": "pending"}
    assert {p: sha256(p) for p in folder.rglob("*.m*")} == before


def test_jobs_run_one_at_a_time_appended_work_keeps_its_destination_and_a_failure_spares_the_rest(home, tmp_path):
    folder = footage(tmp_path)
    later = make_clip(tmp_path / "later.mp4", seconds=4)
    vision = ScriptedVision({}, fail={"intro.mp4"})
    worker = Worker(home, speech=RecordedSpeech(SPANS), vision=vision)
    kitchen, garden = worker.create_project("Kitchen"), worker.create_project("Garden")
    queue = JobQueue(worker)
    queue.enqueue_import(kitchen["id"], [folder])
    active_seen = []

    def during(request):  # while a job runs: the creator drops more footage onto another Project
        active_seen.append(queue.list()["counts"]["active"])
        if request.original_filename == "pour.mov" and not states(queue).get("later.mp4"):
            queue.enqueue_import(garden["id"], [later])
    vision.on_describe = during

    outcome = queue.run()

    assert set(active_seen) == {1}  # Sequential: never two active jobs
    assert not outcome["already_running"]
    assert states(queue) == {"intro.mp4": "failed", "pour.mov": "completed", "later.mp4": "completed"}
    assert "recorded failure" in next(j for j in outcome["jobs"] if j["original_filename"] == "intro.mp4")["error"]
    assert overview(home, kitchen["id"]) == {"intro.mp4": "failed", "pour.mov": "ready"}
    assert overview(home, garden["id"]) == {"later.mp4": "ready"}  # bound when queued, not when it ran

    # Retrying the failure runs only it; completed analysis is not repeated.
    vision.fail.clear()
    calls = vision.calls
    [failed] = [j["id"] for j in queue.list()["jobs"] if j["state"] == "failed"]
    queue.retry([failed])
    queue.run()
    assert states(queue)["intro.mp4"] == "completed"
    assert overview(home, kitchen["id"]) == {"intro.mp4": "ready", "pour.mov": "ready"}
    assert vision.calls - calls == 1  # one Segment of the 4-second clip, nothing else re-described


def three_clips(tmp_path: Path) -> Path:
    folder = tmp_path / "three"
    folder.mkdir()
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        make_clip(folder / name, seconds=4)
    return folder


def test_pause_lets_the_active_clip_finish_and_starts_nothing_new_until_resumed(home, tmp_path):
    vision = ScriptedVision({})
    worker = Worker(home, speech=RecordedSpeech(SPANS), vision=vision)
    project = worker.create_project("Kitchen")
    queue = JobQueue(worker)
    queue.enqueue_import(project["id"], [three_clips(tmp_path)])
    vision.on_describe = lambda request: queue.pause()

    queue.run()

    assert states(queue) == {"a.mp4": "completed", "b.mp4": "queued", "c.mp4": "queued"}
    assert queue.list()["paused"]
    vision.on_describe = lambda request: None
    queue.resume()
    queue.run()
    assert set(states(queue).values()) == {"completed"}
    assert set(overview(home, project["id"]).values()) == {"ready"}


def test_cancelling_queued_and_active_work_keeps_footage_and_leaves_a_truthful_retryable_state(home, tmp_path):
    folder = three_clips(tmp_path)
    before = {p.name: sha256(p) for p in folder.iterdir()}
    vision = ScriptedVision({})
    worker = Worker(home, speech=RecordedSpeech(SPANS), vision=vision)
    project = worker.create_project("Kitchen")
    queue = JobQueue(worker)
    jobs = {j["original_filename"]: j["id"] for j in queue.enqueue_import(project["id"], [folder])["jobs"]}
    queue.cancel([jobs["c.mp4"]])  # still queued
    vision.on_describe = lambda request: request.original_filename == "a.mp4" and queue.cancel([jobs["a.mp4"]])

    queue.run()

    assert states(queue) == {"a.mp4": "cancelled", "b.mp4": "completed", "c.mp4": "cancelled"}
    clips = overview(home, project["id"])
    assert clips == {"a.mp4": "failed", "b.mp4": "ready", "c.mp4": "failed"}  # not analysed, nothing published
    snapshot = {c["original_filename"]: c for c in worker.snapshot(project["id"])["clips"]}
    assert "cancelled" in snapshot["a.mp4"]["error"] and not snapshot["a.mp4"]["segments"]
    assert not list((home / "frames" / snapshot["a.mp4"]["id"]).glob("*/*.jpg"))  # no orphaned frames
    assert {p.name: sha256(p) for p in folder.iterdir()} == before

    vision.on_describe = lambda request: None
    queue.retry([jobs["a.mp4"]])
    queue.run()
    assert overview(home, project["id"])["a.mp4"] == "ready"


def test_cancelling_from_another_process_stops_the_active_jobs_child_process(home, tmp_path):
    import subprocess
    import threading

    from clipco_worker import cancel
    from clipco_worker.cli import main as cli

    started = threading.Event()
    children = []

    class SlowSpeech(RecordedSpeech):
        def transcribe(self, wav_path):
            started.set()
            proc = subprocess.Popen  # record the child that cancel.run starts
            subprocess.Popen = lambda *a, **k: children.append(proc(*a, **k)) or children[-1]
            try:
                cancel.run(["sleep", "30"])
            finally:
                subprocess.Popen = proc
            return super().transcribe(wav_path)

    worker = Worker(home, speech=SlowSpeech(SPANS), vision=ScriptedVision({}))
    project = worker.create_project("Kitchen")
    queue = JobQueue(worker)
    [job] = queue.enqueue_import(project["id"], [make_clip(tmp_path / "long.mp4", seconds=4)])["jobs"]
    # The runner owns its own connection, as the app's long-running run-queue process does.
    runner = threading.Thread(target=lambda: JobQueue(Worker(home, speech=SlowSpeech(SPANS),
                                                             vision=ScriptedVision({}))).run())
    runner.start()
    assert started.wait(30)
    assert JobQueue(Worker(home, speech=None, vision=None)).running()

    t0 = time.monotonic()
    assert cli(["--home", str(home), "cancel", job["id"]]) == 0  # as the app's Cancel button does
    runner.join(20)

    assert not runner.is_alive() and time.monotonic() - t0 < 10
    assert children and all(c.poll() is not None for c in children)  # the child was stopped, not orphaned
    assert states(queue) == {"long.mp4": "cancelled"}
    assert overview(home, project["id"]) == {"long.mp4": "failed"}
    assert not queue.running()


class Crash(BaseException):
    """Stands in for the runner process dying mid-job (power loss, force quit): nothing is cleaned up."""


def test_restart_reconciles_interrupted_work_and_resumes_only_when_asked_without_repeating_completed_analysis(
        home, tmp_path):
    vision = ScriptedVision({})
    worker = Worker(home, speech=RecordedSpeech(SPANS), vision=vision)
    project = worker.create_project("Kitchen")
    queue = JobQueue(worker)
    queue.enqueue_import(project["id"], [three_clips(tmp_path)])

    def die(request):
        if request.original_filename == "b.mp4":
            raise Crash()
    vision.on_describe = die
    try:
        queue.run()
    except Crash:
        pass
    assert states(queue) == {"a.mp4": "completed", "b.mp4": "active", "c.mp4": "queued"}

    # Clipco starts again.
    vision = ScriptedVision({})
    restarted = JobQueue(Worker(home, speech=RecordedSpeech(SPANS), vision=vision))
    listing = restarted.reconcile()
    assert states(restarted) == {"a.mp4": "completed", "b.mp4": "interrupted", "c.mp4": "interrupted"}
    assert not listing["running"]
    assert overview(home, project["id"]) == {"a.mp4": "ready", "b.mp4": "pending", "c.mp4": "pending"}
    restarted.run()  # nothing runs until the creator resumes
    assert vision.calls == 0 and states(restarted)["b.mp4"] == "interrupted"

    restarted.resume()
    restarted.run()
    assert set(states(restarted).values()) == {"completed"}
    assert set(overview(home, project["id"]).values()) == {"ready"}
    assert vision.calls == 2  # b and c only; a's completed analysis was kept


def test_removing_a_source_resolves_its_jobs_and_a_late_publisher_cannot_resurrect_it(home, tmp_path):
    folder = three_clips(tmp_path)
    before = {p.name: sha256(p) for p in folder.iterdir()}
    vision = ScriptedVision({})
    worker = Worker(home, speech=RecordedSpeech(SPANS), vision=vision)
    project = worker.create_project("Kitchen")
    queue = JobQueue(worker)
    jobs = {j["original_filename"]: j for j in queue.enqueue_import(project["id"], [folder])["jobs"]}

    seen = []

    def remove_during(request):  # the creator removes a (active) and c (queued) from the library mid-analysis
        if request.original_filename == "a.mp4":
            worker.remove_from_library([jobs["a.mp4"]["clip_id"], jobs["c.mp4"]["clip_id"]])
            seen.append({j["original_filename"]: (j["state"], j["cancel_requested"]) for j in queue.list()["jobs"]})
    vision.on_describe = remove_during

    queue.run()

    assert seen == [{"a.mp4": ("active", True), "b.mp4": ("queued", False), "c.mp4": ("cancelled", False)}]
    assert states(queue) == {"a.mp4": "cancelled", "b.mp4": "completed", "c.mp4": "cancelled"}
    assert overview(home, project["id"]) == {"b.mp4": "ready"}
    [result] = call(home, ("search_footage", {"project_id": project["id"], "query": "test pattern"}))
    assert {h["original_filename"] for h in payload(result)["results"]} <= {"b.mp4"}
    assert not (home / "frames" / jobs["a.mp4"]["clip_id"]).exists()
    assert {p.name: sha256(p) for p in folder.iterdir()} == before


def test_reanalysis_and_tone_reading_are_queued_jobs_that_reuse_cached_evidence(home, tmp_path):
    clip = make_clip(tmp_path / "pour.mp4", seconds=4, audio=False)
    vision = ScriptedVision({}, tones={"pour.mp4": {"tones": [("calm", "slow pour")]}})
    worker = Worker(home, speech=RecordedSpeech(SPANS), vision=vision, tone_on_import=False)
    project = worker.create_project("Kitchen")
    queue = JobQueue(worker)
    [job] = queue.enqueue_import(project["id"], [clip])["jobs"]
    queue.run()
    calls = vision.calls

    queued = queue.enqueue("enrich_tone", project["id"], [job["clip_id"]])
    assert queue.enqueue("enrich_tone", project["id"], [job["clip_id"]])["already_queued"]  # no duplicate
    queue.run()

    assert queue.job(queued["jobs"][0]["id"])["state"] == "completed"
    assert vision.calls == calls and vision.tone_calls == 1  # tone from saved evidence, nothing re-described
    [result] = call(home, ("search_footage", {"scope": "library", "query": "calm pour", "tone": "calm"}))
    assert [h["original_filename"] for h in payload(result)["results"]] == ["pour.mp4"]

    queue.enqueue("reanalyse", project["id"], [job["clip_id"]])
    queue.run()
    assert vision.calls == calls  # unchanged content and settings: the saved analysis is reused
    assert overview(home, project["id"]) == {"pour.mp4": "ready"}


def test_quitting_the_app_stops_the_runner_and_leaves_its_job_interrupted_for_resume(home, tmp_path):
    vision = ScriptedVision({})
    worker = Worker(home, speech=RecordedSpeech(SPANS), vision=vision)
    project = worker.create_project("Kitchen")
    queue = JobQueue(worker)
    queue.enqueue_import(project["id"], [three_clips(tmp_path)])
    vision.on_describe = lambda request: request.original_filename == "b.mp4" and queue.stop()  # SIGTERM on quit

    queue.run()

    assert states(queue) == {"a.mp4": "completed", "b.mp4": "interrupted", "c.mp4": "queued"}
    assert overview(home, project["id"]) == {"a.mp4": "ready", "b.mp4": "pending", "c.mp4": "pending"}
    restarted = JobQueue(Worker(home, speech=RecordedSpeech(SPANS), vision=ScriptedVision({})))
    restarted.reconcile()
    assert states(restarted) == {"a.mp4": "completed", "b.mp4": "interrupted", "c.mp4": "interrupted"}
