"""Read-only retrieval over the saved footage index. Never loads inference models or writes the index."""

import json
import os
from collections import Counter
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from . import roles
from .text import matches, terms, words

DEFAULT_HOME = Path.home() / "Library" / "Application Support" / "Clipcon"


def default_home() -> Path:
    return Path(os.environ.get("CLIPCON_HOME", DEFAULT_HOME))


SEARCH_PAGE = 5
CONTEXT_WINDOW_MAX = 120.0
CONTEXT_LINES_MAX = 60
PREVIEW_BYTES_MAX = 200_000
PREVIEW_WIDTH_MAX = 512
SEARCH_PAGE_MAX = 10
EXCERPT_CHARS = 240

# What the other Segment of a relationship is, seen from its first (a) and second (b) Segment; listed in the
# order relationships are shown.
RELATED_AS = {"spoken_correction": ("correction", "earlier_statement"),
              "repeated_take": ("other_take", "other_take"),
              "supporting_broll": ("suggested_broll", "a_roll_explanation")}
# A relationship whose two sides fall in the same Segment is reported once as "within_segment".
RELATIONSHIPS_PER_RESULT = 3
RELATIONSHIPS_PER_CONTEXT = 10

# Evidence kinds a match can rest on, and how strongly each counts toward relevance.
WEIGHTS = {"transcript": 3.0, "creator_note": 3.0, "label": 2.0, "interpretation": 2.0, "observation": 1.5}
# Further matching lines add less than the best one, so long Segments do not win on length alone.
SUPPORTING_WEIGHT = 0.25


# What each non-ready status means for an agent holding that clip's saved context.
STATUS_NOTES = {
    "pending": "Not analysed yet; no context is saved for it.",
    "indexing": "Being analysed now. Any context shown is from its previous analysis and may be replaced.",
    "failed": "Its last analysis failed. Any context shown is from an earlier analysis and is not current; "
              "the creator can retry it in Clipcon.",
    "stale": "Its original or the analysis settings changed since it was indexed. This saved context may not "
             "describe the footage; do not rely on it until the creator re-analyses the clip.",
    "missing": "Its original file is not at the indexed location. The saved context describes it, but there is "
               "no media to use until the creator restores or locates the file.",
}


def live_status(clip) -> str:
    """The clip's stored status, except that a 'ready' clip whose original is gone or no longer matches the
    indexed size/modification time is reported as missing or stale (checked now, without hashing)."""
    if clip["status"] != "ready":
        return clip["status"]
    try:
        stat = Path(clip["source_path"]).stat()
    except OSError:
        return "missing"
    if stat.st_size != clip["size_bytes"] or abs(stat.st_mtime - clip["mtime"]) > 1e-3:
        return "stale"
    return "ready"


def status_fields(clip) -> dict:
    status = live_status(clip)
    return {"status": status, **({"status_note": STATUS_NOTES[status]} if status != "ready" else {})}


class RetrievalError(Exception):
    """A request the index cannot answer truthfully; reported to the agent as a tool error."""


def clip_text(text: str) -> str:
    return text if len(text) <= EXCERPT_CHARS else text[:EXCERPT_CHARS - 1].rstrip() + "…"


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from a JPEG's start-of-frame marker, without an imaging library."""
    i = 2
    while i + 9 < len(data) and data[i] == 0xFF:
        marker, length = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + length
    return None


SCOPES = ("project", "library")

# Why a Segment cannot be offered for reuse outside a Project's context.
NOT_REUSABLE = {
    "a-roll": "it is A-roll, which stays with its own Project's context",
    "mixed": "its role is Mixed and needs the creator's review before reuse",
    "needs_review": "its role needs the creator's review before reuse",
}

SEGMENT_ROW = (
    "SELECT s.*, COALESCE(r.role, s.role) AS effective_role, r.role AS creator_role,"
    " r.updated_at AS creator_role_at, c.original_filename, c.source_path, c.status, c.revision, c.duration,"
    " c.size_bytes, c.mtime, c.speech_language, c.reuse_allowed, c.origin_project_id, c.fingerprint"
    " FROM segments s JOIN source_clips c ON c.id = s.clip_id"
    " LEFT JOIN segment_roles r ON r.clip_id = s.clip_id AND r.start = s.start AND r.end_ = s.end_")


