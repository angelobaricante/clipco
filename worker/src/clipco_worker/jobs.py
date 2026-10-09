"""Durable analysis jobs, run one at a time (Sequential).

Requesting work registers the footage at once (no model or service is needed) and records a job bound to its
source, destination and operation. One runner per Clipco home executes jobs in order; a job's lifecycle (queued,
active, waiting, completed, failed, cancelled, interrupted) is kept apart from the source's analysis status.

- Pause stops new jobs from starting; the active one finishes.
- Cancelling a queued job removes the work; cancelling the active one stops its child processes and inference
  request, publishes nothing, and returns the source to its state before the job.
- A runner that died leaves its jobs interrupted (reconcile); they run again only after an explicit resume.
  Completed analysis is reused, never repeated.
- Missing setup (models, Ollama) makes jobs wait instead of failing or substituting anything.
"""

import contextlib
import fcntl
import json
import os
import shutil
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import cancel
from .pipeline import Progress, Worker, discover, missing_guidance, new_id
from .vision import ServiceUnavailable

OPERATIONS = ("import", "reanalyse", "enrich_tone")
# Jobs that still hold their work; a second request for the same source and kind of work joins them instead.
UNFINISHED = ("queued", "active", "waiting", "interrupted")
ANALYSIS = ("import", "reanalyse")

NOT_STARTED = "Analysis was cancelled before it finished; nothing was saved. Retry to analyse it."

# Polling interval for a cancellation requested from another process.
CANCEL_POLL_SECONDS = 0.2


def same_work(operation: str) -> tuple[str, ...]:
    return ANALYSIS if operation in ANALYSIS else (operation,)


