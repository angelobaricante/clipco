"""whisper.cpp adapter: speech evidence with source-relative timestamps from alignment."""

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import cancel


class SpeechError(Exception):
    pass


@dataclass(frozen=True)
class TranscriptSpan:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    spans: list[TranscriptSpan]
    language: str | None  # as detected (or forced) by whisper, e.g. "en", "tl"


# A punctuated Taglish initial prompt: large-v3-turbo otherwise tends to drop punctuation and casing,
# and an English-only prompt would bias language detection away from Tagalog.
INITIAL_PROMPT = "Hello, everyone. Kumusta kayo? Today, ipapakita ko kung paano ito gumagana."


# Cap on previous-text context carried between decoding windows. Unlimited context let large-v3-turbo
# loop on Taglish footage; 0 also discards the initial prompt (and with it punctuation). 64 kept both
# behaviours on the English and Taglish clips measured on Oct 9.
MAX_CONTEXT_TOKENS = 64


class WhisperCppSpeech:
    def __init__(self, model_path: Path, vad_model_path: Path, binary: str = "whisper-cli", language: str = "auto",
                 prompt: str = INITIAL_PROMPT):
        """language: a whisper language code ("en", "tl") or "auto" to detect it per clip.

        vad_model_path: Silero voice-activity model. Only audio it detects as voice is transcribed; without it,
        whisper invents speech for room tone (e.g. "Konec." over silent B-roll).
        """
        self.model_path = Path(model_path)
        self.vad_model_path = Path(vad_model_path)
        self.binary = binary
        self.language = language
        self.prompt = prompt

    @property
    def identity(self) -> dict:
        return {"engine": "whisper.cpp", "model": self.model_path.name,
                "model_bytes": self.model_path.stat().st_size if self.model_path.exists() else None,
                "language": self.language, "prompt": self.prompt, "max_context": MAX_CONTEXT_TOKENS,
                "vad_model": self.vad_model_path.name}

    def transcribe(self, wav_path: Path) -> Transcript:
        for path in (self.model_path, self.vad_model_path):
            if not path.exists():
                raise SpeechError(f"speech model missing: {path}")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "transcript"
            try:
                cancel.run(  # stopped if the creator cancels the job
                    [self.binary, "-m", str(self.model_path), "-f", str(wav_path), "-l", self.language,
                     "--prompt", self.prompt, "-mc", str(MAX_CONTEXT_TOKENS), "-oj", "-of", str(base), "-np",
                     "--vad", "-vm", str(self.vad_model_path)],
                )
            except FileNotFoundError as e:
                raise SpeechError(f"{self.binary} is not installed") from e
            except subprocess.CalledProcessError as e:
                raise SpeechError(f"whisper.cpp failed: {e.stderr.strip()[-400:]}") from e
            data = json.loads(base.with_suffix(".json").read_text())
        spans = []
        for item in data.get("transcription", []):
            text = item.get("text", "").strip()
            if not text:
                continue
            offsets = item["offsets"]
            spans.append(TranscriptSpan(offsets["from"] / 1000, offsets["to"] / 1000, text))
        return Transcript(spans, data.get("result", {}).get("language"))
