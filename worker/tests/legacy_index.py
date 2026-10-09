"""Builds a footage index with the Project-owned worker as released before the Footage library (commit 6cde551),
so migration is exercised against an index that code actually wrote, not a hand-made imitation."""

import json
import os
import subprocess
import sys
from pathlib import Path

LEGACY_COMMIT = "6cde551"
REPO = Path(__file__).resolve().parents[2]

# Runs inside a subprocess whose import path puts the legacy clipcon_worker first.
SCRIPT = r"""
import json, sys
from pathlib import Path
from conftest import ScriptedSpeech, ScriptedVision, make_clip
from test_project import A_ROLL, B_ROLL, corpus
from clipcon_worker.pipeline import RECIPE, Worker
from clipcon_worker.retrieval import Index

home, tmp = Path(sys.argv[1]), Path(sys.argv[2])
folder = corpus(tmp / "shoot")
worker = Worker(home, speech=ScriptedSpeech(A_ROLL), vision=ScriptedVision(B_ROLL),
                recipe={**RECIPE, "segment_target_seconds": 1.0})
tutorial = worker.create_project("Gravity filter tutorial")
worker.import_folder(tutorial["id"], folder)
ideas = worker.create_project("Kitchen ideas")
worker.import_clip(ideas["id"], folder / "broll-1-pour.mp4")  # the same file again, in another Project
gone = make_clip(tmp / "old-cutaway.mp4", seconds=6.0, audio=False)
worker.import_clip(ideas["id"], gone)
gone.unlink()  # completed, then its original went away
def clips(pid):
    return {c["original_filename"]: c for c in worker.snapshot(pid)["clips"]}
a, b = clips(tutorial["id"]), clips(ideas["id"])
worker.store.set_note(a["broll-1-pour.mp4"]["id"], "Tutorial: use the slow pour.")
worker.store.set_note(b["broll-1-pour.mp4"]["id"], "Kitchen: pour for the lemonade idea.")
worker.store.set_note(a["a-roll.mp4"]["id"], "Use the second take.")
worker.store.set_excluded(tutorial["id"], [a["broll-3-cartridge.mp4"]["id"]], True)
worker.store.set_excluded(ideas["id"], [b["broll-1-pour.mp4"]["id"]], True)
index = Index(home)
held = {}
for pid in (tutorial["id"], ideas["id"]):
    for name, clip in clips(pid).items():
        for seg in clip["segments"]:
            held[seg["id"]] = index.segment_context(seg["id"])
print(json.dumps({"tutorial": tutorial["id"], "ideas": ideas["id"], "folder": str(folder),
                  "clips": {"tutorial": a, "ideas": b}, "held": held}))
"""


def legacy_source(cache: Path) -> Path:
    src = cache / "legacy-src"
    if not (src / "clipcon_worker").exists():
        cache.mkdir(parents=True, exist_ok=True)
        archive = subprocess.run(["git", "-C", str(REPO), "archive", LEGACY_COMMIT, "worker/src", "worker/tests"],
                                 check=True, capture_output=True).stdout
        subprocess.run(["tar", "-x", "-C", str(cache)], input=archive, check=True)
        (cache / "worker" / "src").rename(src)
        (cache / "worker" / "tests").rename(cache / "legacy-tests")
    return src


def build_legacy_index(home: Path, tmp: Path, cache: Path) -> dict:
    """Index a shoot with the legacy worker; returns its Project IDs, clips, and the context it served."""
    src = legacy_source(cache)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(src), str(cache / "legacy-tests")])}
    proc = subprocess.run([sys.executable, "-c", SCRIPT, str(home), str(tmp)], env=env, capture_output=True,
                          text=True, timeout=300, cwd=cache)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.splitlines()[-1])