class JobQueue:
    def __init__(self, worker: Worker, ready: Callable[[], dict | None] = lambda: None):
        """ready() returns None when analysis can run, or {state, detail, guidance} describing what is missing."""
        self.worker = worker
        self.store = worker.store
        self.db = worker.store.db
        self.ready = ready
        self.lock_path = worker.home / "queue.lock"
        self._stopping = False

    # Requests

    def enqueue_import(self, project_id: str | None, paths: list[Path]) -> dict:
        """Register every video among the chosen files and folders in the destination now, and queue its
        analysis. Unsupported and inaccessible items are summarised; the valid ones are still accepted."""
        if project_id is not None and self.store.project(project_id) is None:
            raise ValueError(f"unknown project {project_id}")
        sources, skipped = discover(paths)
        jobs, already = [], []
        for source in sources:
            clip_id, _ = self.worker._register(project_id, source)
            job = self._add("import", clip_id, project_id)
            (jobs if job["created"] else already).append(job["job"])
        return {"jobs": jobs, "already_queued": already, "skipped": skipped}

    def enqueue(self, operation: str, project_id: str | None, clip_ids: list[str]) -> dict:
        """Queue re-analysis or tone enrichment of sources the destination already has."""
        if operation not in OPERATIONS[1:]:
            raise ValueError(f"unknown operation {operation}")
        for clip_id in clip_ids:
            self.worker._require(project_id, clip_id)
        jobs, already = [], []
        for clip_id in clip_ids:
            job = self._add(operation, clip_id, project_id)
            (jobs if job["created"] else already).append(job["job"])
        return {"jobs": jobs, "already_queued": already, "skipped": []}

    def _add(self, operation: str, clip_id: str, project_id: str | None) -> dict:
        with self.store._transaction():
            marks = ",".join("?" * len(UNFINISHED))
            kinds = same_work(operation)
            existing = self.db.execute(
                f"SELECT * FROM jobs WHERE clip_id=? AND state IN ({marks})"
                f" AND operation IN ({','.join('?' * len(kinds))}) ORDER BY created_at LIMIT 1",
                (clip_id, *UNFINISHED, *kinds)).fetchone()
            if existing:
                return {"created": False, "job": self._view(existing)}
            clip = self.store.clip(clip_id)
            now = time.time()
            job_id = new_id("job")
            self.db.execute(
                "INSERT INTO jobs (id, operation, clip_id, project_id, source_path, original_filename, state,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?, 'queued', ?, ?)",
                (job_id, operation, clip_id, project_id, clip["source_path"], clip["original_filename"], now, now))
        return {"created": True, "job": self.job(job_id)}

    # Reading

    def job(self, job_id: str) -> dict:
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown job {job_id}")
        return self._view(row)

    @staticmethod
    def _view(row) -> dict:
        job = {k: row[k] for k in ("id", "operation", "clip_id", "project_id", "source_path", "original_filename",
                                   "state", "stage", "error", "attempts", "created_at", "started_at", "finished_at")}
        job["progress"] = json.loads(row["progress"]) if row["progress"] else None
        job["outcome"] = json.loads(row["outcome"]) if row["outcome"] else None
        job["cancel_requested"] = bool(row["cancel_requested"])
        return job

    def list(self) -> dict:
        jobs = [self._view(r) for r in self.db.execute("SELECT * FROM jobs ORDER BY created_at, rowid")]
        counts = {state: 0 for state in ("queued", "active", "waiting", "completed", "failed", "cancelled",
                                         "interrupted")}
        for j in jobs:
            counts[j["state"]] += 1
        return {"jobs": jobs, "counts": counts, "paused": self.paused, "running": self.running()}

    @property
    def paused(self) -> bool:
        row = self.db.execute("SELECT value FROM meta WHERE key='queue_paused'").fetchone()
        return bool(row and row[0] == "1")

    def running(self) -> bool:
        """Whether a runner currently owns the queue (in any process)."""
        with self._runner_lock() as held:
            return not held

    @contextlib.contextmanager
    def _runner_lock(self):
        """Exclusive ownership of the queue: held for a runner's lifetime, released by the OS if it dies."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    # Creator controls

    def pause(self) -> dict:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES ('queue_paused', '1')")
        return self.list()

    def resume(self) -> dict:
        """Un-pause, and offer interrupted and waiting jobs to the runner again."""
        with self.store._transaction():
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('queue_paused', '0')")
            self.db.execute("UPDATE jobs SET state='queued', error=NULL, updated_at=?"
                            " WHERE state IN ('interrupted', 'waiting')", (time.time(),))
        return self.list()

    def cancel(self, job_ids: list[str]) -> dict:
        """Queued or waiting work is removed at once; the active job is asked to stop (its runner contains its
        child processes and restores the source). Footage and saved context are never deleted."""
        for job_id in job_ids:
            job = self.job(job_id)
            if job["state"] == "active":
                self.db.execute("UPDATE jobs SET cancel_requested=1, updated_at=? WHERE id=?", (time.time(), job_id))
                if self._owned_here(job_id):
                    cancel.cancel()
            elif job["state"] in ("queued", "waiting", "interrupted"):
                self._finish_unstarted(job_id, "cancelled", "Cancelled before it started.")
        return self.list()

    def retry(self, job_ids: list[str]) -> dict:
        """Queue failed, cancelled or interrupted jobs again (completed analysis is reused when they run)."""
        for job_id in job_ids:
            job = self.job(job_id)
            if job["state"] not in ("failed", "cancelled", "interrupted"):
                raise ValueError(f"job {job_id} is {job['state']}; only failed, cancelled or interrupted jobs retry")
            if self.store.clip(job["clip_id"]) is None:
                raise ValueError(f"{job['original_filename']} was removed from the library; import it again")
            other = self.db.execute(
                f"SELECT 1 FROM jobs WHERE clip_id=? AND id<>? AND state IN ({','.join('?' * len(UNFINISHED))})"
                f" AND operation IN ({','.join('?' * len(same_work(job['operation'])))})",
                (job["clip_id"], job_id, *UNFINISHED, *same_work(job["operation"]))).fetchone()
            if other:
                raise ValueError(f"{job['original_filename']} already has this work queued")
            self.db.execute("UPDATE jobs SET state='queued', stage=NULL, progress=NULL, error=NULL, outcome=NULL,"
                            " cancel_requested=0, finished_at=NULL, updated_at=? WHERE id=?", (time.time(), job_id))
        return self.list()

    def clear_finished(self) -> dict:
        self.db.execute("DELETE FROM jobs WHERE state IN ('completed', 'cancelled')")
        return self.list()

    def reconcile(self) -> dict:
        """After a restart: work left by a runner that is no longer alive is marked interrupted (its sources are
        returned to their state before it), to run again only after an explicit resume."""
        with self._runner_lock() as held:
            if held:
                self._interrupt_orphans(include_queued=True)
        return self.list()

    def _interrupt_orphans(self, include_queued: bool) -> None:
        states = ("active", "queued") if include_queued else ("active",)
        for row in self.db.execute(f"SELECT * FROM jobs WHERE state IN ({','.join('?' * len(states))})",
                                   states).fetchall():
            if row["state"] == "active":
                self._settle_unfinished(row, "interrupted", "Clipco stopped while this job was running. "
                                                            "Resume to run it again.")
            else:
                self.db.execute("UPDATE jobs SET state='interrupted', error=?, updated_at=? WHERE id=?",
                                ("Clipco stopped before this job started. Resume to run it.", time.time(),
                                 row["id"]))

    def stop(self) -> None:
        """The runner is being shut down (the app quit): contain the active job's work, leave it interrupted for
        an explicit resume, and start nothing else. Safe to call from a signal handler."""
        self._stopping = True
        cancel.cancel()

    def _owned_here(self, job_id: str) -> bool:
        row = self.db.execute("SELECT owner FROM jobs WHERE id=?", (job_id,)).fetchone()
        return bool(row and row["owner"] == str(os.getpid()))

    # Running

    def run(self, progress: Progress | None = None) -> dict:
        """Run queued jobs one after another until none is left, the queue is paused, or setup is missing.
        Returns at once if another runner owns the queue."""
        report = progress or (lambda stage, detail: None)
        with self._runner_lock() as held:
            if not held:
                return {"already_running": True, **self.list()}
            self._interrupt_orphans(include_queued=False)  # a runner that died mid-job
            self.db.execute("UPDATE jobs SET state='queued', error=NULL, updated_at=? WHERE state='waiting'",
                            (time.time(),))
            while not self.paused and not self._stopping:
                row = self.db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created_at, rowid"
                                      " LIMIT 1").fetchone()
                if row is None:
                    break
                if blocker := self.ready():
                    self._wait_all(blocker)
                    report("waiting", {"detail": blocker.get("detail")})
                    break
                if not self._claim(row["id"]):
                    continue
                if self._execute(self.job(row["id"]), report) == "waiting":
                    break
        return {"already_running": False, **self.list()}

    def _wait_all(self, blocker: dict) -> None:
        self.db.execute("UPDATE jobs SET state='waiting', error=?, stage=?, updated_at=? WHERE state='queued'",
                        (blocker.get("detail") or "Local analysis is not set up.", blocker.get("state"),
                         time.time()))

    def _claim(self, job_id: str) -> bool:
        with self.store._transaction():
            row = self.db.execute("SELECT * FROM jobs WHERE id=? AND state='queued'", (job_id,)).fetchone()
            if row is None:
                return False
            clip = self.store.clip(row["clip_id"])
            if clip is None:  # removed from the library while queued
                self.db.execute("UPDATE jobs SET state='cancelled', error=?, finished_at=?, updated_at=? WHERE id=?",
                                ("The source was removed from the library.", time.time(), time.time(), job_id))
                return False
            now = time.time()
            self.db.execute(
                "UPDATE jobs SET state='active', owner=?, stage=NULL, progress=NULL, error=NULL, cancel_requested=0,"
                " prior_status=?, prior_error=?, prior_revision=?, attempts=attempts+1, started_at=?, updated_at=?"
                " WHERE id=?", (str(os.getpid()), clip["status"], clip["error"], clip["revision"], now, now, job_id))
            return True

    def _execute(self, job: dict, report: Progress) -> str:
        cancel.reset()
        stop = threading.Event()
        watcher = threading.Thread(target=self._watch_cancel, args=(job["id"], stop), daemon=True)
        watcher.start()

        def step(stage: str, detail: dict) -> None:
            cancel.check()
            self.db.execute("UPDATE jobs SET stage=?, progress=?, updated_at=? WHERE id=?",
                            (stage, json.dumps(detail), time.time(), job["id"]))
            report(stage, {**detail, "job_id": job["id"]})

        report("job_started", {"job_id": job["id"], "clip_id": job["clip_id"], "operation": job["operation"]})
        try:
            outcome = self._perform(job, step)
        except cancel.Cancelled:
            state = self._settle_unfinished(self._row(job["id"]), *(
                ("interrupted", "Clipco quit while this job was running. Resume to run it again.") if self._stopping
                else ("cancelled", "Cancelled by the creator.")))
            report("job_" + state, {"job_id": job["id"], "clip_id": job["clip_id"]})
            return state
        except ServiceUnavailable as e:
            self._restore(self._row(job["id"]))  # an outage says nothing about the footage
            self._finish(job["id"], "waiting", str(e))
            self._wait_all({"detail": str(e), "state": "service_unavailable"})
            report("waiting", {"job_id": job["id"], "detail": str(e)})
            return "waiting"
        except Exception as e:  # recorded on the source too; the next job carries on
            self._finish(job["id"], "failed", f"{type(e).__name__}: {e}")
            report("job_failed", {"job_id": job["id"], "clip_id": job["clip_id"], "error": str(e)})
            return "failed"
        finally:
            stop.set()
            watcher.join()
            cancel.reset()
        if outcome.get("removed"):
            self._finish(job["id"], "cancelled", "The source was removed from the library.", outcome)
            report("job_cancelled", {"job_id": job["id"], "clip_id": job["clip_id"]})
            return "cancelled"
        failed = outcome.get("status") in ("failed", "missing")
        self._finish(job["id"], "failed" if failed else "completed", outcome.get("error"), outcome)
        report("job_failed" if failed else "job_completed", {"job_id": job["id"], "clip_id": job["clip_id"]})
        return "failed" if failed else "completed"

    def _perform(self, job: dict, step: Progress) -> dict:
        worker, clip_id = self.worker, job["clip_id"]
        if job["operation"] == "enrich_tone":
            worker.enrich_tone(None, [clip_id], step)
            [clip] = worker._outcome([clip_id])["clips"]
            return clip
        clip = self.store.clip(clip_id)
        source = Path(clip["source_path"])
        if not source.is_file():
            self.store.set_status(clip_id, "missing", error=missing_guidance(clip["source_path"]))
            return {"clip_id": clip_id, "status": "missing", "error": missing_guidance(clip["source_path"])}
        outcome = worker._index(clip_id, source, step, refresh=job["operation"] == "reanalyse")
        if outcome.get("removed"):
            return outcome
        return {**outcome, "status": self.store.clip(clip_id)["status"]}

    def _watch_cancel(self, job_id: str, stop: threading.Event) -> None:
        """Notice a cancellation requested by another process (the app's Cancel) and stop the job's work."""
        db = sqlite3.connect(self.store.home / "index.sqlite", timeout=30)
        try:
            while not stop.wait(CANCEL_POLL_SECONDS):
                row = db.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
                if row is None or row[0]:
                    cancel.cancel()
                    return
        finally:
            db.close()

    # State changes

    def _row(self, job_id: str):
        return self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def _finish(self, job_id: str, state: str, error: str | None, outcome: dict | None = None) -> None:
        now = time.time()
        self.db.execute("UPDATE jobs SET state=?, error=?, outcome=?, cancel_requested=0, finished_at=?,"
                        " updated_at=? WHERE id=?",
                        (state, error, json.dumps(outcome) if outcome else None,
                         now if state in ("completed", "failed", "cancelled") else None, now, job_id))

    def _settle_unfinished(self, row, state: str, error: str) -> str:
        """A job stopped part-way (cancelled, or its runner died). Its analysis publishes atomically, so either
        a new revision was published (the job completed after all) or nothing was, and the source returns to
        its state before the job."""
        clip = self.store.clip(row["clip_id"])
        if clip is None:
            shutil.rmtree(self.worker.home / "frames" / row["clip_id"], ignore_errors=True)
            self._finish(row["id"], "cancelled", "The source was removed from the library.")
            return "cancelled"
        if row["operation"] in ANALYSIS and row["prior_revision"] is not None and clip["revision"] > row["prior_revision"]:
            if clip["status"] == "indexing":  # published, then stopped while reading tone
                self.store.set_status(clip["id"], "ready")
            self._finish(row["id"], "completed", None, {"clip_id": clip["id"], "revision": clip["revision"]})
            return "completed"
        self._restore(row, cancelled=state == "cancelled")
        self._sweep_frames(clip["id"])
        self._finish(row["id"], state, error)
        return state

    def _restore(self, row, cancelled: bool = False) -> None:
        if row["prior_status"] is None or self.store.clip(row["clip_id"]) is None:
            return
        if row["prior_status"] == "pending" and cancelled:  # never analysed, and no work is left for it
            self.store.set_status(row["clip_id"], "failed", error=NOT_STARTED)
        else:
            self.store.set_status(row["clip_id"], row["prior_status"], error=row["prior_error"])

    def _finish_unstarted(self, job_id: str, state: str, error: str) -> None:
        row = self._row(job_id)
        clip = self.store.clip(row["clip_id"])
        if clip and clip["status"] == "pending" and row["operation"] == "import":
            self.store.set_status(clip["id"], "failed", error=NOT_STARTED)
        self._finish(job_id, state, error)

    def _sweep_frames(self, clip_id: str) -> None:
        """Remove frame folders a stopped analysis left behind (frames the index does not reference)."""
        folder = self.worker.home / "frames" / clip_id
        if not folder.is_dir():
            return
        kept = {Path(r[0]).parent for r in self.db.execute(
            "SELECT f.path FROM frames f JOIN segments s ON s.id = f.segment_id WHERE s.clip_id=?", (clip_id,))}
        for run in folder.iterdir():
            if run.is_dir() and run not in kept:
                shutil.rmtree(run, ignore_errors=True)
