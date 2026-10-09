"""Import orchestration: measure, transcribe, sample, describe, validate, publish."""

import hashlib
import json
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from . import media, roles, tone
from .retrieval import Index, live_status
from .speech import TranscriptSpan
from .store import SourceRemoved, Store
from .vision import FrameItem, InferenceError, SegmentRequest, ServiceUnavailable, TranscriptItem, validate

# Bump when segmentation/sampling/prompting changes so cached analyses are invalidated.
RECIPE = {
    "version": 7,  # 2: multilingual speech; 3: drop non-speech annotations; 4: loop guard; 5: VAD + on-camera role;
    #                6: describe what is shown/said only (no Project description; no "speaking" without speech);
    #                7: long silences become their own Segments, so cutaways get their own role; transcript lines
    #                   are bounded by measured silences (whisper.cpp with VAD can stretch a line across one)
    "segment_target_seconds": 30.0,
    "silent_segment_seconds": 10.0,
    "silent_gap_seconds": 10.0,
    "silence_noise_db": -45.0,
    "frames_per_segment": 2,
    "max_frames": 24,
    "frame_width": 512,
}

# Earlier recipes whose saved context stays valid under the current one: they differ only in finding Segment
# boundaries for roles, so their clips are not stale; re-analysing them (explicitly) adds per-Segment roles.
COMPATIBLE_RECIPE_VERSIONS = {6}
ROLE_ONLY_KEYS = ("version", "silent_gap_seconds", "silence_noise_db")

Progress = Callable[[str, dict], None]

# Share of a clip's duration that must be speech before it can count as A-roll ("talking most of the time").
A_ROLL_SPEECH_SHARE = 0.5

VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts"})


def missing_guidance(path: str) -> str:
    return (f"The original is not at {path}. Move it back there, or locate the same file where it is now. "
            "Its saved context is kept meanwhile; agents get no file location for it.")


CHANGED_CONTENT = ("The original's content changed since it was indexed, so its saved context may not describe it. "
                   "Re-analyse to refresh it, or restore the original file.")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def is_annotation(text: str) -> bool:
    """Whisper's non-speech markers, e.g. [BLANK_AUDIO], [Music], (speaking in foreign language)."""
    text = text.strip()
    return (text.startswith("[") and text.endswith("]")) or (text.startswith("(") and text.endswith(")"))


# Whisper can fall into a decoding loop that repeats one line until the audio ends. A run this long of
# identical consecutive lines is treated as that failure: the first line is kept, the rest dropped.
REPETITION_LOOP_RUN = 4


def collapse_repetition_loops(spans: list[TranscriptSpan]) -> list[TranscriptSpan]:
    kept: list[TranscriptSpan] = []
    i = 0
    while i < len(spans):
        j = i
        while j + 1 < len(spans) and spans[j + 1].text.casefold() == spans[i].text.casefold():
            j += 1
        run = spans[i:j + 1]
        kept.extend(run[:1] if len(run) >= REPETITION_LOOP_RUN else run)
        i = j + 1
    return kept


def clean_spans(spans: list[TranscriptSpan], duration: float,
                silences: list[tuple[float, float]] = ()) -> list[TranscriptSpan]:
    """Keep only actual speech with valid source-relative bounds; clamp alignment overrun at the end, and a line
    that claims to run through a measured long silence to its side of that silence."""
    kept = []
    for s in sorted(spans, key=lambda s: s.start):
        start, end = max(0.0, s.start), min(s.end, duration)
        for quiet_start, quiet_end in silences:
            if start < quiet_start < end:
                end = quiet_start  # it was spoken before the silence
            elif quiet_start <= start < quiet_end < end:
                start = quiet_end  # it was spoken after it
        if start < end and s.text.strip() and not is_annotation(s.text):
            kept.append(TranscriptSpan(start, end, s.text.strip()))
    return collapse_repetition_loops(kept)


