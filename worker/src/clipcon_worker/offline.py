"""Offline proof: show the internet is unreachable, then index one new clip live and search it locally.

Local-only configuration is not proof, so the report records what was actually attempted: outbound
connections to well-known public hosts and DNS resolution, each with the error it got.
"""

import json
import resource
import socket
import subprocess
import time
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .retrieval import Index

# Public anycast DNS/HTTPS and Apple's connectivity check: any one answering means the internet is up.
PROBE_TARGETS = [("1.1.1.1", 443), ("8.8.8.8", 53), ("captive.apple.com", 80)]


class StillOnline(RuntimeError):
    """The internet answered, so an import now would prove nothing about offline use."""


def probe_internet(targets=PROBE_TARGETS, timeout: float = 3.0) -> dict:
    """Try a TCP connection (resolving names first) to each target; record what happened."""
    results = []
    for host, port in targets:
        target = f"{host}:{port}"
        try:
            with socket.create_connection((host, port), timeout=timeout):
                results.append({"target": target, "reachable": True, "error": None})
        except OSError as e:
            results.append({"target": target, "reachable": False, "error": f"{type(e).__name__}: {e}"})
    return {"internet_reachable": any(r["reachable"] for r in results),
            "method": f"TCP connect (with DNS lookup for names), {timeout:g}s timeout, from this process",
            "targets": results}


def offline_proof(worker, project_id: str, source: Path, queries: list[str],
                  probe: Callable[[], dict] = probe_internet, progress=None) -> dict:
    """Refuse while online; otherwise import `source` with the worker's real models and search the index."""
    network = probe()
    if network["internet_reachable"]:
        up = ", ".join(t["target"] for t in network["targets"] if t["reachable"])
        raise StillOnline(f"the internet is reachable ({up}); turn networking off, then run this again")

    started = time.monotonic()
    outcome = worker.import_clip(project_id, source, progress)
    elapsed = time.monotonic() - started
    clip = next(c for c in worker.snapshot(project_id)["clips"] if c["id"] == outcome["clip_id"])
    live = not outcome["reused"]

    index = Index(worker.home)
    searches = []
    for query in queries:
        t0 = time.monotonic()
        page = index.search(project_id, query, limit=5)
        searches.append({
            "query": query,
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
            "top": [{"segment_id": r["segment_id"], "original_filename": r["original_filename"],
                     "start": r["start"], "end": r["end"]} for r in page["results"]],
        })

    reasons = []
    if not live:
        reasons.append("the clip was already indexed, so its context was reused rather than inferred offline")
    if clip["status"] != "ready":
        reasons.append(f"the clip ended {clip['status']}: {clip.get('error')}")
    if not any(s["top"] for s in searches):
        reasons.append("no search returned a result")
    return {
        "offline": network,
        "models": {"speech": worker.speech.identity, "vision": worker.vision.identity},
        "import": {"clip_id": clip["id"], "original_filename": clip["original_filename"],
                   "duration": clip["duration"], "status": clip["status"], "live_inference": live,
                   "revision": outcome["revision"], "segments": len(clip["segments"]),
                   "elapsed_seconds": round(elapsed, 2)},
        "searches": searches,
        "verdict": {"offline_verified": not reasons, "reasons": reasons},
    }


def machine() -> dict:
    """The tested hardware and OS, as macOS reports them."""
    def run(*cmd: str) -> str:
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False).stdout.strip()
        except OSError:
            return ""
    memsize = run("sysctl", "-n", "hw.memsize")
    return {"model": run("sysctl", "-n", "hw.model"), "chip": run("sysctl", "-n", "machdep.cpu.brand_string"),
            "memory_gb": round(int(memsize) / 2**30) if memsize.isdigit() else None,
            "macos": run("sw_vers", "-productVersion")}


def memory(ollama_host: str) -> dict:
    """Peak memory of this worker process and current resident memory of the local Ollama processes."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS
    peak += resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss  # largest child: whisper-cli or ffmpeg
    out = {"worker_plus_largest_child_peak_mb": round(peak / 2**20),
           "note": "worker peak = this process + its largest child (ru_maxrss), measured at report time"}
    try:
        ps = subprocess.run(["ps", "-axo", "rss=,comm="], capture_output=True, text=True, check=False).stdout
        out["ollama_resident_mb"] = round(sum(int(line.split(None, 1)[0]) for line in ps.splitlines()
                                              if line.strip() and "ollama" in line.split(None, 1)[1]) / 1024)
    except OSError as e:  # the network-deny sandbox also forbids running the setuid `ps`
        out["ollama_resident_mb"] = None
        out["ollama_resident_unavailable"] = f"ps: {e}"
    try:  # Ollama's own account of the loaded model, over loopback
        with urllib.request.urlopen(f"http://{ollama_host}/api/ps", timeout=5) as r:
            out["ollama_loaded_models"] = [{"name": m["name"], "size_mb": round(m["size"] / 2**20),
                                            "size_vram_mb": round(m.get("size_vram", 0) / 2**20)}
                                           for m in json.load(r)["models"]]
    except (OSError, ValueError, KeyError) as e:
        out["ollama_loaded_models"] = f"unavailable: {e}"
    return out


def write_report(report: dict, folder: Path, ollama_host: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    report = {"recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
              "machine": machine(), "memory": memory(ollama_host), **report}
    path = folder / f"offline-proof-{datetime.now().astimezone():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    return path
