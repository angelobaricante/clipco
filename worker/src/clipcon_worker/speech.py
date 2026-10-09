"""whisper.cpp adapter: speech evidence with source-relative timestamps from alignment."""

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class SpeechError(Exception):
    pass


@dataclass(frozen=True)
class TranscriptSpan:
    start: float
    end: float
    text: str


class WhisperCppSpeech:
    def __init__(self, model_path: Path, binary: str = "whisper-cli", language: str = "en"):
        self.model_path = Path(model_path)
        self.binary = binary
        self.language = language

    @property
    def identity(self) -> dict:
        return {"engine": "whisper.cpp", "model": self.model_path.name,
                "model_bytes": self.model_path.stat().st_size if self.model_path.exists() else None,
                "language": self.language}

    def transcribe(self, wav_path: Path) -> list[TranscriptSpan]:
        if not self.model_path.exists():
            raise SpeechError(f"whisper model missing: {self.model_path}")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "transcript"
            try:
                subprocess.run(
                    [self.binary, "-m", str(self.model_path), "-f", str(wav_path), "-l", self.language,
                     "-oj", "-of", str(base), "-np"],
                    check=True, capture_output=True, text=True,
                )
            except FileNotFoundError as e:
                raise SpeechError(f"{self.binary} is not installed") from e
            except subprocess.CalledProcessError as e:
                raise SpeechError(f"whisper.cpp failed: {e.stderr.strip()[-400:]}") from e
            data = json.loads(base.with_suffix(".json").read_text())
        spans = []
        for item in data.get("transcription", []):
            text = item.get("text", "").strip()
            if not text or text.startswith("[") and text.endswith("]"):  # e.g. [BLANK_AUDIO], [Music]
                continue
            offsets = item["offsets"]
            spans.append(TranscriptSpan(offsets["from"] / 1000, offsets["to"] / 1000, text))
        return spans
