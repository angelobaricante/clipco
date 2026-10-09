"""Import orchestration: measure, transcribe, sample, describe, validate, publish."""

import hashlib
import json
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from . import media
from .speech import TranscriptSpan
from .store import Store
from .vision import FrameItem, InferenceError, SegmentRequest, ServiceUnavailable, TranscriptItem, validate

# Bump when segmentation/sampling/prompting changes so cached analyses are invalidated.
RECIPE = {
    "version": 4,  # 2: multilingual speech; 3: drop non-speech annotations; 4: loop guard
    "segment_target_seconds": 30.0,
    "silent_segment_seconds": 10.0,
    "frames_per_segment": 2,
    "max_frames": 24,
    "frame_width": 512,
}

Progress = Callable[[str, dict], None]

VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts"})


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


def clean_spans(spans: list[TranscriptSpan], duration: float) -> list[TranscriptSpan]:
    """Keep only actual speech with valid source-relative bounds; clamp alignment overrun at the end."""
    kept = []
    for s in sorted(spans, key=lambda s: s.start):
        start, end = max(0.0, s.start), min(s.end, duration)
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
    groups: list[list[TranscriptSpan]] = [[]]
    for s in spans:
        if groups[-1] and s.end - groups[-1][0].start > recipe["segment_target_seconds"]:
            groups.append([])
        groups[-1].append(s)
    segments = []
    for i, group in enumerate(groups):
        start = 0.0 if i == 0 else group[0].start
        end = duration if i == len(groups) - 1 else groups[i + 1][0].start
        segments.append((start, end, group))
    return segments


def frame_times(start: float, end: float, per_segment: int) -> list[float]:
    span = end - start
    n = 1 if span < 4 else per_segment
    return [round(start + span * (i + 1) / (n + 1), 3) for i in range(n)]


class Worker:
    def __init__(self, home: Path, speech, vision, recipe: dict | None = None):
        self.home = Path(home)
        self.store = Store(self.home / "index.sqlite")
        self.speech = speech
        self.vision = vision
        self.recipe = recipe or RECIPE

    def create_project(self, name: str, context: str = "") -> dict:
        return self.store.create_project(new_id("prj"), name.strip(), context.strip())

    def snapshot(self, project_id: str) -> dict:
        return self.store.snapshot(project_id)

    def analysis_key(self, content_fingerprint: str) -> str:
        material = json.dumps({"source": content_fingerprint, "recipe": self.recipe,
                               "speech": self.speech.identity, "vision": self.vision.identity}, sort_keys=True)
        return hashlib.sha256(material.encode()).hexdigest()

    def import_clip(self, project_id: str, source: Path, progress: Progress | None = None) -> dict:
        report = progress or (lambda stage, detail: None)
        source = Path(source).expanduser().resolve()
        if self.store.project(project_id) is None:
            raise ValueError(f"unknown project {project_id}")
        existing = self.store.clip_by_path(project_id, str(source))
        clip_id = existing["id"] if existing else new_id("clp")
        if not existing:
            self.store.add_clip(clip_id, project_id, str(source), source.name)

        def stage(name: str, **detail) -> None:
            self.store.set_status(clip_id, "indexing", stage=name)
            report(name, {"clip_id": clip_id, **detail})

        try:
            stat = source.stat()
            ready = existing is not None and existing["status"] == "ready"
            if ready and existing["size_bytes"] == stat.st_size and abs(existing["mtime"] - stat.st_mtime) <= 1e-3:
                # Same size and modification time as when indexed (the check resolve_media applies): trust the
                # saved content fingerprint instead of rehashing gigabytes, and keep the clip ready meanwhile.
                report("fingerprinting", {"clip_id": clip_id, "cached": True})
                content = existing["fingerprint"]
            else:
                stage("fingerprinting")
                content = fingerprint(source)
            key = self.analysis_key(content)
            if ready and existing["analysis_key"] == key:
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
            report("ready", {"clip_id": clip_id, "reused": False, "revision": revision})
            return {"clip_id": clip_id, "reused": False, "revision": revision}
        except Exception as e:
            self.store.set_status(clip_id, "failed", error=f"{type(e).__name__}: {e}")
            report("failed", {"clip_id": clip_id, "error": str(e)})
            raise

    def import_folder(self, project_id: str, folder: Path, progress: Progress | None = None) -> dict:
        """Register every video file in a folder (and its subfolders, skipping hidden ones) as pending, then index
        each one. A clip that fails stays failed while the others continue; if the local model service is
        unavailable, the import stops with that error and the remaining clips stay pending."""
        report = progress or (lambda stage, detail: None)
        folder = Path(folder).expanduser().resolve()
        if self.store.project(project_id) is None:
            raise ValueError(f"unknown project {project_id}")
        # Clips are identified by their resolved original path, as import_clip does, so a linked file is one clip.
        sources = sorted({p.resolve() for p in folder.rglob("*")
                          if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES
                          and not any(part.startswith(".") for part in p.relative_to(folder).parts)})
        if not sources:
            raise ValueError(f"no video files in {folder}")
        for source in sources:
            if not self.store.clip_by_path(project_id, str(source)):
                clip_id = new_id("clp")
                self.store.add_clip(clip_id, project_id, str(source), source.name)
                report("pending", {"clip_id": clip_id, "filename": source.name})
        for source in sources:
            try:
                self.import_clip(project_id, source, progress)
            except ServiceUnavailable:
                raise  # no clip can be analysed now; the rest stay pending for a retry
            except Exception:
                continue  # recorded on the clip as failed; the rest of the Project carries on
        clips = [self.store.clip_by_path(project_id, str(s)) for s in sources]
        return {"clips": [{"clip_id": c["id"], "original_filename": c["original_filename"], "status": c["status"],
                           "error": c["error"]} for c in clips]}

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
        project_context = self.store.project_context_for_clip(clip_id)
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
                    spans, language = clean_spans(transcript.spans, info.duration), transcript.language
            planned = plan_segments(info.duration, spans, recipe)
            per_segment = recipe["frames_per_segment"]
            if len(planned) * per_segment > recipe["max_frames"]:
                per_segment = 1
            segments = []
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
                    project_context=project_context,
                    original_filename=source.name, start=start, end=end,
                    transcript=[TranscriptItem(f"t{i + 1}", t["start"], t["end"], t["text"])
                                for i, t in enumerate(transcript)],
                    frames=[FrameItem(f"f{i + 1}", f["time"], Path(f["path"])) for i, f in enumerate(frames)],
                )
                stage("describing", segment=ordinal + 1, of=len(planned))
                desc = self._describe(request)
                segments.append({
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
        speech_seconds = sum(s.end - s.start for s in spans)
        is_a_roll = speech_seconds >= 0.4 * info.duration
        return {
            "clip": {
                "duration": info.duration, "width": info.width, "height": info.height, "fps": info.fps,
                "video_codec": info.video_codec, "audio_codec": info.audio_codec,
                "label": segments[0]["label"],
                "speech_language": language,
                "role": "a-roll" if is_a_roll else "b-roll",
                "role_basis": f"speech covers {speech_seconds / info.duration:.0%} of the clip",
            },
            "segments": segments,
        }
