"""Read-only retrieval over the saved footage index. Never loads inference models or writes the index."""

import json
import os
from collections import Counter
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

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
WEIGHTS = {"transcript": 3.0, "label": 2.0, "interpretation": 2.0, "observation": 1.5}
# Further matching lines add less than the best one, so long Segments do not win on length alone.
SUPPORTING_WEIGHT = 0.25


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


class Index:
    """Each call reads one consistent snapshot of the latest published index through a read-only connection,
    so a clip being re-published meanwhile is seen entirely before or entirely after."""

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
                "SELECT p.id, p.name, COUNT(c.id) AS clips FROM projects p"
                " LEFT JOIN source_clips c ON c.project_id = p.id GROUP BY p.id ORDER BY p.created_at").fetchall()
        return {"projects": [{"project_id": r["id"], "name": r["name"], "clip_count": r["clips"]} for r in rows]}

    def overview(self, project_id: str) -> dict:
        with self._connect() as db:
            project = self._project(db, project_id)
            clips = db.execute(
                "SELECT c.*, (SELECT COUNT(*) FROM segments s WHERE s.clip_id = c.id) AS segment_count"
                " FROM source_clips c WHERE c.project_id=? ORDER BY c.created_at", (project_id,)).fetchall()
        return {
            "project": {"project_id": project["id"], "name": project["name"], "context": project["context"]},
            "status_counts": dict(Counter(c["status"] for c in clips)),
            "clips": [{
                "clip_id": c["id"], "original_filename": c["original_filename"], "label": c["label"],
                "role": c["role"], "status": c["status"], "stage": c["stage"], "error": c["error"],
                "duration": c["duration"],
                "speech_language": c["speech_language"], "segment_count": c["segment_count"],
                "revision": c["revision"],
            } for c in clips],
        }

    @staticmethod
    def _segment(db: sqlite3.Connection, segment_id: str) -> sqlite3.Row:
        row = db.execute(
            "SELECT s.*, c.project_id, c.original_filename, c.source_path, c.status, c.revision, c.duration,"
            " c.size_bytes, c.mtime, c.speech_language FROM segments s JOIN source_clips c ON c.id = s.clip_id"
            " WHERE s.id=?", (segment_id,)).fetchone()
        if row is None:
            raise RetrievalError(f"unknown segment_id {segment_id!r}; use a segment_id returned by search_footage")
        return row

    @staticmethod
    def _reference(seg: sqlite3.Row) -> dict:
        return {"project_id": seg["project_id"], "clip_id": seg["clip_id"], "segment_id": seg["id"],
                "original_filename": seg["original_filename"], "label": seg["label"],
                "start": seg["start"], "end": seg["end_"]}

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

    def _relationships(self, db: sqlite3.Connection, segment_id: str, limit: int, full: bool) -> list[dict]:
        """Suggested relationships touching a Segment, each naming the other Segment and what it is."""
        rows = db.execute("SELECT * FROM relationships WHERE a_segment=? OR b_segment=? ORDER BY rowid",
                          (segment_id, segment_id)).fetchall()
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
            excerpt = " ".join(dict.fromkeys(e["text"] for e in self._evidence(db, cited)))
            item = {"relationship_id": r["id"], "kind": r["kind"], "related_as": related_as,
                    **{k: v for k, v in self._reference(seg).items() if k != "project_id"},
                    "excerpt": clip_text(excerpt), "basis": r["basis"], "suggested": True}
            if full:
                item["evidence"] = self._evidence(db, json.loads(r["a_evidence"]) + json.loads(r["b_evidence"]))
            out.append(item)
        return out[:limit]

    def segment_context(self, segment_id: str, window_seconds: float = 15.0) -> dict:
        """One Segment's evidence plus transcript up to window_seconds either side, kept distinct by kind."""
        window = max(0.0, min(window_seconds, CONTEXT_WINDOW_MAX))
        with self._connect() as db:
            seg = self._segment(db, segment_id)
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
            relationships = self._relationships(db, seg["id"], RELATIONSHIPS_PER_CONTEXT, full=True)
        speech = json.loads(analysis["speech_identity"]) if analysis else {}
        vision = json.loads(analysis["vision_identity"]) if analysis else {}
        omitted = max(0, len(spans) - CONTEXT_LINES_MAX)
        if omitted:  # keep the Segment's own lines; trim the surrounding ones farthest from it
            centre = (seg["start"] + seg["end_"]) / 2
            keep = sorted(spans, key=lambda t: (not t["in_segment"], abs(t["start"] - centre)))[:CONTEXT_LINES_MAX]
            spans = sorted(keep, key=lambda t: t["start"])
        return {
            "segment": self._reference(seg),
            "status": seg["status"], "revision": seg["revision"],
            "transcript": [{"transcript_id": t["id"], "start": t["start"], "end": t["end_"], "text": t["text"],
                            "in_segment": bool(t["in_segment"])} for t in spans],
            "transcript_window_seconds": window, "transcript_lines_omitted": omitted,
            "observations": [{"frame_id": o["frame_id"], "time": o["time"], "text": o["text"]}
                             for o in observations],
            "interpretation": {"text": seg["interpretation"],
                               "evidence_ids": json.loads(seg["interpretation_evidence"]),
                               "model": vision.get("model")},
            "provenance": {
                "transcript": "local speech recognition (timestamps from alignment)",
                "observations": "local vision model describing sampled frames only",
                "interpretation": "local model inference citing the evidence_ids above",
                "speech": speech, "vision": vision, "speech_language": seg["speech_language"],
                "recipe_version": json.loads(analysis["recipe"]).get("version") if analysis else None,
                "analyzed_at": analysis["finished_at"] if analysis else None,
            },
            "relationships": relationships,
            "relationships_note": "Suggestions derived from saved evidence. Both sides stay in the index; "
                                  "none is marked preferred. The creator decides which statement or take to use.",
            # Creator notes are not indexed yet.
            "not_yet_available": ["creator_notes"],
        }

    def preview(self, segment_id: str, frame_id: str | None = None) -> tuple[dict, bytes]:
        """A sampled frame Clipcon saved for this Segment (not a new decode of the source)."""
        with self._connect() as db:
            seg = self._segment(db, segment_id)
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
            "segment": self._reference(seg), "status": seg["status"], "revision": seg["revision"],
            "frame": {"frame_id": frame["id"], "time": frame["time"], "width": width, "height": height,
                      "bytes": len(data), "mime_type": "image/jpeg"},
            "sampled_frame_ids": [f["id"] for f in frames],
            "note": "One frame sampled at `time` seconds into the Source clip; it does not show the whole Segment.",
        }, data

    def resolve_media(self, segment_id: str, start: float | None = None, end: float | None = None) -> dict:
        """Locate the original Source clip and validate a source-relative range (default: the Segment's).

        Availability is checked now: a missing file, or one whose size/modification time differs from the
        indexed source, gets no locator, because the saved context may no longer describe it.
        """
        with self._connect() as db:
            seg = self._segment(db, segment_id)
        start = seg["start"] if start is None else start
        end = seg["end_"] if end is None else end
        duration = seg["duration"]
        if not (0 <= start < end <= duration + 1e-6):
            raise RetrievalError(f"range {start}–{end}s is invalid for {seg['original_filename']}; "
                                 f"need 0 <= start < end <= duration ({duration}s)")
        out = {**self._reference(seg), "start": start, "end": min(end, duration), "duration": duration,
               "index_status": seg["status"], "revision": seg["revision"]}
        if seg["status"] != "ready":
            return {**out, "available": False, "state": seg["status"],
                    "detail": f"Clipcon marks this clip {seg['status']}; its saved context is not current. "
                              "Ask the creator to resolve it in Clipcon."}
        path = Path(seg["source_path"])
        try:
            stat = path.stat()
        except OSError:
            return {**out, "available": False, "state": "missing",
                    "detail": "The original file is not at its indexed location. Ask the creator to restore it."}
        if stat.st_size != seg["size_bytes"] or abs(stat.st_mtime - seg["mtime"]) > 1e-3:
            return {**out, "available": False, "state": "changed",
                    "detail": "The file changed since it was indexed; its saved context may be stale. "
                              "Ask the creator to re-analyse it in Clipcon."}
        return {**out, "available": True, "state": "available", "path": str(path), "file_url": path.as_uri(),
                "note": "A locator only: it grants no new filesystem permission. Read the file with your own "
                        "tools under their normal access to this Mac."}

    def search(self, project_id: str, query: str, limit: int = SEARCH_PAGE, offset: int = 0) -> dict:
        """Rank Segments by query terms found in their saved evidence; return one bounded page."""
        limit = max(1, min(limit, SEARCH_PAGE_MAX))
        offset = max(0, offset)
        with self._connect() as db:
            self._project(db, project_id)
            segments = db.execute(
                "SELECT s.*, c.original_filename, c.status, c.revision, c.project_id FROM segments s"
                " JOIN source_clips c ON c.id = s.clip_id WHERE c.project_id=?"
                " ORDER BY c.created_at, s.ordinal", (project_id,)).fetchall()
            evidence = {}
            for seg in segments:
                items = [("transcript", t["text"]) for t in db.execute(
                    "SELECT text FROM transcript_spans WHERE segment_id=? ORDER BY ordinal", (seg["id"],))]
                items += [("observation", o["text"]) for o in db.execute(
                    "SELECT text FROM observations WHERE segment_id=? ORDER BY rowid", (seg["id"],))]
                items += [("interpretation", seg["interpretation"]), ("label", seg["label"])]
                evidence[seg["id"]] = items
            ranked = rank(query, segments, evidence)
            page = ranked[offset:offset + limit]
            related = {seg["id"]: self._relationships(db, seg["id"], RELATIONSHIPS_PER_RESULT, full=False)
                       for _, seg, _ in page}
        more = offset + limit < len(ranked)
        return {
            "query": query, "project_id": project_id, "total_matches": len(ranked),
            "offset": offset, "truncated": more, "next_offset": offset + limit if more else None,
            "results": [{
                **self._reference(seg), "excerpt": clip_text(text), "evidence_basis": kind,
                "status": seg["status"], "revision": seg["revision"], "score": round(score, 2),
                "relationships": related[seg["id"]],
            } for score, seg, (_, kind, text) in page],
        }


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
