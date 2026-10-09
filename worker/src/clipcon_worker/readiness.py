"""Readiness of the local analysis stack, with actionable setup guidance.

States: tools_missing, service_unavailable, model_missing, cold (installed, not loaded),
loading, ready, inference_failed. The app adds worker_unavailable when it cannot run the worker.
"""

import shutil
from collections.abc import Callable
from pathlib import Path

from .vision import InferenceError, ServiceUnavailable

TOOLS = ("ffmpeg", "ffprobe", "whisper-cli")


def check(ollama, whisper_model: Path, which: Callable = shutil.which) -> dict:
    base = {"vision_model": ollama.model, "speech_model": str(whisper_model)}
    missing = [t for t in TOOLS if not which(t)]
    if missing:
        formulas = sorted({"whisper-cpp" if t == "whisper-cli" else "ffmpeg" for t in missing})
        return {**base, "state": "tools_missing", "detail": f"Not found on PATH: {', '.join(missing)}",
                "guidance": f"Install {', '.join(missing)} with Homebrew: brew install {' '.join(formulas)}"}
    try:
        version = ollama.version()
        installed = ollama.installed_models()
        loaded = ollama.loaded_models()
    except ServiceUnavailable as e:
        return {**base, "state": "service_unavailable", "detail": str(e),
                "guidance": "Start the local Ollama service on loopback with cloud features disabled: "
                            "OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=1 ollama serve"}
    base["ollama_version"] = version
    if ollama.model not in installed:
        return {**base, "state": "model_missing", "detail": f"{ollama.model} is not installed in Ollama",
                "guidance": f"While online, run: ollama pull {ollama.model}"}
    base["vision_digest"] = installed[ollama.model]
    if not Path(whisper_model).exists():
        return {**base, "state": "model_missing", "detail": f"Speech model not found at {whisper_model}",
                "guidance": f"While online, download {Path(whisper_model).name} from "
                            f"https://huggingface.co/ggerganov/whisper.cpp to {whisper_model}"}
    if ollama.model in loaded:
        return {**base, "state": "ready", "detail": f"{ollama.model} is loaded", "guidance": ""}
    return {**base, "state": "cold", "detail": f"{ollama.model} is installed but not loaded",
            "guidance": "Load the model before analysis; the first load can take a minute."}


def warm_up(ollama, whisper_model: Path, which: Callable = shutil.which,
            progress: Callable[[dict], None] = lambda s: None) -> dict:
    current = check(ollama, whisper_model, which)
    if current["state"] != "cold":
        return current
    progress({**current, "state": "loading", "detail": f"Loading {ollama.model}…", "guidance": ""})
    try:
        ollama.warm_up()
    except InferenceError as e:
        return {**current, "state": "inference_failed", "detail": str(e),
                "guidance": "Check ~/.clipcon/logs/ollama.log or restart Ollama, then retry."}
    return check(ollama, whisper_model, which)