class Index:
    """Each call reads one consistent snapshot of the latest published index through a read-only connection,
    so a clip being re-published meanwhile is seen entirely before or entirely after.

    Every Segment lookup is scoped: to a Project (its membership's note, exclusion and relationships), to the
    library (only reusable B-roll, through memberships that allow it), or, for a reference held from before
    scopes existed, to the Project the source was first imported into."""

    def __init__(self, home: Path):
        self.path = Path(home) / "index.sqlite"

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if not self.path.exists():
            raise RetrievalError(f"no footage index at {self.path}; import footage in Clipcon first")
        db = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN")
            if "project_id" in {r["name"] for r in db.execute("PRAGMA table_info(source_clips)")}:
                raise RetrievalError("this footage index predates the Footage library; open Clipcon once so it "
                                     "can migrate the index (no footage is re-analysed)")
            yield db
        finally:
            db.close()

    @staticmethod
    def _project(db: sqlite3.Connection, project_id: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise RetrievalError(f"unknown project_id {project_id!r}; call get_project_overview without arguments")
        return row

    def projects(self) -> dict:
        with self._connect() as db:
            rows = db.execute(
                "SELECT p.id, p.name, COUNT(m.clip_id) AS clips FROM projects p"
                " LEFT JOIN memberships m ON m.project_id = p.id GROUP BY p.id ORDER BY p.created_at").fetchall()
            sources = db.execute("SELECT COUNT(*) FROM source_clips").fetchone()[0]
            standalone = db.execute("SELECT COUNT(*) FROM source_clips c WHERE NOT EXISTS"
                                    " (SELECT 1 FROM memberships m WHERE m.clip_id = c.id)").fetchone()[0]
        return {"projects": [{"project_id": r["id"], "name": r["name"], "clip_count": r["clips"]} for r in rows],
                "library": {"source_count": sources, "standalone_count": standalone,
                            "note": "Search reusable B-roll across the library with search_footage scope='library'."}}

    @staticmethod
    def _role_summaries(db: sqlite3.Connection, clip_ids: list[str]) -> dict[str, str]:
        out = {}
        for clip_id in clip_ids:
            found = [r["effective_role"] for r in db.execute(SEGMENT_ROW + " WHERE s.clip_id=? ORDER BY s.ordinal",
                                                              (clip_id,))]
            out[clip_id] = roles.summary(found)["text"]
        return out

    def overview(self, project_id: str) -> dict:
        with self._connect() as db:
            project = self._project(db, project_id)
            clips = db.execute(
                "SELECT c.*, m.excluded, (SELECT COUNT(*) FROM segments s WHERE s.clip_id = c.id) AS segment_count"
                " FROM memberships m JOIN source_clips c ON c.id = m.clip_id WHERE m.project_id=?"
                " ORDER BY m.created_at, c.created_at", (project_id,)).fetchall()
            summaries = self._role_summaries(db, [c["id"] for c in clips])
        statuses = {c["id"]: status_fields(c) for c in clips}
        return {
            "project": {"project_id": project["id"], "name": project["name"], "context": project["context"]},
            "status_counts": dict(Counter(statuses[c["id"]]["status"] for c in clips)),
            "excluded_count": sum(1 for c in clips if c["excluded"]),
            "clips": [{
                "clip_id": c["id"], "original_filename": c["original_filename"], "label": c["label"],
                "role": c["role"], "segment_roles": summaries[c["id"]],
                **statuses[c["id"]], "stage": c["stage"], "error": c["error"],
                "duration": c["duration"],
                "speech_language": c["speech_language"], "segment_count": c["segment_count"],
                "revision": c["revision"], "excluded": bool(c["excluded"]),
                "reuse_allowed": bool(c["reuse_allowed"]),
            } for c in clips],
        }

    @staticmethod
    def _segment(db: sqlite3.Connection, segment_id: str) -> sqlite3.Row:
        row = db.execute(SEGMENT_ROW + " WHERE s.id=?", (segment_id,)).fetchone()
        if row is not None:
            return row
        retired = db.execute("SELECT r.revision, c.id, c.original_filename FROM retired_segments r"
                             " JOIN source_clips c ON c.id = r.clip_id WHERE r.id=?", (segment_id,)).fetchone()
        if retired:
            raise RetrievalError(
                f"segment_id {segment_id!r} was from revision {retired[0]} of {retired[2]} (clip_id {retired[1]}),"
                " which has since been re-analysed; its context is no longer current. Search again for that"
                " clip's current Segments.")
        alias = db.execute("SELECT * FROM segment_aliases WHERE id=?", (segment_id,)).fetchone()
        if alias:
            raise RetrievalError(
                f"segment_id {segment_id!r} came from a duplicate import of {alias['original_filename']} in"
                f" project {alias['project_id']}, which now shares one library analysis as clip_id"
                f" {alias['clip_id']}. Search project {alias['project_id']} again for its current Segments.")
        raise RetrievalError(f"unknown segment_id {segment_id!r}; use a segment_id returned by search_footage")

    @staticmethod
    def _memberships(db: sqlite3.Connection, clip_id: str) -> list[sqlite3.Row]:
        return db.execute("SELECT m.*, p.name FROM memberships m JOIN projects p ON p.id = m.project_id"
                          " WHERE m.clip_id=? ORDER BY m.created_at", (clip_id,)).fetchall()

    def _reuse(self, db: sqlite3.Connection, seg, requesting: str | None) -> tuple[str | None, list]:
        """(reason it is not reusable or None, memberships a library result may draw on). Only B-roll is
        reusable; an excluded membership never contributes; reuse permission off leaves only the requesting
        Project's own allowed membership."""
        if seg["effective_role"] != "b-roll":
            return NOT_REUSABLE[seg["effective_role"]], []
        members = self._memberships(db, seg["clip_id"])
        allowed = [m for m in members if not m["excluded"]]
        if not seg["reuse_allowed"]:
            own = [m for m in allowed if m["project_id"] == requesting]
            return (None, own) if own else ("the creator has not allowed reuse of this clip across projects", [])
        if members and not allowed:
            return "the creator excluded it from agent results in every Project it belongs to", []
        return None, allowed

    def _scope(self, db: sqlite3.Connection, seg, project_id: str | None, scope: str | None) -> dict:
        if scope not in (None, *SCOPES):
            raise RetrievalError(f"unknown scope {scope!r}; use 'project' or 'library'")
        if project_id is not None:
            self._project(db, project_id)
        if scope == "library":
            reason, origins = self._reuse(db, seg, project_id)
            if reason:
                raise RetrievalError(f"segment_id {seg['id']!r} is not available for library reuse: {reason}.")
            return {"kind": "library", "project_id": None, "requesting": project_id, "membership": None,
                    "origins": origins}
        if scope == "project" and project_id is None:
            raise RetrievalError("scope 'project' needs a project_id")
        # Without a scope, a reference resolves in the Project its source was first imported into, so a held
        # reference never picks up another Project's notes because the source was shared later.
        pid = project_id if project_id is not None else seg["origin_project_id"]
        membership = db.execute("SELECT * FROM memberships WHERE project_id=? AND clip_id=?",
                                (pid, seg["clip_id"])).fetchone() if pid else None
        if project_id is not None and membership is None:
            raise RetrievalError(f"segment_id {seg['id']!r} is not in project {project_id!r}; search that "
                                 "Project, or use scope='library' for reusable B-roll")
        return {"kind": "project" if membership else "unscoped", "project_id": pid if membership else None,
                "membership": membership, "origins": []}

    @staticmethod
    def _reference(seg, scope: dict) -> dict:
        ref = {"project_id": scope["project_id"], "clip_id": seg["clip_id"], "segment_id": seg["id"],
               "original_filename": seg["original_filename"], "label": seg["label"],
               "start": seg["start"], "end": seg["end_"], "role": seg["effective_role"]}
        if scope["kind"] == "library":
            ref["origins"] = [{"project_id": m["project_id"], "name": m["name"]} for m in scope["origins"]]
        return ref

    @staticmethod
    def _notes(scope: dict, clip_id: str) -> list[dict]:
        members = [scope["membership"]] if scope["membership"] else scope["origins"]
        return [{"project_id": m["project_id"], "clip_id": clip_id, "text": m["note"],
                 "updated_at": m["note_updated_at"]} for m in members if m["note"]]

    @staticmethod
    def _excluded(scope: dict) -> bool:
        return bool(scope["membership"]["excluded"]) if scope["membership"] else False

    @staticmethod
    def _evidence(db: sqlite3.Connection, ids: list[str]) -> list[dict]:
        """Resolve cited transcript/frame IDs to their timestamped saved text."""
        out = []
        for eid in ids:
            if t := db.execute("SELECT * FROM transcript_spans WHERE id=?", (eid,)).fetchone():
                out.append({"transcript_id": eid, "segment_id": t["segment_id"], "start": t["start"],
                            "end": t["end_"], "text": t["text"]})
            elif o := db.execute("SELECT o.segment_id, o.text, f.time FROM observations o JOIN frames f"
                                 " ON f.id = o.frame_id WHERE o.frame_id=?", (eid,)).fetchone():
                out.append({"frame_id": eid, "segment_id": o["segment_id"], "time": o["time"], "text": o["text"]})
        return out

    def _relationships(self, db: sqlite3.Connection, segment_id: str, project_id: str | None, limit: int,
                       full: bool, include_excluded: bool = False) -> list[dict]:
        """A Project's suggested relationships touching a Segment, each naming the other Segment and what it is.
        Segments the creator excluded from that Project are left out unless include_excluded. Relationships are
        Project context, so there are none outside a Project's scope."""
        if project_id is None:
            return []
        rows = db.execute("SELECT * FROM relationships WHERE project_id=? AND (a_segment=? OR b_segment=?)"
                          " ORDER BY rowid", (project_id, segment_id, segment_id)).fetchall()
        rows.sort(key=lambda r: list(RELATED_AS).index(r["kind"]))  # corrections, then takes, then B-roll
        out = []
        for r in rows:
            if r["a_segment"] == r["b_segment"]:  # both statements or takes fall within this Segment
                other, related_as, cited = "a", "within_segment", json.loads(r["a_evidence"]) + json.loads(r["b_evidence"])
            elif r["a_segment"] == segment_id:
                other, related_as, cited = "b", RELATED_AS[r["kind"]][0], json.loads(r["b_evidence"])
            else:
                other, related_as, cited = "a", RELATED_AS[r["kind"]][1], json.loads(r["a_evidence"])
            seg = self._segment(db, r[f"{other}_segment"])
            membership = db.execute("SELECT excluded FROM memberships WHERE project_id=? AND clip_id=?",
                                    (project_id, seg["clip_id"])).fetchone()
            excluded = bool(membership["excluded"]) if membership else True
            if excluded and not include_excluded:
                continue
            excerpt = " ".join(dict.fromkeys(e["text"] for e in self._evidence(db, cited)))
            scope = {"kind": "project", "project_id": project_id}
            item = {"relationship_id": r["id"], "kind": r["kind"], "related_as": related_as,
                    **{k: v for k, v in self._reference(seg, scope).items() if k != "project_id"},
                    "excerpt": clip_text(excerpt), "basis": r["basis"], "suggested": True, "excluded": excluded}
            if full:
                item["evidence"] = self._evidence(db, json.loads(r["a_evidence"]) + json.loads(r["b_evidence"]))
            out.append(item)
        return out[:limit]

    def review_relationships(self, project_id: str, segment_ids: list[str]) -> dict[str, list[dict]]:
        """Every suggested relationship of these Segments in a Project, including ones to excluded clips, for
        the creator."""
        with self._connect() as db:
            return {sid: self._relationships(db, sid, project_id, RELATIONSHIPS_PER_CONTEXT, full=False,
                                             include_excluded=True)
                    for sid in segment_ids}

    def segment_context(self, segment_id: str, window_seconds: float = 15.0, project_id: str | None = None,
                        scope: str | None = None) -> dict:
        """One Segment's evidence plus transcript up to window_seconds either side, kept distinct by kind."""
        window = max(0.0, min(window_seconds, CONTEXT_WINDOW_MAX))
        with self._connect() as db:
            seg = self._segment(db, segment_id)
            scoped = self._scope(db, seg, project_id, scope)
            spans = db.execute(
                "SELECT t.*, t.segment_id = ? AS in_segment FROM transcript_spans t"
                " JOIN segments s ON s.id = t.segment_id WHERE s.clip_id=? AND t.end_ > ? AND t.start < ?"
                " ORDER BY t.start", (seg["id"], seg["clip_id"], seg["start"] - window, seg["end_"] + window)
            ).fetchall()
            observations = db.execute(
                "SELECT o.frame_id, f.time, o.text FROM observations o JOIN frames f ON f.id = o.frame_id"
                " WHERE o.segment_id=? ORDER BY f.time", (seg["id"],)).fetchall()
            analysis = db.execute("SELECT * FROM analyses WHERE clip_id=? AND revision=?",
                                  (seg["clip_id"], seg["revision"])).fetchone()
            relationships = self._relationships(db, seg["id"], scoped["project_id"], RELATIONSHIPS_PER_CONTEXT,
                                                full=True)
        speech = json.loads(analysis["speech_identity"]) if analysis else {}
        vision = json.loads(analysis["vision_identity"]) if analysis else {}
        omitted = max(0, len(spans) - CONTEXT_LINES_MAX)
        if omitted:  # keep the Segment's own lines; trim the surrounding ones farthest from it
            centre = (seg["start"] + seg["end_"]) / 2
            keep = sorted(spans, key=lambda t: (not t["in_segment"], abs(t["start"] - centre)))[:CONTEXT_LINES_MAX]
            spans = sorted(keep, key=lambda t: t["start"])
        excluded = self._excluded(scoped)
        return {
            "segment": self._reference(seg, scoped), "scope": scoped["kind"],
            **status_fields(seg), "revision": seg["revision"],
            "transcript": [{"transcript_id": t["id"], "start": t["start"], "end": t["end_"], "text": t["text"],
                            "in_segment": bool(t["in_segment"])} for t in spans],
            "transcript_window_seconds": window, "transcript_lines_omitted": omitted,
            "observations": [{"frame_id": o["frame_id"], "time": o["time"], "text": o["text"]}
                             for o in observations],
            "interpretation": {"text": seg["interpretation"],
                               "evidence_ids": json.loads(seg["interpretation_evidence"]),
                               "model": vision.get("model")},
            "segment_role": {"role": seg["effective_role"], "suggested": seg["role"], "basis": seg["role_basis"],
                             "creator": seg["creator_role"]},
            "provenance": {
                "transcript": "local speech recognition (timestamps from alignment)",
                "observations": "local vision model describing sampled frames only",
                "interpretation": "local model inference citing the evidence_ids above",
                "creator_notes": "written by the creator in Clipcon about the whole Source clip for the named "
                                 "Project; not model output",
                "segment_role": "suggested in code from this Segment's speech coverage and sampled frames; "
                                "`creator` is the creator's correction, which takes precedence",
                "speech": speech, "vision": vision, "speech_language": seg["speech_language"],
                "recipe_version": json.loads(analysis["recipe"]).get("version") if analysis else None,
                "analyzed_at": analysis["finished_at"] if analysis else None,
            },
            "excluded": excluded,
            "exclusion_note": ("The creator excluded this clip from new default search results. Context already "
                               "retrieved is not revoked, but do not choose this footage without asking."
                               if excluded else None),
            "relationships": relationships,
            "relationships_note": "Suggestions derived from saved evidence. Both sides stay in the index; "
                                  "none is marked preferred. The creator decides which statement or take to use.",
            "creator_notes": self._notes(scoped, seg["clip_id"]),
        }

    def preview(self, segment_id: str, frame_id: str | None = None, project_id: str | None = None,
                scope: str | None = None) -> tuple[dict, bytes]:
        """A sampled frame Clipcon saved for this Segment (not a new decode of the source)."""
        with self._connect() as db:
            seg = self._segment(db, segment_id)
            scoped = self._scope(db, seg, project_id, scope)
            frames = db.execute("SELECT * FROM frames WHERE segment_id=? ORDER BY time", (seg["id"],)).fetchall()
        if frame_id is None and frames:
            frame = frames[len(frames) // 2]
        else:
            frame = next((f for f in frames if f["id"] == frame_id), None)
        if frame is None:
            sampled = ", ".join(f["id"] for f in frames) or "none"
            raise RetrievalError(f"frame {frame_id!r} was not sampled for segment {segment_id}; sampled: {sampled}")
        path = Path(frame["path"])
        if not path.is_file():
            raise RetrievalError(f"sampled frame {frame['id']} is no longer in Clipcon's cache; re-analyse the clip")
        data = path.read_bytes()
        if len(data) > PREVIEW_BYTES_MAX:
            raise RetrievalError(f"sampled frame {frame['id']} exceeds the {PREVIEW_BYTES_MAX}-byte preview limit")
        width, height = jpeg_size(data) or (None, None)
        if width is None or width > PREVIEW_WIDTH_MAX:
            raise RetrievalError(f"sampled frame {frame['id']} is not a JPEG at most {PREVIEW_WIDTH_MAX} px wide")
        return {
            "segment": self._reference(seg, scoped), **status_fields(seg), "revision": seg["revision"],
            "frame": {"frame_id": frame["id"], "time": frame["time"], "width": width, "height": height,
                      "bytes": len(data), "mime_type": "image/jpeg"},
            "sampled_frame_ids": [f["id"] for f in frames],
            "note": "One frame sampled at `time` seconds into the Source clip; it does not show the whole Segment.",
        }, data

    def resolve_media(self, segment_id: str, start: float | None = None, end: float | None = None,
                      project_id: str | None = None, scope: str | None = None) -> dict:
        """Locate the original Source clip and validate a source-relative range (default: the Segment's).

        Availability is checked now: a missing file, or one whose size/modification time differs from the
        indexed source, gets no locator, because the saved context may no longer describe it.
        """
        with self._connect() as db:
            seg = self._segment(db, segment_id)
            scoped = self._scope(db, seg, project_id, scope)
        start = seg["start"] if start is None else start
        end = seg["end_"] if end is None else end
        duration = seg["duration"]
        if not (0 <= start < end <= duration + 1e-6):
            raise RetrievalError(f"range {start}–{end}s is invalid for {seg['original_filename']}; "
                                 f"need 0 <= start < end <= duration ({duration}s)")
        status = live_status(seg)  # the same answer overview and search give for this clip
        out = {**self._reference(seg, scoped), "start": start, "end": min(end, duration), "duration": duration,
               "index_status": status, "revision": seg["revision"]}
        if status != "ready":
            return {**out, "available": False, "state": status,
                    "detail": f"Clipcon marks this clip {status}. {STATUS_NOTES[status]} "
                              "Ask the creator to resolve it in Clipcon."}
        path = Path(seg["source_path"])
        return {**out, "available": True, "state": "available", "path": str(path), "file_url": path.as_uri(),
                "note": "A locator only: it grants no new filesystem permission. Read the file with your own "
                        "tools under their normal access to this Mac."}

    def search(self, project_id: str | None, query: str, limit: int = SEARCH_PAGE, offset: int = 0,
               include_excluded: bool = False, scope: str | None = None) -> dict:
        """Rank Segments by query terms found in their saved evidence; return one bounded page.

        Project scope (the default) searches a Project's memberships, skipping clips the creator excluded unless
        include_excluded. Library scope searches reusable B-roll across the whole library; project_id is then
        the requesting Project, if any, and excluded memberships never contribute."""
        scope = scope or "project"
        if scope not in SCOPES:
            raise RetrievalError(f"unknown scope {scope!r}; use 'project' or 'library'")
        if scope == "project" and project_id is None:
            raise RetrievalError("search_footage needs a project_id, or scope='library' for reusable B-roll")
        limit = max(1, min(limit, SEARCH_PAGE_MAX))
        offset = max(0, offset)
        with self._connect() as db:
            if project_id is not None:
                self._project(db, project_id)
            if scope == "project":
                segments = db.execute(
                    SEGMENT_ROW.replace(" FROM segments s", ", m.excluded, m.note FROM segments s") +
                    " JOIN memberships m ON m.clip_id = c.id AND m.project_id=?"
                    " WHERE ? OR NOT m.excluded ORDER BY m.created_at, c.created_at, s.ordinal",
                    (project_id, include_excluded)).fetchall()
                scopes = {seg["id"]: {"kind": "project", "project_id": project_id, "membership": seg,
                                      "origins": []} for seg in segments}
                notes = {seg["id"]: [seg["note"]] if seg["note"] else [] for seg in segments}
            else:
                segments, scopes = [], {}
                for seg in db.execute(SEGMENT_ROW + " ORDER BY c.created_at, s.ordinal").fetchall():
                    reason, origins = self._reuse(db, seg, project_id)
                    if reason is None:
                        segments.append(seg)
                        scopes[seg["id"]] = {"kind": "library", "project_id": None, "membership": None,
                                             "origins": origins}
                notes = {seg["id"]: [n["text"] for n in self._notes(scopes[seg["id"]], seg["clip_id"])]
                         for seg in segments}
            evidence = {}
            for seg in segments:
                items = [("transcript", t["text"]) for t in db.execute(
                    "SELECT text FROM transcript_spans WHERE segment_id=? ORDER BY ordinal", (seg["id"],))]
                items += [("observation", o["text"]) for o in db.execute(
                    "SELECT text FROM observations WHERE segment_id=? ORDER BY rowid", (seg["id"],))]
                items += [("interpretation", seg["interpretation"]), ("label", seg["label"])]
                # A clip-wide note, so it can match each of the clip's Segments.
                items += [("creator_note", text) for text in notes[seg["id"]]]
                evidence[seg["id"]] = items
            ranked = rank(query, segments, evidence)
            duplicates: dict[str, list[str]] = {}
            if scope == "library":  # the same footage imported from several places is one candidate
                kept, best = [], {}
                for r in ranked:
                    key = r[1]["fingerprint"] or r[1]["clip_id"]
                    best.setdefault(key, r[1]["clip_id"])
                    if best[key] == r[1]["clip_id"]:
                        kept.append(r)
                    elif r[1]["clip_id"] not in duplicates.setdefault(best[key], []):
                        duplicates[best[key]].append(r[1]["clip_id"])
                ranked = kept
            page = ranked[offset:offset + limit]
            statuses = {seg["clip_id"]: status_fields(seg) for _, seg, _ in page}
            related = {seg["id"]: self._relationships(db, seg["id"], scopes[seg["id"]]["project_id"],
                                                      RELATIONSHIPS_PER_RESULT, full=False,
                                                      include_excluded=include_excluded)
                       for _, seg, _ in page}
        more = offset + limit < len(ranked)
        out = {
            "query": query, "scope": scope, "project_id": project_id, "total_matches": len(ranked),
            "offset": offset, "truncated": more, "next_offset": offset + limit if more else None,
            "results": [{
                **self._reference(seg, scopes[seg["id"]]), "excerpt": clip_text(text), "evidence_basis": kind,
                **statuses[seg["clip_id"]], "revision": seg["revision"], "score": round(score, 2),
                "excluded": self._excluded(scopes[seg["id"]]), "has_creator_note": bool(notes[seg["id"]]),
                "relationships": related[seg["id"]],
                **({"duplicate_clip_ids": duplicates[seg["clip_id"]]} if seg["clip_id"] in duplicates else {}),
            } for score, seg, (_, kind, text) in page],
        }
        if scope == "library":
            out["scope_note"] = ("Reusable B-roll from the whole library. Origins name the Projects it came from; "
                                 "it does not document events in your Project. Pass scope='library' when expanding "
                                 "these Segments.")
        return out


def rank(query: str, segments: list, evidence: dict[str, list[tuple[str, str]]]) -> list[tuple]:
    """(score, segment, best matching (score, kind, text)) for every Segment with evidence matching the query."""
    wanted = terms(query)
    phrase = f" {' '.join(words(query))} "
    ranked = []
    for seg in segments if wanted else []:
        scored = []
        for kind, text in evidence[seg["id"]]:
            found = words(text)
            hits = sum(1 for t in wanted if matches(t, set(found)))
            if hits:
                exact = phrase.strip() and phrase in f" {' '.join(found)} "
                scored.append((WEIGHTS[kind] * hits + (2.0 * len(wanted) if exact else 0), kind, text))
        if scored:
            scored.sort(key=lambda s: -s[0])
            score = scored[0][0] + SUPPORTING_WEIGHT * sum(s[0] for s in scored[1:])
            ranked.append((score, seg, scored[0]))
    ranked.sort(key=lambda r: -r[0])  # stable: equal scores keep source order
    return ranked
