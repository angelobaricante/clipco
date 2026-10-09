"""Real speech + vision smoke test through the worker CLI the app uses.

Requires whisper.cpp, the multilingual ggml large-v3-turbo model, and a running local Ollama with
qwen3.5:4b-q4_K_M. Run with: uv run pytest -m real -s
The English clip is synthesised locally: macOS speech synthesis over a system desktop photo.
macOS has no Tagalog voice, so the Tagalog check runs on a real clip you supply:
  CLIPCON_TAGALOG_CLIP=/path/to/tagalog-or-taglish.mp4 uv run pytest -m real -s -k tagalog
"""

import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import sha256

pytestmark = pytest.mark.real

SCRIPT = ("Today I'm going to show you how a gravity water filter works. "
          "First, pour the dirty water into the top chamber. "
          "Actually, I mean the upper tank, not the chamber. "
          "Then the water slowly drips through the ceramic filter.")
PHOTO = Path("/System/Library/Desktop Pictures/Sonoma.heic")


def synth_clip(folder: Path) -> Path:
    speech, still = folder / "speech.aiff", folder / "still.jpg"
    subprocess.run(["say", "-v", "Samantha", "-o", str(speech), SCRIPT], check=True)
    subprocess.run(["sips", "-s", "format", "jpeg", "-Z", "1280", str(PHOTO), "--out", str(still)],
                   check=True, capture_output=True)
    clip = folder / "a-roll-explainer.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(still), "-i", str(speech),
                    "-vf", "scale=1280:-2,format=yuv420p", "-r", "24", "-c:v", "libx264", "-c:a", "aac",
                    "-shortest", str(clip)], check=True)
    speech.unlink()
    still.unlink()
    return clip


def worker(home: Path, *args: str) -> list[dict]:
    out = subprocess.run([sys.executable, "-m", "clipcon_worker.cli", "--home", str(home), *args],
                         capture_output=True, text=True)
    events = [json.loads(line) for line in out.stdout.splitlines()]
    assert events and events[-1]["event"] == "result", out.stderr + out.stdout
    return events


def test_real_speech_and_vision_context(tmp_path):
    footage = tmp_path / "footage"
    footage.mkdir()
    clip = synth_clip(footage)
    original = sha256(clip)
    home = tmp_path / "home"

    warm = worker(home, "warmup")[-1]["readiness"]
    assert warm["state"] == "ready", warm

    project = worker(home, "create-project", "--name", "Water filter", "--context",
                     "A tutorial explaining how a gravity water filter works")[-1]["project"]
    started = time.monotonic()
    events = worker(home, "import", "--project", project["id"], str(clip))
    elapsed = time.monotonic() - started
    assert events[-1]["reused"] is False
    stages = [e["stage"] for e in events if e["event"] == "progress"]
    assert {"probing", "transcribing", "describing", "saving", "ready"} <= set(stages)

    [saved] = worker(home, "snapshot", "--project", project["id"])[-1]["snapshot"]["clips"]
    assert saved["status"] == "ready"
    spoken = " ".join(t["text"] for s in saved["segments"] for t in s["transcript"]).lower()
    assert "water filter" in spoken and "actually" in spoken
    assert saved["speech_language"] == "en"
    for seg in saved["segments"]:
        assert 0 <= seg["start"] < seg["end"] <= saved["duration"]
        for t in seg["transcript"]:
            assert seg["start"] <= t["start"] < t["end"] <= seg["end"]
        assert seg["observations"], "every segment has sampled-frame observations"
        assert seg["interpretation"]["text"]
    assert saved["analysis"]["vision"]["model"] == "qwen3.5:4b-q4_K_M"
    assert saved["analysis"]["vision"]["digest"]

    reuse_started = time.monotonic()
    again = worker(home, "import", "--project", project["id"], str(clip))[-1]
    assert again["reused"] is True
    assert sha256(clip) == original

    report = {
        "clip_duration_s": saved["duration"],
        "import_elapsed_s": round(elapsed, 1),
        "reuse_elapsed_s": round(time.monotonic() - reuse_started, 2),
        "segments": len(saved["segments"]),
        "child_peak_rss_mb": round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 2**20, 1),
        "speech": saved["analysis"]["speech"],
        "vision": saved["analysis"]["vision"],
        "transcript": [t["text"] for s in saved["segments"] for t in s["transcript"]],
        "segments_detail": [{"range": [round(s["start"], 2), round(s["end"], 2)], "label": s["label"],
                             "observations": [o["text"] for o in s["observations"]],
                             "interpretation": s["interpretation"]["text"],
                             "rejected_refs": s["interpretation"]["rejected_refs"]}
                            for s in saved["segments"]],
    }
    print("\nSMOKE REPORT " + json.dumps(report, indent=2))


@pytest.mark.skipif(not os.environ.get("CLIPCON_TAGALOG_CLIP"), reason="set CLIPCON_TAGALOG_CLIP to a real clip")
def test_real_tagalog_speech_is_detected_and_transcribed(tmp_path):
    clip = Path(os.environ["CLIPCON_TAGALOG_CLIP"]).expanduser()
    original = sha256(clip)
    home = tmp_path / "home"
    assert worker(home, "warmup")[-1]["readiness"]["state"] == "ready"
    project = worker(home, "create-project", "--name", "Tagalog check")[-1]["project"]

    started = time.monotonic()
    worker(home, "import", "--project", project["id"], str(clip))
    elapsed = time.monotonic() - started

    [saved] = worker(home, "snapshot", "--project", project["id"])[-1]["snapshot"]["clips"]
    assert saved["status"] == "ready"
    assert saved["speech_language"] == "tl"
    assert sha256(clip) == original
    print("\nTAGALOG REPORT " + json.dumps({
        "clip_duration_s": round(saved["duration"], 1), "import_elapsed_s": round(elapsed, 1),
        "transcript": [f"[{t['start']:.1f}-{t['end']:.1f}] {t['text']}"
                       for s in saved["segments"] for t in s["transcript"]],
        "interpretations": [s["interpretation"]["text"] for s in saved["segments"]],
    }, indent=2, ensure_ascii=False))