def plan_segments(duration: float, spans: list[TranscriptSpan], recipe: dict) -> list[tuple[float, float, list]]:
    """Contiguous segments covering the clip. Boundaries fall between transcript spans."""
    if not spans:
        step = recipe["silent_segment_seconds"]
        count = max(1, round(duration / step))
        edges = [duration * i / count for i in range(count + 1)]
        return [(edges[i], edges[i + 1], []) for i in range(count)]
    gap = recipe.get("silent_gap_seconds", float("inf"))  # a silence this long is a Segment of its own
    groups: list[list[TranscriptSpan]] = [[]]
    for s in spans:
        if groups[-1] and (s.end - groups[-1][0].start > recipe["segment_target_seconds"]
                           or s.start - groups[-1][-1].end >= gap):
            groups.append([])
        groups[-1].append(s)
    segments = []
    if spans[0].start >= gap:
        segments.append((0.0, spans[0].start, []))
    for i, group in enumerate(groups):
        start = 0.0 if i == 0 and not segments else group[0].start
        end = duration if i == len(groups) - 1 else groups[i + 1][0].start
        if end - group[-1].end >= gap:
            segments += [(start, group[-1].end, group), (group[-1].end, end, [])]
        else:
            segments.append((start, end, group))
    return segments


def frame_times(start: float, end: float, per_segment: int) -> list[float]:
    span = end - start
    n = 1 if span < 4 else per_segment
    return [round(start + span * (i + 1) / (n + 1), 3) for i in range(n)]


