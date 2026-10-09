"""SQLite footage index. The worker is the only writer; results publish in one transaction.

The Footage library owns Source clips and their shared analysis. A Project membership associates a source with
a Project and carries that Project's creator note and exclusion; a source can have none, one, or many.
"""

import json
import shutil
import sqlite3
import time
from pathlib import Path

from . import relationships, roles, tone

# Bump with a migration step when the index's ownership model changes.
LIBRARY_VERSION = 1

SOURCE_CLIPS = """
CREATE TABLE IF NOT EXISTS source_clips (
  id TEXT PRIMARY KEY,
  source_path TEXT NOT NULL, original_filename TEXT NOT NULL,
  fingerprint TEXT, size_bytes INTEGER, mtime REAL,
  status TEXT NOT NULL CHECK (status IN ('pending','indexing','ready','failed','stale','missing')),
  stage TEXT, error TEXT,
  duration REAL, width INTEGER, height INTEGER, fps REAL, video_codec TEXT, audio_codec TEXT,
  label TEXT, role TEXT, role_basis TEXT, speech_language TEXT,
  revision INTEGER NOT NULL DEFAULT 0, analysis_key TEXT,
  reuse_allowed INTEGER NOT NULL DEFAULT 1, origin_project_id TEXT,
  created_at REAL NOT NULL, updated_at REAL NOT NULL
);
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, context TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL
);
""" + SOURCE_CLIPS + """
CREATE TABLE IF NOT EXISTS memberships (
  project_id TEXT NOT NULL REFERENCES projects(id), clip_id TEXT NOT NULL REFERENCES source_clips(id),
  excluded INTEGER NOT NULL DEFAULT 0, note TEXT, note_updated_at REAL, created_at REAL NOT NULL,
  PRIMARY KEY (project_id, clip_id)
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
  role TEXT NOT NULL DEFAULT 'needs_review', role_basis TEXT NOT NULL DEFAULT '',
  CHECK (start >= 0 AND end_ > start)
);
CREATE TABLE IF NOT EXISTS segment_roles (
  clip_id TEXT NOT NULL REFERENCES source_clips(id), start REAL NOT NULL, end_ REAL NOT NULL,
  role TEXT NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY (clip_id, start, end_)
);
-- One saved emotional-tone reading per Segment (absent: Not analyzed); the creator's tones are kept apart, keyed
-- by source range like role corrections.
CREATE TABLE IF NOT EXISTS tone_analyses (
  segment_id TEXT PRIMARY KEY REFERENCES segments(id), clip_id TEXT NOT NULL REFERENCES source_clips(id),
  tones TEXT NOT NULL, connotations TEXT NOT NULL, depicted_emotion TEXT NOT NULL, rejected_refs TEXT NOT NULL,
  recipe TEXT NOT NULL, model TEXT NOT NULL, analyzed_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tone_corrections (
  clip_id TEXT NOT NULL REFERENCES source_clips(id), start REAL NOT NULL, end_ REAL NOT NULL,
  tones TEXT NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY (clip_id, start, end_)
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
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS retired_segments (
  id TEXT PRIMARY KEY, clip_id TEXT NOT NULL REFERENCES source_clips(id), revision INTEGER NOT NULL,
  retired_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS relationships (
  id TEXT NOT NULL, project_id TEXT NOT NULL REFERENCES projects(id), kind TEXT NOT NULL,
  a_segment TEXT NOT NULL REFERENCES segments(id), b_segment TEXT NOT NULL REFERENCES segments(id),
  a_evidence TEXT NOT NULL, b_evidence TEXT NOT NULL, basis TEXT NOT NULL,
  PRIMARY KEY (project_id, id)
);
-- IDs of duplicate imports consolidated into one source: each resolves only within its own Project.
CREATE TABLE IF NOT EXISTS clip_aliases (
  id TEXT PRIMARY KEY, clip_id TEXT NOT NULL REFERENCES source_clips(id), project_id TEXT NOT NULL
);
-- Analysis jobs: queued work bound to its source and destination when requested. Its lifecycle is separate from
-- the source's analysis status; clip_id is not a foreign key, so a job outlives a source removed from the library.
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, operation TEXT NOT NULL, clip_id TEXT NOT NULL, project_id TEXT,
  source_path TEXT NOT NULL, original_filename TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('queued','active','waiting','completed','failed','cancelled','interrupted')),
  stage TEXT, progress TEXT, error TEXT, outcome TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0, owner TEXT,
  prior_status TEXT, prior_error TEXT, prior_revision INTEGER, attempts INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL, started_at REAL, finished_at REAL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS segment_aliases (
  id TEXT PRIMARY KEY, clip_id TEXT NOT NULL REFERENCES source_clips(id), project_id TEXT NOT NULL,
  original_filename TEXT NOT NULL
);
"""


