"""JSON-lines command interface used by the Clipcon app.

Every stdout line is one JSON event: {"event": "progress"|"readiness"|"result"|"error", ...}.
Diagnostics go to stderr.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .pipeline import Worker
from .readiness import check, warm_up
from .retrieval import SEARCH_PAGE, Index, default_home
from .speech import WhisperCppSpeech
from .vision import OllamaVision

DEFAULT_WHISPER = Path.home() / ".clipcon" / "models" / "ggml-large-v3-turbo.bin"  # multilingual
DEFAULT_VAD = Path.home() / ".clipcon" / "models" / "ggml-silero-v5.1.2.bin"  # voice activity detection
DEFAULT_VISION = "qwen3.5:4b-q4_K_M"


def emit(event: str, **payload) -> None:
    sys.stdout.write(json.dumps({"event": event, **payload}) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clipcon-worker")
    parser.add_argument("--home", type=Path, default=default_home())
    parser.add_argument("--whisper-model", type=Path,
                        default=Path(os.environ.get("CLIPCON_WHISPER_MODEL", DEFAULT_WHISPER)))
    parser.add_argument("--vad-model", type=Path,
                        default=Path(os.environ.get("CLIPCON_VAD_MODEL", DEFAULT_VAD)))
    parser.add_argument("--speech-language", default=os.environ.get("CLIPCON_SPEECH_LANGUAGE", "auto"),
                        help='whisper language code, e.g. "en" or "tl"; "auto" detects it per clip')
    parser.add_argument("--vision-model", default=os.environ.get("CLIPCON_VISION_MODEL", DEFAULT_VISION))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("readiness")
    sub.add_parser("warmup")
    sub.add_parser("projects")
    sub.add_parser("mcp-status")
    p = sub.add_parser("create-project")
    p.add_argument("--name", required=True)
    p.add_argument("--context", default="")
    p = sub.add_parser("import")
    p.add_argument("--project", required=True)
    p.add_argument("source", type=Path)
    p = sub.add_parser("import-sources", help="import chosen video files and folders into one Project")
    p.add_argument("--project", required=True)
    p.add_argument("source", type=Path, nargs="+", metavar="file-or-folder")
    p = sub.add_parser("remove-clips", help="forget clips' saved context (original files are not touched)")
    p.add_argument("--project", required=True)
    p.add_argument("clip_ids", nargs="+")
    p = sub.add_parser("delete-project", help="forget a Project's saved context (original files are not touched)")
    p.add_argument("--project", required=True)
    p = sub.add_parser("set-note", help="save the creator's note for a clip (empty text clears it)")
    p.add_argument("--clip", required=True)
    p.add_argument("--text", required=True)
    p = sub.add_parser("set-excluded", help="exclude clips from, or restore them to, default search results")
    p.add_argument("--project", required=True)
    p.add_argument("--excluded", required=True, choices=["yes", "no"])
    p.add_argument("clip_ids", nargs="+")
    p = sub.add_parser("snapshot")
    p.add_argument("--project", required=True)
    p = sub.add_parser("search", help="search the saved index (reads only; starts no model)")
    p.add_argument("--project", required=True)
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=SEARCH_PAGE)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--include-excluded", action="store_true", help="also match clips the creator excluded")
    args = parser.parse_args(argv)

    ollama = OllamaVision(args.vision_model)
    try:
        if args.command == "mcp-status":
            from .mcp_check import connection_status
            emit("result", mcp=connection_status(args.home))
        elif args.command == "search":
            emit("result", search=Index(args.home).search(args.project, args.query, args.limit, args.offset,
                                                             include_excluded=args.include_excluded))
        elif args.command == "readiness":
            emit("result", readiness=check(ollama, args.whisper_model, args.vad_model))
        elif args.command == "warmup":
            final = warm_up(ollama, args.whisper_model, args.vad_model, progress=lambda s: emit("readiness", readiness=s))
            emit("result", readiness=final)
        else:
            worker = Worker(args.home, WhisperCppSpeech(args.whisper_model, args.vad_model, language=args.speech_language), ollama)
            if args.command == "projects":
                emit("result", projects=worker.store.projects())
            elif args.command == "create-project":
                emit("result", project=worker.create_project(args.name, args.context))
            elif args.command == "remove-clips":
                worker.remove_clips(args.project, args.clip_ids)
                emit("result", removed=args.clip_ids)
            elif args.command == "delete-project":
                worker.delete_project(args.project)
                emit("result", deleted=args.project)
            elif args.command == "set-note":
                emit("result", note=worker.store.set_note(args.clip, args.text), clip_id=args.clip)
            elif args.command == "set-excluded":
                worker.store.set_excluded(args.project, args.clip_ids, args.excluded == "yes")
                emit("result", excluded=args.excluded == "yes", clip_ids=args.clip_ids)
            elif args.command == "snapshot":
                emit("result", snapshot=worker.snapshot(args.project))
            elif args.command in ("import", "import-sources"):
                started = time.monotonic()
                run = worker.import_clip if args.command == "import" else worker.import_sources
                outcome = run(args.project, args.source,
                              progress=lambda stage, detail: emit("progress", stage=stage, **detail))
                emit("result", **outcome, elapsed=round(time.monotonic() - started, 2))
    except Exception as e:  # reported to the app as a structured, displayable error
        print(f"clipcon-worker: {type(e).__name__}: {e}", file=sys.stderr)
        emit("error", kind=type(e).__name__, message=str(e))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
