"""FFmpeg/ffprobe adapters. Media is only ever read; outputs go to Clipcon's own directories."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


class MediaError(Exception):
    pass


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    size_bytes: int

    @property
    def has_audio(self) -> bool:
        return self.audio_codec is not None


def _run(args: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise MediaError(f"{args[0]} is not installed") from e
    except subprocess.CalledProcessError as e:
        raise MediaError(f"{args[0]} failed: {e.stderr.strip()[-400:]}") from e


def probe(path: Path) -> MediaInfo:
    out = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    data = json.loads(out.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise MediaError("no video stream")
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    if duration <= 0:
        raise MediaError("could not measure duration")
    fps = None
    if rate := video.get("avg_frame_rate"):
        num, _, den = rate.partition("/")
        if den and float(den):
            fps = round(float(num) / float(den), 3)
    return MediaInfo(
        duration=duration,
        width=video.get("width"),
        height=video.get("height"),
        fps=fps,
        video_codec=video.get("codec_name"),
        audio_codec=audio.get("codec_name") if audio else None,
        size_bytes=path.stat().st_size,
    )


def extract_audio(path: Path, wav: Path) -> Path:
    """16 kHz mono PCM, the input whisper.cpp expects."""
    _run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
          "-c:a", "pcm_s16le", str(wav)])
    return wav


def extract_frame(path: Path, time: float, out: Path, width: int = 512) -> Path:
    _run(["ffmpeg", "-v", "error", "-y", "-ss", f"{time:.3f}", "-i", str(path), "-frames:v", "1",
          "-vf", f"scale={width}:-2", "-q:v", "4", str(out)])
    if not out.exists():
        raise MediaError(f"no frame decoded at {time:.3f}s")
    return out
