"""SQLite footage index. The worker is the only writer; results publish in one transaction."""

import json
import sqlite3
import time
from pathlib import Path

from . import relationships

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, context TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS source_clips (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  source_path TEXT NOT NULL, original_filename TEXT NOT NULL,
  fingerprint TEXT, size_bytes INTEGER, mtime REAL,
  status TEXT NOT NULL CHECK (status IN ('pending','indexing','ready','failed','stale','missing')),
  stage TEXT, error TEXT,
  duration REAL, width INTEGER, height INTEGER, fps REAL, video_codec TEXT, audio_codec TEXT,
  label TEXT, role TEXT, role_basis TEXT, speech_language TEXT,
  revision INTEGER NOT NULL DEFAULT 0, analysis_key TEXT, excluded INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL, updated_at REAL NOT NULL,
  UNIQUE (project_id, source_path)
);
CREATE TABLE IF NOT EXISTS analyses (
  clip_id TEXT NOT NULL REFERENCES source_clips(id), revision INTEGER NOT NULL,
  analysis_key TEXT NOT NULL, recipe TEXT NOT NULL, speech_identity TEXT NOT NULL, vision_identity TEXT NOT NULL,
  started_at REAL NOT NULL, finished_at REAL NOT NULL, elapsed REAL NOT NULL,
  PRIMARY KEY (clip_id, revision)
);
CREATE TABLE IF NOT EXISTS segments (
  id TEXT PRIMARY KEY, clip_id TEXT NOT NULL REFERENCES source_clips(id), ordinal INTEGER NOT NULL,
  start REAL NOT NULL, end_ REAL NOT NULL, label TEXT NOT NULL,
  interpretation TEXT NOT NULL, interpretation_evidence TEXT NOT NULL, rejected_refs TEXT NOT NULL,
  CHECK (start >= 0 AND end_ > start)
);
CREATE TABLE IF NOT EXISTS transcript_spans (
  id TEXT PRIMARY KEY, segment_id TEXT NOT NULL REFERENCES segments(id), ordinal INTEGER NOT NULL,
  start REAL NOT NULL, end_ REAL NOT NULL, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS frames (
  id TEXT PRIMARY KEY, segment_id TEXT NOT NULL REFERENCES segments(id), time REAL NOT NULL, path TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations (
  frame_id TEXT NOT NULL REFERENCES frames(id), segment_id TEXT NOT NULL REFERENCES segments(id), text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS creator_notes (
  clip_id TEXT PRIMARY KEY REFERENCES source_clips(id), text TEXT NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS relationships (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), kind TEXT NOT NULL,
  a_segment TEXT NOT NULL REFERENCES segments(id), b_segment TEXT NOT NULL REFERENCES segments(id),
  a_evidence TEXT NOT NULL, b_evidence TEXT NOT NULL, basis TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        columns = {r["name"] for r in self.db.execute("PRAGMA table_info(source_clips)")}
        if "speech_language" not in columns:  # indexes created before multilingual speech
            self.db.execute("ALTER TABLE source_clips ADD COLUMN speech_language TEXT")
        if "excluded" not in columns:  # indexes created before creator exclusions
            self.db.execute("ALTER TABLE source_clips ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0")
        derived = self.db.execute("SELECT value FROM meta WHERE key='relationships_version'").fetchone()
        if derived is None or int(derived[0]) != relationships.VERSION:  # saved before these rules existed
            self.db.execute("BEGIN IMMEDIATE")
            try:
                for project in self.projects():
                    self.db.execute("DELETE FROM relationships WHERE project_id=?", (project["id"],))
                    self._relate(project["id"])
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('relationships_version', ?)",
                                (str(relationships.VERSION),))
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def create_project(self, project_id: str, name: str, context: str) -> dict:
        self.db.execute("INSERT INTO projects VALUES (?,?,?,?)", (project_id, name, context, time.time()))
        return self.project(project_id)

    def project(self, project_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return dict(row) if row else None

    def projects(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM projects ORDER BY created_at")]

    def clip_by_path(self, project_id: str, source_path: str) -> dict | None:
        row = self.db.execute("SELECT * FROM source_clips WHERE project_id=? AND source_path=?",
                              (project_id, source_path)).fetchone()
        return dict(row) if row else None

    def project_context_for_clip(self, clip_id: str) -> str:
        return self.db.execute("SELECT p.context FROM projects p JOIN source_clips c ON c.project_id=p.id"
                               " WHERE c.id=?", (clip_id,)).fetchone()[0]

    def add_clip(self, clip_id: str, project_id: str, source_path: str, filename: str) -> None:
        now = time.time()
        self.db.execute(
            "INSERT INTO source_clips (id, project_id, source_path, original_filename, status, created_at, updated_at)"
            " VALUES (?,?,?,?, 'pending', ?, ?)", (clip_id, project_id, source_path, filename, now, now))

    def set_status(self, clip_id: str, status: str, stage: str | None = None, error: str | None = None) -> None:
        self.db.execute("UPDATE source_clips SET status=?, stage=?, error=?, updated_at=? WHERE id=?",
                        (status, stage, error, time.time(), clip_id))

    def publish(self, clip_id: str, clip_fields: dict, analysis: dict, segments: list[dict]) -> int:
        """Replace a clip's context with a completed analysis atomically, then mark it ready."""
        db = self.db
        db.execute("BEGIN IMMEDIATE")
        try:
            revision = db.execute("SELECT revision FROM source_clips WHERE id=?", (clip_id,)).fetchone()[0] + 1
            project_id = db.execute("SELECT project_id FROM source_clips WHERE id=?", (clip_id,)).fetchone()[0]
            db.execute("DELETE FROM relationships WHERE project_id=?", (project_id,))
            old = [r[0] for r in db.execute("SELECT id FROM segments WHERE clip_id=?", (clip_id,))]
            for seg_id in old:
                db.execute("DELETE FROM observations WHERE segment_id=?", (seg_id,))
                db.execute("DELETE FROM frames WHERE segment_id=?", (seg_id,))
                db.execute("DELETE FROM transcript_spans WHERE segment_id=?", (seg_id,))
            db.execute("DELETE FROM segments WHERE clip_id=?", (clip_id,))
            for seg in segments:
                db.execute("INSERT INTO segments VALUES (?,?,?,?,?,?,?,?,?)", (
                    seg["id"], clip_id, seg["ordinal"], seg["start"], seg["end"], seg["label"],
                    seg["interpretation"], json.dumps(seg["evidence_ids"]), json.dumps(seg["rejected_refs"])))
                for i, t in enumerate(seg["transcript"]):
                    db.execute("INSERT INTO transcript_spans VALUES (?,?,?,?,?,?)",
                               (t["id"], seg["id"], i, t["start"], t["end"], t["text"]))
                for f in seg["frames"]:
                    db.execute("INSERT INTO frames VALUES (?,?,?,?)", (f["id"], seg["id"], f["time"], f["path"]))
                for frame_id, text in seg["observations"]:
                    db.execute("INSERT INTO observations VALUES (?,?,?)", (frame_id, seg["id"], text))
            db.execute("INSERT INTO analyses VALUES (?,?,?,?,?,?,?,?,?)", (
                clip_id, revision, analysis["key"], json.dumps(analysis["recipe"]),
                json.dumps(analysis["speech"]), json.dumps(analysis["vision"]),
                analysis["started_at"], analysis["finished_at"], analysis["finished_at"] - analysis["started_at"]))
            sets = ", ".join(f"{k}=?" for k in clip_fields)
            db.execute(f"UPDATE source_clips SET {sets}, status='ready', stage=NULL, error=NULL, revision=?,"
                       f" analysis_key=?, updated_at=? WHERE id=?",
                       (*clip_fields.values(), revision, analysis["key"], time.time(), clip_id))
            self._relate(project_id)
            db.execute("COMMIT")
            return revision
        except BaseException:
            db.execute("ROLLBACK")
            raise

    def set_note(self, clip_id: str, text: str) -> dict | None:
        """Save the creator's note for a clip (empty text clears it). Notes sit beside the analysed evidence and
        survive re-analysis; they never replace it."""
        if not self.db.execute("SELECT 1 FROM source_clips WHERE id=?", (clip_id,)).fetchone():
            raise ValueError(f"unknown clip {clip_id}")
        text = text.strip()
        if not text:
            self.db.execute("DELETE FROM creator_notes WHERE clip_id=?", (clip_id,))
            return None
        self.db.execute("INSERT OR REPLACE INTO creator_notes VALUES (?,?,?)", (clip_id, text, time.time()))
        return self.note(clip_id)

    def set_excluded(self, project_id: str, clip_ids: list[str], excluded: bool) -> None:
        """Exclude clips from (or restore them to) new default searches. Reversible: no context is deleted."""
        db = self.db
        db.execute("BEGIN IMMEDIATE")
        try:
            for clip_id in clip_ids:
                if db.execute("UPDATE source_clips SET excluded=? WHERE id=? AND project_id=?",
                              (int(excluded), clip_id, project_id)).rowcount != 1:
                    raise ValueError(f"clip {clip_id} is not in project {project_id}")
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise

    def note(self, clip_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM creator_notes WHERE clip_id=?", (clip_id,)).fetchone()
        return dict(row) if row else None

    def _delete_clip(self, clip_id: str) -> None:
        """Delete one clip's saved context rows (inside a caller's transaction)."""
        db = self.db
        for (seg_id,) in db.execute("SELECT id FROM segments WHERE clip_id=?", (clip_id,)).fetchall():
            db.execute("DELETE FROM observations WHERE segment_id=?", (seg_id,))
            db.execute("DELETE FROM frames WHERE segment_id=?", (seg_id,))
            db.execute("DELETE FROM transcript_spans WHERE segment_id=?", (seg_id,))
        db.execute("DELETE FROM segments WHERE clip_id=?", (clip_id,))
        db.execute("DELETE FROM analyses WHERE clip_id=?", (clip_id,))
        db.execute("DELETE FROM creator_notes WHERE clip_id=?", (clip_id,))
        db.execute("DELETE FROM source_clips WHERE id=?", (clip_id,))

    def remove_clips(self, project_id: str, clip_ids: list[str]) -> None:
        """Remove clips and their saved context from a Project in one transaction; relationships are re-derived
        from what remains. Original files are not touched."""
        db = self.db
        db.execute("BEGIN IMMEDIATE")
        try:
            for clip_id in clip_ids:
                if not db.execute("SELECT 1 FROM source_clips WHERE id=? AND project_id=?",
                                  (clip_id, project_id)).fetchone():
                    raise ValueError(f"clip {clip_id} is not in project {project_id}")
            db.execute("DELETE FROM relationships WHERE project_id=?", (project_id,))
            for clip_id in clip_ids:
                self._delete_clip(clip_id)
            self._relate(project_id)
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise

    def delete_project(self, project_id: str) -> list[str]:
        """Delete a Project and all its saved context in one transaction; returns the removed clip IDs."""
        db = self.db
        db.execute("BEGIN IMMEDIATE")
        try:
            if not self.project(project_id):
                raise ValueError(f"unknown project {project_id}")
            clip_ids = [r[0] for r in db.execute("SELECT id FROM source_clips WHERE project_id=?", (project_id,))]
            db.execute("DELETE FROM relationships WHERE project_id=?", (project_id,))
            for clip_id in clip_ids:
                self._delete_clip(clip_id)
            db.execute("DELETE FROM projects WHERE id=?", (project_id,))
            db.execute("COMMIT")
            return clip_ids
        except BaseException:
            db.execute("ROLLBACK")
            raise

    def _relate(self, project_id: str) -> None:
        """Re-derive the Project's suggested relationships from its published Segments (inside publish's
        transaction, so readers never see relationships that disagree with the Segments they cite)."""
        db = self.db
        segments = []
        for s in db.execute("SELECT s.id, s.clip_id, s.start, s.end_, s.label, c.role FROM segments s"
                            " JOIN source_clips c ON c.id = s.clip_id WHERE c.project_id=?"
                            " ORDER BY c.created_at, s.ordinal", (project_id,)).fetchall():
            segments.append({
                "id": s["id"], "clip_id": s["clip_id"], "start": s["start"], "end": s["end_"], "label": s["label"],
                "role": s["role"],
                "transcript": [{"id": t["id"], "start": t["start"], "end": t["end_"], "text": t["text"]}
                               for t in db.execute("SELECT * FROM transcript_spans WHERE segment_id=?"
                                                   " ORDER BY ordinal", (s["id"],))],
                "observations": [{"id": o["frame_id"], "text": o["text"]}
                                 for o in db.execute("SELECT * FROM observations WHERE segment_id=?"
                                                     " ORDER BY rowid", (s["id"],))],
            })
        for r in relationships.relate(segments):
            db.execute("INSERT INTO relationships VALUES (?,?,?,?,?,?,?,?)", (
                r["id"], project_id, r["kind"], r["a_segment"], r["b_segment"],
                json.dumps(r["a_evidence"]), json.dumps(r["b_evidence"]), r["basis"]))

    def snapshot(self, project_id: str) -> dict:
        db = self.db
        clips = []
        for c in db.execute("SELECT * FROM source_clips WHERE project_id=? ORDER BY created_at", (project_id,)):
            clip = dict(c)
            clip["excluded"] = bool(clip["excluded"])
            clip["note"] = self.note(clip["id"])
            analysis = db.execute("SELECT * FROM analyses WHERE clip_id=? AND revision=?",
                                  (clip["id"], clip["revision"])).fetchone()
            vision = json.loads(analysis["vision_identity"]) if analysis else {}
            clip["analysis"] = None if analysis is None else {
                "revision": analysis["revision"], "elapsed": analysis["elapsed"],
                "recipe": json.loads(analysis["recipe"]), "speech": json.loads(analysis["speech_identity"]),
                "vision": vision, "finished_at": analysis["finished_at"]}
            clip["segments"] = []
            for s in db.execute("SELECT * FROM segments WHERE clip_id=? ORDER BY ordinal", (clip["id"],)):
                frames = {f["id"]: {"id": f["id"], "time": f["time"], "path": f["path"]}
                          for f in db.execute("SELECT * FROM frames WHERE segment_id=? ORDER BY time", (s["id"],))}
                clip["segments"].append({
                    "id": s["id"], "start": s["start"], "end": s["end_"], "label": s["label"],
                    "transcript": [{"id": t["id"], "start": t["start"], "end": t["end_"], "text": t["text"]}
                                   for t in db.execute("SELECT * FROM transcript_spans WHERE segment_id=?"
                                                       " ORDER BY ordinal", (s["id"],))],
                    "observations": [{"frame": frames[o["frame_id"]], "text": o["text"]}
                                     for o in db.execute("SELECT * FROM observations WHERE segment_id=?"
                                                         " ORDER BY rowid", (s["id"],))],
                    "interpretation": {"text": s["interpretation"],
                                       "evidence_ids": json.loads(s["interpretation_evidence"]),
                                       "rejected_refs": json.loads(s["rejected_refs"]),
                                       "model": vision.get("model")},
                })
            clips.append(clip)
        return {"project": self.project(project_id), "clips": clips}
