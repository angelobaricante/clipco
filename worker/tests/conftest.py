import hashlib
import subprocess
from pathlib import Path

import pytest

from clipco_worker.speech import Transcript, TranscriptSpan


def make_clip(path: Path, seconds: float = 12.0, audio: bool = True) -> Path:
    """Render a small real video file (test pattern, plus a tone when audio is wanted) with FFmpeg."""
    tone = ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", "-shortest"]
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=24:duration={seconds}",
            *(tone if audio else []),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RecordedSpeech:
    """Replays whisper-shaped spans; counts calls to observe cache reuse."""

    identity = {"engine": "recorded-speech", "model": "fixture"}

    def __init__(self, spans, language: str = "en"):
        self.spans = spans
        self.language = language
        self.calls = 0

    def transcribe(self, wav_path: Path):
        self.calls += 1
        assert wav_path.exists()
        return Transcript(list(self.spans), self.language)


class ScriptedSpeech:
    """Replays one transcript per transcribed clip, in import order (clips without audio are skipped)."""

    identity = {"engine": "scripted-speech", "model": "fixture"}

    def __init__(self, *scripts: list[TranscriptSpan]):
        self.scripts = list(scripts)
        self.calls = 0

    def transcribe(self, wav_path: Path):
        self.calls += 1
        return Transcript(list(self.scripts[(self.calls - 1) % len(self.scripts)]), "en")


class ScriptedVision:
    """Describes each clip's sampled frames with the text scripted for its filename; can fail named clips."""

    identity = {"engine": "scripted-vision", "model": "fixture"}

    def __init__(self, scripts: dict[str, str], fail: set[str] = frozenset(),
                 facing_camera: set[str] = frozenset({"a-roll.mp4"}), tones: dict[str, dict] | None = None):
        self.scripts = scripts
        self.fail = set(fail)
        self.facing_camera = set(facing_camera)
        self.tones = tones or {}
        self.calls = 0
        self.tone_calls = 0
        self.on_describe = lambda request: None

    def describe_tone(self, request):
        """Tone readings scripted per filename ({"tones": [(tone, why)], "connotations": [(idea, why)]}), each
        citing every frame it was given."""
        self.tone_calls += 1
        script = self.tones.get(request.original_filename, {})
        cited = [f.id for f in request.frames] or [t.id for t in request.transcript]
        return {"tones": [{"tone": t, "explanation": why, "evidence_ids": cited} for t, why in script.get("tones", [])],
                "connotations": [{"idea": i, "explanation": why, "evidence_ids": cited}
                                 for i, why in script.get("connotations", [])],
                "depicted_emotion": script.get("depicted_emotion", "")}

    def describe(self, request):
        from clipco_worker.vision import InferenceError

        self.calls += 1
        self.on_describe(request)
        if request.original_filename in self.fail:
            raise InferenceError(f"recorded failure for {request.original_filename}")
        seen = self.scripts.get(request.original_filename, "A test pattern.")
        return {
            "label": seen.split(".")[0][:60],
            "observations": [{"frame_id": f.id, "text": seen} for f in request.frames],
            "interpretation": seen,
            "evidence_ids": [t.id for t in request.transcript] + [f.id for f in request.frames],
            "speaker_facing_camera": request.original_filename in self.facing_camera,
        }


class RecordedVision:
    """Replays model-shaped JSON that cites the evidence IDs it was given."""

    identity = {"engine": "recorded-vision", "model": "fixture"}

    def __init__(self, invent_ids: bool = False, fail: bool = False, only_invented: bool = False,
                 echo_prompt_lines: bool = False):
        self.invent_ids = invent_ids
        self.echo_prompt_lines = echo_prompt_lines  # cite "f1 at 4.0s" as the prompt lists it, not "f1"
        self.only_invented = only_invented
        self.fail = fail
        self.calls = 0
        self.requests = []

    def describe_tone(self, request):
        return {"tones": [], "connotations": [], "depicted_emotion": ""}

    def describe(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.fail:
            from clipco_worker.vision import InferenceError
            raise InferenceError("recorded failure")
        frame_ids = [f"{f.id} at {f.time:.1f}s" if self.echo_prompt_lines else f.id for f in request.frames]
        transcript_ids = [f"{t.id} [{t.start:.1f}-{t.end:.1f}s]" if self.echo_prompt_lines else t.id
                          for t in request.transcript]
        observations = [
            {"frame_id": fid, "text": f"Colour bars test pattern in {fid}."} for fid in frame_ids
        ]
        cited = transcript_ids + frame_ids
        if self.invent_ids:
            observations.append({"frame_id": "f999", "text": "A frame that was never sampled."})
            cited = cited + ["t999"]
        if self.only_invented:
            cited = ["t999", "f999"]
        return {
            "label": "Test pattern explanation",
            "observations": observations,
            "interpretation": "The speaker introduces the test pattern.",
            "evidence_ids": cited,
            "speaker_facing_camera": True,
        }


SPANS = [
    TranscriptSpan(0.0, 4.2, "Today I'll explain the test pattern."),
    TranscriptSpan(4.2, 8.9, "Actually, I mean the colour bars."),
    TranscriptSpan(8.9, 11.5, "That's the whole idea."),
]


@pytest.fixture
def clip(tmp_path) -> Path:
    footage = tmp_path / "footage"
    footage.mkdir()
    return make_clip(footage / "talking-head.mp4")


@pytest.fixture
def home(tmp_path) -> Path:
    return tmp_path / "clipco-home"