class Worker:
    def __init__(self, home: Path, speech, vision, recipe: dict | None = None, tone_on_import: bool = False):
        self.home = Path(home)
        self.store = Store(self.home / "index.sqlite")
        self.speech = speech
        self.vision = vision
        self.recipe = recipe or RECIPE
        # Tone is read only when the creator asks (enrich_tone); tests may also read it as part of a new analysis.
        self.tone_on_import = tone_on_import

    def create_project(self, name: str, context: str = "") -> dict:
        return self.store.create_project(new_id("prj"), name.strip(), context.strip())

    def snapshot(self, project_id: str) -> dict:
        """The Project as the app reviews it: saved context, notes, exclusions, and suggested relationships."""
        snapshot = self.store.snapshot(project_id)
        segments = [s for c in snapshot["clips"] for s in c["segments"]]
        related = Index(self.home).review_relationships(project_id, [s["id"] for s in segments])
        for s in segments:
            s["relationships"] = related[s["id"]]
        return self._live(snapshot)

    def library_snapshot(self) -> dict:
        """Every library source as the app reviews it, with its Projects but no Project notes."""
        snapshot = self.store.library_snapshot()
        for s in (s for c in snapshot["clips"] for s in c["segments"]):
            s["relationships"] = []
        return self._live(snapshot)

    def _live(self, snapshot: dict) -> dict:
        for clip in snapshot["clips"]:  # report what MCP reports, even before the next check_sources
            if (status := live_status(clip)) != clip["status"]:
                clip["status"], clip["error"] = status, (
                    missing_guidance(clip["source_path"]) if status == "missing" else
                    "The original changed on disk since it was indexed. Check sources to verify it, or re-analyse.")
        return snapshot

    def remove_clips(self, project_id: str, clip_ids: list[str]) -> None:
        """Remove clips from a Project (its notes and exclusions for them). Their library context stays."""
        self.store.remove_memberships(project_id, clip_ids)

    def remove_from_library(self, clip_ids: list[str]) -> list[str]:
        """Forget sources everywhere: their saved context, Project memberships and Clipco's frame cache.
        The original video files stay untouched. Returns the Projects they were removed from."""
        projects = self.store.remove_from_library(clip_ids)
        for clip_id in clip_ids:
            shutil.rmtree(self.home / "frames" / clip_id, ignore_errors=True)
        return projects

    def delete_project(self, project_id: str) -> None:
        """Forget a Project and its notes and exclusions. Its footage stays in the library, originals untouched."""
        self.store.delete_project(project_id)

    def add_to_project(self, project_id: str, clip_ids: list[str]) -> dict:
        """Associate library sources with a Project, reusing their analysis (no inference)."""
        for clip_id in clip_ids:
            self.store.add_membership(project_id, clip_id)
        return self._outcome(clip_ids)

    def analysis_key(self, content_fingerprint: str) -> str:
        material = json.dumps({"source": content_fingerprint, "recipe": self.recipe,
                               "speech": self.speech.identity, "vision": self.vision.identity}, sort_keys=True)
        return hashlib.sha256(material.encode()).hexdigest()

    def _register(self, project_id: str | None, source: Path) -> tuple[str, bool]:
        """The library source for this original, added to the Project when one is given: an existing source at
        the same path is reused (its content is verified before its analysis is), otherwise a new one is
        registered. Returns (clip_id, newly registered)."""
        if project_id is not None and self.store.project(project_id) is None:
            raise ValueError(f"unknown project {project_id}")
        existing = self.store.source_by_path(str(source), project_id)
        if existing:
            if project_id is not None:
                self.store.add_membership(project_id, existing["id"])
            return existing["id"], False
        clip_id = new_id("clp")
        self.store.add_clip(clip_id, str(source), source.name, project_id)
        return clip_id, True

    def import_clip(self, project_id: str | None, source: Path, progress: Progress | None = None) -> dict:
        """Index one original into a Project, or into the library alone when project_id is None. Footage the
        library already analysed unchanged gains a membership and reuses that analysis."""
        source = Path(source).expanduser().resolve()
        clip_id, _ = self._register(project_id, source)
        return self._index(clip_id, source, progress)

    def _index(self, clip_id: str, source: Path, progress: Progress | None = None, refresh: bool = False) -> dict:
        """Analyse a source unless its saved analysis already describes this content. Importing reuses an
        analysis made under compatible settings; refresh (an explicit re-analysis) requires current ones."""
        report = progress or (lambda stage, detail: None)
        existing = self.store.clip(clip_id)

        def stage(name: str, **detail) -> None:
            self.store.set_status(clip_id, "indexing", stage=name)
            report(name, {"clip_id": clip_id, **detail})

        try:
            stat = source.stat()
            analysed = existing is not None and existing["revision"] > 0
            unchanged = analysed and existing["size_bytes"] == stat.st_size and abs(existing["mtime"] - stat.st_mtime) <= 1e-3
            if unchanged and existing["status"] == "ready":
                # Same size and modification time as when indexed (the check resolve_media applies): trust the
                # saved content fingerprint instead of rehashing gigabytes, and keep the clip ready meanwhile.
                report("fingerprinting", {"clip_id": clip_id, "cached": True})
                content = existing["fingerprint"]
            else:
                stage("fingerprinting")
                content = fingerprint(source)
            key = self.analysis_key(content)
            if analysed and existing["fingerprint"] == content and (
                    existing["analysis_key"] == key or not refresh and not self._settings_changed(existing)):
                # The saved context describes exactly this content under these settings (e.g. a restored
                # original, or a retry after a failed re-analysis): publish it as current again, without inference.
                self.store.set_source(clip_id, str(source), source.name, stat.st_size, stat.st_mtime)
                self.store.set_status(clip_id, "ready")
                report("ready", {"clip_id": clip_id, "reused": True})
                return {"clip_id": clip_id, "reused": True, "revision": existing["revision"]}
            started = time.time()
            result = self._analyse(clip_id, source, stage)
            stage("saving")
            revision = self.store.publish(
                clip_id,
                {**result["clip"], "fingerprint": content, "size_bytes": stat.st_size, "mtime": stat.st_mtime},
                {"key": key, "recipe": self.recipe, "speech": self.speech.identity,
                 "vision": self.vision.identity, "started_at": started, "finished_at": time.time()},
                result["segments"],
            )
            if self.tone_on_import:
                try:
                    self._read_tones(clip_id, report)
                except InferenceError as e:  # the analysis is published; its tone stays Not analyzed
                    report("tone_failed", {"clip_id": clip_id, "error": str(e)})
            report("ready", {"clip_id": clip_id, "reused": False, "revision": revision})
            return {"clip_id": clip_id, "reused": False, "revision": revision}
        except SourceRemoved:
            shutil.rmtree(self.home / "frames" / clip_id, ignore_errors=True)  # nothing of it is published
            report("removed", {"clip_id": clip_id})
            return {"clip_id": clip_id, "removed": True}
        except ServiceUnavailable as e:
            # An outage says nothing about saved context that was usable before: a refresh of a ready, stale or
            # missing clip leaves it as it was. Anything else records the failure, for a retry once it is back.
            if existing and existing["status"] in ("ready", "stale", "missing"):
                self.store.set_status(clip_id, existing["status"], error=existing["error"])
            else:
                self.store.set_status(clip_id, "failed", error=f"{type(e).__name__}: {e}")
            report("failed", {"clip_id": clip_id, "error": str(e)})
            raise
        except Exception as e:
            if isinstance(e, FileNotFoundError) and not source.exists():
                self.store.set_status(clip_id, "missing", error=missing_guidance(str(source)))
                report("missing", {"clip_id": clip_id, "error": missing_guidance(str(source))})
            else:
                self.store.set_status(clip_id, "failed", error=f"{type(e).__name__}: {e}")
                report("failed", {"clip_id": clip_id, "error": str(e)})
            raise

    def _require(self, project_id: str | None, clip_id: str) -> None:
        if project_id is None:
            if self.store.clip(clip_id) is None:
                raise ValueError(f"unknown clip {clip_id}")
        else:
            self.store.require_member(project_id, clip_id)

    def retry(self, project_id: str | None, clip_ids: list[str], progress: Progress | None = None) -> dict:
        """Re-run analysis for chosen clips from their originals, keeping each clip's ID, notes and exclusion.
        Unchanged content with unchanged settings is reused; a missing original is reported, not analysed.
        A shared source's refreshed analysis serves every Project it belongs to."""
        report = progress or (lambda stage, detail: None)
        for clip_id in clip_ids:
            self._require(project_id, clip_id)
        for clip_id in clip_ids:
            clip = self.store.clip(clip_id)
            source = Path(clip["source_path"])
            if not source.is_file():
                self.store.set_status(clip_id, "missing", error=missing_guidance(clip["source_path"]))
                report("missing", {"clip_id": clip_id, "error": missing_guidance(clip["source_path"])})
                continue
            try:
                self._index(clip_id, source, progress, refresh=True)
            except ServiceUnavailable:
                raise  # no clip can be analysed now; the rest keep their state for a later retry
            except Exception:
                continue  # recorded on the clip; the others carry on
        return self._outcome(clip_ids)

    def enrich_tone(self, project_id: str | None, clip_ids: list[str] | None = None,
                    progress: Progress | None = None) -> dict:
        """Read emotional tone for chosen clips (default: every clip of the Project, or of the library) whose
        Segments have none yet, one clip after another. Only saved evidence is used: the cached sampled frames,
        their observations and the transcript, so nothing is re-transcribed or re-described. Clips that are not
        ready are skipped (their saved context may not describe the footage); nothing else is upgraded."""
        report = progress or (lambda stage, detail: None)
        if clip_ids is None:
            if project_id is not None and self.store.project(project_id) is None:
                raise ValueError(f"unknown project {project_id}")
            clip_ids = [c["id"] for c in (self.store.library_clips() if project_id is None
                                           else self.store.clips(project_id))]
        for clip_id in clip_ids:
            self._require(project_id, clip_id)
        for clip_id in clip_ids:
            if self.store.clip(clip_id)["status"] != "ready":
                report("tone_skipped", {"clip_id": clip_id, "reason": "not ready"})
                continue
            try:
                self._read_tones(clip_id, report)
            except ServiceUnavailable:
                raise  # nothing can be read now; what was saved so far stays saved
            except (InferenceError, OSError) as e:
                report("tone_failed", {"clip_id": clip_id, "error": str(e)})
        return self._outcome(clip_ids)

    def _read_tones(self, clip_id: str, report: Progress) -> None:
        """Ask the model for each not-yet-read Segment's tone from saved evidence, saving each as it completes."""
        clip = self.store.clip(clip_id)
        pending = [s for s in self.store.review_clip(clip_id)["segments"] if s["tone"]["analyzed_at"] is None]
        for i, seg in enumerate(pending):
            report("reading_tone", {"clip_id": clip_id, "segment": i + 1, "of": len(pending)})
            # The model sees short local IDs; code maps its citations back to the saved evidence IDs.
            lines = {f"t{n + 1}": t for n, t in enumerate(seg["transcript"])}
            seen = {f"f{n + 1}": o for n, o in enumerate(seg["observations"])}
            request = tone.ToneRequest(
                original_filename=clip["original_filename"], start=seg["start"], end=seg["end"],
                transcript=[TranscriptItem(k, t["start"], t["end"], t["text"]) for k, t in lines.items()],
                frames=[FrameItem(k, o["frame"]["time"], Path(o["frame"]["path"])) for k, o in seen.items()],
                observations={k: o["text"] for k, o in seen.items()})
            for f in request.frames:
                if not f.path.is_file():
                    raise InferenceError(f"sampled frame {f.path.name} is no longer in Clipco's cache; "
                                         "re-analyse the clip to read its tone")
            local = {k: t["id"] for k, t in lines.items()} | {k: o["frame"]["id"] for k, o in seen.items()}
            reading = self._validated_tone(request, set(local))
            for item in reading.tones + reading.connotations:
                item["evidence_ids"] = [local[r] for r in item["evidence_ids"]]
            self.store.save_tone(seg["id"], reading, tone.TONE_RECIPE, self.vision.identity)

    def _validated_tone(self, request: tone.ToneRequest, known: set[str], attempts: int = 2) -> tone.ToneReading:
        for attempt in range(attempts):
            try:
                return tone.validate(self.vision.describe_tone(request), known)
            except ServiceUnavailable:
                raise
            except InferenceError:
                if attempt == attempts - 1:
                    raise

    def check_sources(self, project_id: str | None, progress: Progress | None = None) -> dict:
        """Re-verify every analysed clip against its original and the current analysis settings. A missing
        original marks the clip missing; changed content or settings mark it stale; an original that is back
        and unchanged makes it ready again. Saved context, notes and exclusions are kept throughout."""
        report = progress or (lambda stage, detail: None)
        if project_id is not None and self.store.project(project_id) is None:
            raise ValueError(f"unknown project {project_id}")
        candidates = self.store.library_clips() if project_id is None else self.store.clips(project_id)
        clips = [c for c in candidates
                 if c["revision"] > 0 and c["status"] in ("ready", "stale", "missing")]
        for clip in clips:
            status, error = self._verify(clip, report)
            if (status, error) != (clip["status"], clip["error"]):
                self.store.set_status(clip["id"], status, error=error)
                report(status, {"clip_id": clip["id"], "error": error})
        return self._outcome([c["id"] for c in clips])

    def relink(self, project_id: str | None, clip_id: str, source: Path) -> dict:
        """Point a clip at its original's new location. Only the same content is accepted, so a clip's context,
        notes and relationships are never reassigned to different footage; a different file is a new clip."""
        self._require(project_id, clip_id)
        clip = self.store.clip(clip_id)
        source = Path(source).expanduser().resolve()
        if not source.is_file():
            raise ValueError(f"{source} is not a file")
        other = self.store.source_by_path(str(source), project_id)
        if other and other["id"] != clip_id:
            raise ValueError(f"{source.name} is already clip {other['id']} in the library")
        if not clip["fingerprint"]:  # never analysed: nothing proves the file is this clip's footage
            raise ValueError(f"{clip['original_filename']} was never analysed, so {source.name} cannot be confirmed "
                             "as the same footage. Import it as a new clip instead.")
        if fingerprint(source) != clip["fingerprint"]:
            raise ValueError(f"{source.name} is not the same footage as {clip['original_filename']} (its content "
                             "differs). Import it as a new clip instead.")
        stat = source.stat()
        self.store.set_source(clip_id, str(source), source.name, stat.st_size, stat.st_mtime)
        self.store.set_status(clip_id, *self._verify(self.store.clip(clip_id), lambda stage, detail: None))
        return self._outcome([clip_id])

    def _verify(self, clip: dict, report: Progress) -> tuple[str, str | None]:
        """(status, guidance) for an analysed clip: is its original still there, the same content, and was it
        analysed with the current settings?"""
        source = Path(clip["source_path"])
        try:
            stat = source.stat()
        except OSError:
            return "missing", missing_guidance(clip["source_path"])
        if clip["size_bytes"] == stat.st_size and abs(clip["mtime"] - stat.st_mtime) <= 1e-3:
            content = clip["fingerprint"]
        else:
            report("fingerprinting", {"clip_id": clip["id"]})
            content = fingerprint(source)
            if content != clip["fingerprint"]:
                return "stale", CHANGED_CONTENT
            self.store.set_source(clip["id"], clip["source_path"], clip["original_filename"], stat.st_size,
                                  stat.st_mtime)  # touched but identical
        if changed := self._settings_changed(clip):
            return "stale", (f"Analysis settings changed since this clip was indexed ({', '.join(changed)}). "
                             "Re-analyse to refresh its context.")
        return "ready", None

    def _settings_changed(self, clip: dict) -> list[str]:
        """Which analysis settings differ from those that produced the clip's saved context. A model whose
        identity cannot be read right now (e.g. Ollama not running) is not reported as changed."""
        analysis = self.store.analysis(clip["id"], clip["revision"])
        if analysis is None:
            return []
        changed = []
        saved_recipe, recipe = json.loads(analysis["recipe"]), json.loads(json.dumps(self.recipe))
        if saved_recipe != recipe and not (
                saved_recipe.get("version") in COMPATIBLE_RECIPE_VERSIONS
                and {k: v for k, v in saved_recipe.items() if k not in ROLE_ONLY_KEYS}
                == {k: v for k, v in recipe.items() if k not in ROLE_ONLY_KEYS}):
            changed.append("analysis recipe")
        if json.loads(analysis["speech_identity"]) != json.loads(json.dumps(self.speech.identity)):
            changed.append("speech model")
        saved, current = json.loads(analysis["vision_identity"]), self.vision.identity
        if current.get("digest") == "" and saved.get("model") == current.get("model"):
            pass  # digest unknown right now; same model name, so nothing to report
        elif saved != json.loads(json.dumps(current)):
            changed.append("vision model")
        return changed

    def _outcome(self, clip_ids: list[str]) -> dict:
        clips = [(c, self.store.clip(c)) for c in clip_ids]
        return {"clips": [{"clip_id": c["id"], "original_filename": c["original_filename"], "status": c["status"],
                           "error": c["error"]} if c else {"clip_id": cid, "status": "removed"}
                          for cid, c in clips]}

    def import_folder(self, project_id: str | None, folder: Path, progress: Progress | None = None) -> dict:
        return self.import_sources(project_id, [folder], progress)

    def import_sources(self, project_id: str | None, paths: list[Path], progress: Progress | None = None) -> dict:
        """Register every chosen video file, and every video in chosen folders (and their subfolders, skipping
        hidden ones), as pending, then index each one. A clip that fails stays failed while the others continue;
        if the local model service is unavailable, the import stops with that error and the rest stay pending."""
        report = progress or (lambda stage, detail: None)
        if project_id is not None and self.store.project(project_id) is None:
            raise ValueError(f"unknown project {project_id}")
        found: set[Path] = set()
        for path in (Path(p).expanduser().resolve() for p in paths):
            if path.is_dir():
                found |= {p for p in path.rglob("*")
                          if not any(part.startswith(".") for part in p.relative_to(path).parts)}
            else:
                found.add(path)
        # Clips are identified by their resolved original path, as import_clip does, so a linked or twice-chosen
        # file is one clip.
        sources = sorted({p.resolve() for p in found if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES})
        if not sources:
            raise ValueError("no video files in the chosen items")
        registered = []
        for source in sources:
            clip_id, new = self._register(project_id, source)
            registered.append(clip_id)
            if new:
                report("pending", {"clip_id": clip_id, "filename": source.name})
        for clip_id, source in zip(registered, sources):
            try:
                self._index(clip_id, source, progress)
            except ServiceUnavailable:
                raise  # no clip can be analysed now; the rest stay pending for a retry
            except Exception:
                continue  # recorded on the clip as failed; the rest of the Project carries on
        return self._outcome(registered)

    def _describe(self, request: SegmentRequest, attempts: int = 2):
        """Ask the model for validated context, retrying once when its output fails validation."""
        for attempt in range(attempts):
            try:
                return validate(self.vision.describe(request), request)
            except ServiceUnavailable:
                raise
            except InferenceError:
                if attempt == attempts - 1:
                    raise

    def _analyse(self, clip_id: str, source: Path, stage: Callable) -> dict:
        recipe = self.recipe
        stage("probing")
        info = media.probe(source)
        frames_dir = self.home / "frames" / clip_id / uuid.uuid4().hex[:8]
        frames_dir.mkdir(parents=True)
        try:
            spans: list[TranscriptSpan] = []
            language = None
            if info.has_audio:
                with tempfile.TemporaryDirectory() as tmp:
                    stage("extracting_audio")
                    wav = media.extract_audio(source, Path(tmp) / "audio.wav")
                    stage("transcribing")
                    transcript = self.speech.transcribe(wav)
                    quiet = (media.silences(wav, recipe["silent_gap_seconds"], recipe["silence_noise_db"])
                             if "silence_noise_db" in recipe else [])
                    spans, language = clean_spans(transcript.spans, info.duration, quiet), transcript.language
            planned = plan_segments(info.duration, spans, recipe)
            per_segment = recipe["frames_per_segment"]
            if len(planned) * per_segment > recipe["max_frames"]:
                per_segment = 1
            segments = []
            facing = 0  # speaking Segments whose frames show a person addressing the camera
            for ordinal, (start, end, group) in enumerate(planned):
                stage("sampling_frames", segment=ordinal + 1, of=len(planned))
                frames = []
                for t in frame_times(start, end, per_segment):
                    t = min(t, info.duration - 0.05)
                    fid = new_id("frm")
                    path = media.extract_frame(source, t, frames_dir / f"{fid}.jpg", recipe["frame_width"])
                    frames.append({"id": fid, "time": t, "path": str(path)})
                transcript = [{"id": new_id("trn"), "start": s.start, "end": s.end, "text": s.text} for s in group]
                local = {f"t{i + 1}": t["id"] for i, t in enumerate(transcript)}
                local |= {f"f{i + 1}": f["id"] for i, f in enumerate(frames)}
                request = SegmentRequest(
                    original_filename=source.name, start=start, end=end,
                    transcript=[TranscriptItem(f"t{i + 1}", t["start"], t["end"], t["text"])
                                for i, t in enumerate(transcript)],
                    frames=[FrameItem(f"f{i + 1}", f["time"], Path(f["path"])) for i, f in enumerate(frames)],
                )
                stage("describing", segment=ordinal + 1, of=len(planned))
                desc = self._describe(request)
                facing += bool(group) and desc.speaker_facing_camera
                role, role_basis = roles.suggest(start, end, sum(s.end - s.start for s in group),
                                                 desc.speaker_facing_camera)
                segments.append({
                    "role": role, "role_basis": role_basis,
                    "id": new_id("seg"), "ordinal": ordinal, "start": start, "end": end, "label": desc.label,
                    "transcript": transcript, "frames": frames,
                    "observations": [(local[fid], text) for fid, text in desc.observations],
                    "interpretation": desc.interpretation,
                    "evidence_ids": [local[ref] for ref in desc.evidence_ids],
                    "rejected_refs": desc.rejected_refs,
                })
        except BaseException:
            shutil.rmtree(frames_dir, ignore_errors=True)
            raise
        # A-roll: someone speaks for most of the clip and, in at least half of the speaking Segments, is seen
        # facing the camera. Speech alone (a voice-over) or a person alone (silent B-roll) is not A-roll.
        speech_seconds = sum(s.end - s.start for s in spans)
        speaking = sum(1 for _, _, group in planned if group)
        is_a_roll = speech_seconds >= A_ROLL_SPEECH_SHARE * info.duration and speaking and facing >= speaking / 2
        return {
            "clip": {
                "duration": info.duration, "width": info.width, "height": info.height, "fps": info.fps,
                "video_codec": info.video_codec, "audio_codec": info.audio_codec,
                "label": segments[0]["label"],
                "speech_language": language,
                "role": "a-roll" if is_a_roll else "b-roll",
                "role_basis": f"speech covers {speech_seconds / info.duration:.0%} of the clip; a person is "
                              f"facing the camera in {facing} of {speaking} speaking segments",
            },
            "segments": segments,
        }