class SourceRemoved(Exception):
    """The source was removed from the library while its analysis ran; nothing is published for it."""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.home = path.parent
        self.db = sqlite3.connect(path, isolation_level=None, timeout=30)  # the queue runner writes too
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        legacy = self._columns("source_clips")
        if "project_id" in legacy:  # a Project-owned index from before the Footage library
            if "speech_language" not in legacy:  # indexes created before multilingual speech
                self.db.execute("ALTER TABLE source_clips ADD COLUMN speech_language TEXT")
            if "excluded" not in legacy:  # indexes created before creator exclusions
                self.db.execute("ALTER TABLE source_clips ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0")
            self._migrate_to_library()
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('library_version', ?)", (str(LIBRARY_VERSION),))
        derived = self.db.execute("SELECT value FROM meta WHERE key='relationships_version'").fetchone()
        if derived is None or int(derived[0]) != relationships.VERSION:  # saved before these rules existed
            with self._transaction():
                for project in self.projects():
                    self._relate(project["id"])
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('relationships_version', ?)",
                                (str(relationships.VERSION),))

    def _columns(self, table: str) -> set[str]:
        return {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}

    def _transaction(self):
        store = self

        class Transaction:
            def __enter__(self):
                store.db.execute("BEGIN IMMEDIATE")

            def __exit__(self, kind, value, tb):
                store.db.execute("ROLLBACK" if kind else "COMMIT")
                return False
        return Transaction()

    def _migrate_to_library(self) -> None:
        """Move a Project-owned index to library-owned sources with Project memberships, in one transaction.

        Notes and exclusions move to the membership of the Project they were written in. The same original
        imported into several Projects (same path and verified content) becomes one source: the best analysis
        is kept and the duplicates' IDs become aliases that resolve only within their own Project. Segments get
        no new role evidence: they await review. No inference is started."""
        db = self.db
        backup = self.home / f"index.pre-library-v{LIBRARY_VERSION}.sqlite"
        if not backup.exists():  # the migration is one-way: keep the Project-owned index as it was
            with sqlite3.connect(backup) as copy:
                db.backup(copy)
        db.execute("PRAGMA foreign_keys=OFF")  # the source table is rebuilt; checked again before committing
        removed_frames = []
        db.executescript(SCHEMA.replace(SOURCE_CLIPS, ""))  # the new tables (executescript commits first)
        with self._transaction():
            if "creator_notes" not in {r[0] for r in db.execute("SELECT name FROM sqlite_master")}:
                db.execute("CREATE TABLE creator_notes (clip_id TEXT PRIMARY KEY, text TEXT, updated_at REAL)")
            db.execute(SOURCE_CLIPS.replace("source_clips", "library_sources"))
            shared = [c for c in self._columns("source_clips")
                      if c in self._columns("library_sources") and c not in ("reuse_allowed", "origin_project_id")]
            db.execute(f"INSERT INTO library_sources ({', '.join(shared)}, origin_project_id)"
                       f" SELECT {', '.join(shared)}, project_id FROM source_clips")
            db.execute("INSERT INTO memberships (project_id, clip_id, excluded, note, note_updated_at, created_at)"
                       " SELECT c.project_id, c.id, c.excluded, n.text, n.updated_at, c.created_at"
                       " FROM source_clips c LEFT JOIN creator_notes n ON n.clip_id = c.id")
            groups: dict[tuple, list] = {}
            for c in db.execute("SELECT * FROM source_clips WHERE fingerprint IS NOT NULL AND revision > 0"
                                " ORDER BY created_at"):
                groups.setdefault((c["source_path"], c["fingerprint"]), []).append(dict(c))
            for clips in groups.values():
                if len(clips) < 2:
                    continue
                keep = min(clips, key=lambda c: (c["status"] != "ready", c["created_at"]))
                for dup in (c for c in clips if c is not keep):
                    db.execute("UPDATE memberships SET clip_id=? WHERE clip_id=?", (keep["id"], dup["id"]))
                    db.execute("INSERT INTO clip_aliases VALUES (?,?,?)", (dup["id"], keep["id"], dup["project_id"]))
                    for (seg_id,) in db.execute("SELECT id FROM segments WHERE clip_id=? UNION"
                                                " SELECT id FROM retired_segments WHERE clip_id=?",
                                                (dup["id"], dup["id"])).fetchall():
                        db.execute("INSERT INTO segment_aliases VALUES (?,?,?,?)",
                                   (seg_id, keep["id"], dup["project_id"], dup["original_filename"]))
                    self._delete_context(dup["id"])
                    db.execute("DELETE FROM library_sources WHERE id=?", (dup["id"],))
                    removed_frames.append(dup["id"])
            db.execute("DROP TABLE creator_notes")
            db.execute("DROP TABLE source_clips")
            db.execute("ALTER TABLE library_sources RENAME TO source_clips")
            if "role" not in self._columns("segments"):
                db.execute("ALTER TABLE segments ADD COLUMN role TEXT NOT NULL DEFAULT 'needs_review'")
                db.execute("ALTER TABLE segments ADD COLUMN role_basis TEXT NOT NULL DEFAULT ''")
            for c in db.execute("SELECT id, role, role_basis FROM source_clips").fetchall():
                db.execute("UPDATE segments SET role='needs_review', role_basis=? WHERE clip_id=?",
                           (roles.legacy_basis(c["role"], c["role_basis"]), c["id"]))
            db.execute("DROP TABLE relationships")  # re-created keyed per Project, then re-derived
            db.execute("DELETE FROM meta WHERE key='relationships_version'")  # re-derived from memberships
            if problems := db.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError(f"library migration left dangling references: {[tuple(p) for p in problems]}")
            db.execute("INSERT OR REPLACE INTO meta VALUES ('library_version', ?)", (str(LIBRARY_VERSION),))
        for clip_id in removed_frames:  # the kept analysis has its own frames
            shutil.rmtree(self.home / "frames" / clip_id, ignore_errors=True)

    # Projects

    def create_project(self, project_id: str, name: str, context: str) -> dict:
        self.db.execute("INSERT INTO projects VALUES (?,?,?,?)", (project_id, name, context, time.time()))
        return self.project(project_id)

    def project(self, project_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return dict(row) if row else None

    def projects(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM projects ORDER BY created_at")]

    def _require_project(self, project_id: str) -> None:
        if self.project(project_id) is None:
            raise ValueError(f"unknown project {project_id}")

    # Sources and memberships

    def source_by_path(self, source_path: str, project_id: str | None = None) -> dict | None:
        """The library source at this original path, preferring one that is already in the given Project."""
        row = self.db.execute(
            "SELECT c.* FROM source_clips c LEFT JOIN memberships m ON m.clip_id = c.id AND m.project_id=?"
            " WHERE c.source_path=? ORDER BY m.clip_id IS NULL, c.revision = 0, c.created_at",
            (project_id, source_path)).fetchone()
        return dict(row) if row else None

    def add_clip(self, clip_id: str, source_path: str, filename: str, project_id: str | None) -> None:
        """Register a new library source, in a Project when one is given."""
        now = time.time()
        with self._transaction():
            self.db.execute(
                "INSERT INTO source_clips (id, source_path, original_filename, status, origin_project_id,"
                " created_at, updated_at) VALUES (?,?,?, 'pending', ?, ?, ?)",
                (clip_id, source_path, filename, project_id, now, now))
            if project_id is not None:
                self.db.execute("INSERT INTO memberships (project_id, clip_id, created_at) VALUES (?,?,?)",
                                (project_id, clip_id, now))

    def add_membership(self, project_id: str, clip_id: str) -> bool:
        """Associate an existing library source with a Project (no analysis is repeated). Returns whether it
        is newly associated; an existing membership keeps its note and exclusion."""
        self._require_project(project_id)
        with self._transaction():
            if self.clip(clip_id) is None:
                raise ValueError(f"unknown clip {clip_id}")
            added = self.db.execute("INSERT OR IGNORE INTO memberships (project_id, clip_id, created_at)"
                                    " VALUES (?,?,?)", (project_id, clip_id, time.time())).rowcount == 1
            if added:
                self._relate(project_id)
            return added

    def membership(self, project_id: str, clip_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM memberships WHERE project_id=? AND clip_id=?",
                              (project_id, clip_id)).fetchone()
        return dict(row) if row else None

    def memberships(self, clip_id: str) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT m.*, p.name AS project_name FROM memberships m JOIN projects p ON p.id = m.project_id"
            " WHERE m.clip_id=? ORDER BY m.created_at", (clip_id,))]

    def resolve_clip(self, clip_id: str, project_id: str | None = None) -> str:
        """The current library ID for a clip ID the app or agent holds. A duplicate's alias resolves only in
        the Project it was imported into, so it never reaches another Project's membership."""
        if self.clip(clip_id):
            return clip_id
        alias = self.db.execute("SELECT * FROM clip_aliases WHERE id=?", (clip_id,)).fetchone()
        if alias and project_id in (None, alias["project_id"]):
            return alias["clip_id"]
        raise ValueError(f"unknown clip {clip_id}" + (f" in project {project_id}" if project_id else ""))

    def require_member(self, project_id: str, clip_id: str) -> None:
        if not self.membership(project_id, clip_id):
            raise ValueError(f"clip {clip_id} is not in project {project_id}")

    def set_status(self, clip_id: str, status: str, stage: str | None = None, error: str | None = None) -> None:
        self.db.execute("UPDATE source_clips SET status=?, stage=?, error=?, updated_at=? WHERE id=?",
                        (status, stage, error, time.time(), clip_id))

    def publish(self, clip_id: str, clip_fields: dict, analysis: dict, segments: list[dict]) -> int:
        """Replace a source's shared context with a completed analysis atomically, then mark it ready. Every
        Project it belongs to has its relationships re-derived in the same transaction."""
        db = self.db
        with self._transaction():
            row = db.execute("SELECT revision FROM source_clips WHERE id=?", (clip_id,)).fetchone()
            if row is None:
                raise SourceRemoved(f"clip {clip_id} was removed from the library during analysis")
            revision = row[0] + 1
            projects = [r[0] for r in db.execute("SELECT project_id FROM memberships WHERE clip_id=?", (clip_id,))]
            old = [r[0] for r in db.execute("SELECT id FROM segments WHERE clip_id=?", (clip_id,))]
            for seg_id in old:  # replaced, but an agent may still hold the ID: remember whose it was
                db.execute("INSERT OR REPLACE INTO retired_segments VALUES (?,?,?,?)",
                           (seg_id, clip_id, revision - 1, time.time()))
            self._delete_segments(clip_id)
            for seg in segments:
                db.execute("INSERT INTO segments VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                    seg["id"], clip_id, seg["ordinal"], seg["start"], seg["end"], seg["label"],
                    seg["interpretation"], json.dumps(seg["evidence_ids"]), json.dumps(seg["rejected_refs"]),
                    seg["role"], seg["role_basis"]))
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
            for project_id in projects:
                self._relate(project_id)
            return revision

    def clip(self, clip_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM source_clips WHERE id=?", (clip_id,)).fetchone()
        return dict(row) if row else None

    def clips(self, project_id: str) -> list[dict]:
        """A Project's sources, each with its membership's exclusion."""
        return [dict(r) for r in self.db.execute(
            "SELECT c.*, m.excluded FROM memberships m JOIN source_clips c ON c.id = m.clip_id"
            " WHERE m.project_id=? ORDER BY m.created_at, c.created_at", (project_id,))]

    def library_clips(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM source_clips ORDER BY created_at")]

    def analysis(self, clip_id: str, revision: int) -> dict | None:
        row = self.db.execute("SELECT * FROM analyses WHERE clip_id=? AND revision=?", (clip_id, revision)).fetchone()
        return dict(row) if row else None

    def set_source(self, clip_id: str, source_path: str, filename: str, size_bytes: int, mtime: float) -> None:
        """Record where a clip's unchanged original now is (same content, so same clip and context)."""
        self.db.execute("UPDATE source_clips SET source_path=?, original_filename=?, size_bytes=?, mtime=?,"
                        " updated_at=? WHERE id=?", (source_path, filename, size_bytes, mtime, time.time(), clip_id))

    # Creator choices

    def set_note(self, project_id: str, clip_id: str, text: str) -> dict | None:
        """Save the creator's note for a clip in one Project (empty text clears it). Notes sit beside the shared
        analysed evidence and survive re-analysis; they never replace it. Other Projects see a note only through
        library results this membership supplies, attributed to this Project, and never while it is excluded."""
        self.require_member(project_id, clip_id)
        text = text.strip()
        self.db.execute("UPDATE memberships SET note=?, note_updated_at=? WHERE project_id=? AND clip_id=?",
                        (text or None, time.time() if text else None, project_id, clip_id))
        return self.note(project_id, clip_id)

    def note(self, project_id: str, clip_id: str) -> dict | None:
        m = self.membership(project_id, clip_id)
        return {"project_id": project_id, "clip_id": clip_id, "text": m["note"], "updated_at": m["note_updated_at"]} \
            if m and m["note"] else None

    def set_excluded(self, project_id: str, clip_ids: list[str], excluded: bool) -> None:
        """Exclude clips' memberships from (or restore them to) a Project's agent results. Reversible."""
        with self._transaction():
            for clip_id in clip_ids:
                if self.db.execute("UPDATE memberships SET excluded=? WHERE clip_id=? AND project_id=?",
                                   (int(excluded), clip_id, project_id)).rowcount != 1:
                    raise ValueError(f"clip {clip_id} is not in project {project_id}")

    def set_reuse(self, clip_ids: list[str], allowed: bool) -> None:
        """Allow or prevent every cross-project reuse of these sources. Their own Projects are unaffected."""
        with self._transaction():
            for clip_id in clip_ids:
                if self.db.execute("UPDATE source_clips SET reuse_allowed=? WHERE id=?",
                                   (int(allowed), clip_id)).rowcount != 1:
                    raise ValueError(f"unknown clip {clip_id}")

    def set_segment_role(self, segment_id: str, role: str | None) -> dict:
        """Record (or clear, with None) the creator's role for a Segment. It is kept beside the suggested role
        and keyed by the Segment's source range, so it still applies after re-analysis yields the same range."""
        if role is not None and role not in roles.ROLES:
            raise ValueError(f"unknown role {role!r}; choose one of {', '.join(roles.ROLES)}")
        seg = self.db.execute("SELECT * FROM segments WHERE id=?", (segment_id,)).fetchone()
        if seg is None:
            raise ValueError(f"unknown segment {segment_id}")
        key = (seg["clip_id"], seg["start"], seg["end_"])
        if role is None:
            self.db.execute("DELETE FROM segment_roles WHERE clip_id=? AND start=? AND end_=?", key)
        else:
            self.db.execute("INSERT OR REPLACE INTO segment_roles VALUES (?,?,?,?,?)", (*key, role, time.time()))
        return self._role(seg)

    def _role(self, seg) -> dict:
        creator = self.db.execute("SELECT role, updated_at FROM segment_roles WHERE clip_id=? AND start=? AND end_=?",
                                  (seg["clip_id"], seg["start"], seg["end_"])).fetchone()
        return {"suggested": seg["role"], "basis": seg["role_basis"],
                "creator": creator["role"] if creator else None,
                "creator_updated_at": creator["updated_at"] if creator else None,
                "effective": roles.effective(seg["role"], creator["role"] if creator else None)}

    def save_tone(self, segment_id: str, reading, recipe: dict, model: dict) -> bool:
        """Save a Segment's tone reading. Returns False, saving nothing, if the Segment was replaced or removed
        while it was being read (its evidence is no longer current)."""
        with self._transaction():
            seg = self.db.execute("SELECT clip_id FROM segments WHERE id=?", (segment_id,)).fetchone()
            if seg is None:
                return False
            self.db.execute("INSERT OR REPLACE INTO tone_analyses VALUES (?,?,?,?,?,?,?,?,?)", (
                segment_id, seg["clip_id"], json.dumps(reading.tones), json.dumps(reading.connotations),
                reading.depicted_emotion, json.dumps(reading.rejected_refs), json.dumps(recipe), json.dumps(model),
                time.time()))
            return True

    def set_segment_tones(self, segment_id: str, tones: list[str] | None) -> dict:
        """Record (or clear, with None) the creator's tones for a Segment; an empty list says it has none. Kept
        beside the model's suggestions, which are never rewritten, and keyed by the Segment's source range."""
        unknown = [t for t in tones or [] if t not in tone.VOCABULARY]
        if unknown:
            raise ValueError(f"unknown tone {unknown[0]!r}; use one of {', '.join(tone.VOCABULARY)}")
        seg = self.db.execute("SELECT * FROM segments WHERE id=?", (segment_id,)).fetchone()
        if seg is None:
            raise ValueError(f"unknown segment {segment_id}")
        key = (seg["clip_id"], seg["start"], seg["end_"])
        if tones is None:
            self.db.execute("DELETE FROM tone_corrections WHERE clip_id=? AND start=? AND end_=?", key)
        else:
            self.db.execute("INSERT OR REPLACE INTO tone_corrections VALUES (?,?,?,?,?)",
                            (*key, json.dumps(list(dict.fromkeys(tones))), time.time()))
        return tone.read(self.db, seg)

    # Removal: originals are never touched

    def _delete_segments(self, clip_id: str) -> None:
        db = self.db
        for (seg_id,) in db.execute("SELECT id FROM segments WHERE clip_id=?", (clip_id,)).fetchall():
            db.execute("DELETE FROM relationships WHERE a_segment=? OR b_segment=?", (seg_id, seg_id))
            db.execute("DELETE FROM observations WHERE segment_id=?", (seg_id,))
            db.execute("DELETE FROM tone_analyses WHERE segment_id=?", (seg_id,))
            db.execute("DELETE FROM frames WHERE segment_id=?", (seg_id,))
            db.execute("DELETE FROM transcript_spans WHERE segment_id=?", (seg_id,))
        db.execute("DELETE FROM segments WHERE clip_id=?", (clip_id,))

    def _delete_context(self, clip_id: str) -> None:
        """Delete one source's analysed context rows (inside a caller's transaction)."""
        self._delete_segments(clip_id)
        for table in ("analyses", "retired_segments", "segment_roles", "tone_corrections"):
            self.db.execute(f"DELETE FROM {table} WHERE clip_id=?", (clip_id,))

    def remove_memberships(self, project_id: str, clip_ids: list[str]) -> None:
        """Remove clips from a Project: its note and exclusion for them go, the library sources stay."""
        with self._transaction():
            for clip_id in clip_ids:
                if self.db.execute("DELETE FROM memberships WHERE project_id=? AND clip_id=?",
                                   (project_id, clip_id)).rowcount != 1:
                    raise ValueError(f"clip {clip_id} is not in project {project_id}")
            self._relate(project_id)

    def remove_from_library(self, clip_ids: list[str]) -> list[str]:
        """Delete sources' saved context, memberships and aliases in one transaction; the Projects they were in
        have relationships re-derived from what remains. Returns the affected Project IDs."""
        db = self.db
        with self._transaction():
            projects: set[str] = set()
            for clip_id in clip_ids:
                if self.clip(clip_id) is None:
                    raise ValueError(f"unknown clip {clip_id}")
                projects |= {r[0] for r in db.execute("SELECT project_id FROM memberships WHERE clip_id=?",
                                                      (clip_id,))}
                self._delete_context(clip_id)
                for table in ("memberships", "clip_aliases", "segment_aliases"):
                    db.execute(f"DELETE FROM {table} WHERE clip_id=?", (clip_id,))
                db.execute("DELETE FROM source_clips WHERE id=?", (clip_id,))
                # Its unstarted work is removed; an active job is asked to stop (and could not publish anyway).
                now = time.time()
                db.execute("UPDATE jobs SET state='cancelled', error='The source was removed from the library.',"
                           " finished_at=?, updated_at=? WHERE clip_id=? AND state IN ('queued','waiting','interrupted')",
                           (now, now, clip_id))
                db.execute("UPDATE jobs SET cancel_requested=1, updated_at=? WHERE clip_id=? AND state='active'",
                           (now, clip_id))
            for project_id in projects:
                self._relate(project_id)
            return sorted(projects)

    def delete_project(self, project_id: str) -> None:
        """Delete a Project, its memberships and their notes; its sources stay in the library."""
        db = self.db
        with self._transaction():
            if not self.project(project_id):
                raise ValueError(f"unknown project {project_id}")
            for table in ("relationships", "memberships", "clip_aliases", "segment_aliases"):
                db.execute(f"DELETE FROM {table} WHERE project_id=?", (project_id,))
            db.execute("UPDATE source_clips SET origin_project_id=NULL WHERE origin_project_id=?", (project_id,))
            db.execute("DELETE FROM projects WHERE id=?", (project_id,))

    def _relate(self, project_id: str) -> None:
        """Re-derive the Project's suggested relationships from its members' published Segments (inside the
        caller's transaction, so readers never see relationships that disagree with the Segments they cite)."""
        db = self.db
        db.execute("DELETE FROM relationships WHERE project_id=?", (project_id,))
        segments = []
        for s in db.execute("SELECT s.id, s.clip_id, s.start, s.end_, s.label, c.role FROM memberships m"
                            " JOIN source_clips c ON c.id = m.clip_id JOIN segments s ON s.clip_id = c.id"
                            " WHERE m.project_id=? ORDER BY m.created_at, c.created_at, s.ordinal",
                            (project_id,)).fetchall():
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

    # Review

    def _clip_review(self, clip: dict) -> dict:
        db = self.db
        clip["reuse_allowed"] = bool(clip["reuse_allowed"])
        clip["projects"] = [{"project_id": m["project_id"], "name": m["project_name"], "excluded": bool(m["excluded"])}
                            for m in self.memberships(clip["id"])]
        analysis = db.execute("SELECT * FROM analyses WHERE clip_id=? AND revision=?",
                              (clip["id"], clip["revision"])).fetchone()
        vision = json.loads(analysis["vision_identity"]) if analysis else {}
        clip["analysis"] = None if analysis is None else {
            "revision": analysis["revision"], "elapsed": analysis["elapsed"],
            "recipe": json.loads(analysis["recipe"]), "speech": json.loads(analysis["speech_identity"]),
            "vision": vision, "finished_at": analysis["finished_at"]}
        clip["segments"] = []
        for s in db.execute("SELECT * FROM segments WHERE clip_id=? ORDER BY ordinal", (clip["id"],)).fetchall():
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
                "role": self._role(s),
                "tone": tone.read(db, s),
            })
        clip["role_summary"] = roles.summary([s["role"]["effective"] for s in clip["segments"]])
        # Corrections made for Segment ranges a later re-analysis no longer has: kept and shown, never dropped.
        ranges = {(s["start"], s["end"]) for s in clip["segments"]}
        clip["unmatched_role_corrections"] = [
            {"start": r["start"], "end": r["end_"], "role": r["role"], "updated_at": r["updated_at"]}
            for r in db.execute("SELECT * FROM segment_roles WHERE clip_id=? ORDER BY start", (clip["id"],))
            if (r["start"], r["end_"]) not in ranges]
        clip["unmatched_tone_corrections"] = [
            {"start": r["start"], "end": r["end_"], "tones": json.loads(r["tones"]), "updated_at": r["updated_at"]}
            for r in db.execute("SELECT * FROM tone_corrections WHERE clip_id=? ORDER BY start", (clip["id"],))
            if (r["start"], r["end_"]) not in ranges]
        return clip

    def review_clip(self, clip_id: str) -> dict:
        return self._clip_review(self.clip(clip_id))

    def snapshot(self, project_id: str) -> dict:
        clips = []
        for c in self.clips(project_id):
            clip = self._clip_review(c)
            clip["excluded"] = bool(clip["excluded"])
            clip["note"] = self.note(project_id, clip["id"])
            clips.append(clip)
        return {"project": self.project(project_id), "clips": clips}

    def library_snapshot(self) -> dict:
        """Every library source with its shared context and Project associations (no Project notes)."""
        return {"project": None, "clips": [{**self._clip_review(c), "excluded": False, "note": None}
                                           for c in self.library_clips()]}
