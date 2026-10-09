"""JSON-lines command interface used by the Clipco app.

Every stdout line is one JSON event: {"event": "progress"|"readiness"|"result"|"error", ...}.
Diagnostics go to stderr.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import roles
from .pipeline import Worker
from .readiness import check, warm_up
from .retrieval import SEARCH_PAGE, Index, default_home
from .speech import WhisperCppSpeech
from .vision import OllamaVision

DEFAULT_WHISPER = Path.home() / ".clipco" / "models" / "ggml-large-v3-turbo.bin"  # multilingual
DEFAULT_VAD = Path.home() / ".clipco" / "models" / "ggml-silero-v5.1.2.bin"  # voice activity detection
DEFAULT_VISION = "qwen3.5:4b-q4_K_M"


def emit(event: str, **payload) -> None:
    sys.stdout.write(json.dumps({"event": event, **payload}) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clipco-worker")
    parser.add_argument("--home", type=Path, default=default_home())
    parser.add_argument("--whisper-model", type=Path,
                        default=Path(os.environ.get("CLIPCO_WHISPER_MODEL", DEFAULT_WHISPER)))
    parser.add_argument("--vad-model", type=Path,
                        default=Path(os.environ.get("CLIPCO_VAD_MODEL", DEFAULT_VAD)))
    parser.add_argument("--speech-language", default=os.environ.get("CLIPCO_SPEECH_LANGUAGE", "auto"),
                        help='whisper language code, e.g. "en" or "tl"; "auto" detects it per clip')
    parser.add_argument("--vision-model", default=os.environ.get("CLIPCO_VISION_MODEL", DEFAULT_VISION))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("readiness")
    sub.add_parser("warmup")
    sub.add_parser("projects")
    sub.add_parser("mcp-status")
    p = sub.add_parser("create-project")
    p.add_argument("--name", required=True)
    p.add_argument("--context", default="")
    def destination(p):  # a Project, or the Footage library alone
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument("--project")
        group.add_argument("--library", action="store_true", help="the Footage library, without a Project")

    p = sub.add_parser("import")
    destination(p)
    p.add_argument("source", type=Path)
    p = sub.add_parser("import-sources", help="import chosen video files and folders into a Project or the library")
    destination(p)
    p.add_argument("source", type=Path, nargs="+", metavar="file-or-folder")
    p = sub.add_parser("remove-clips", help="remove clips from a Project; they stay in the library")
    p.add_argument("--project", required=True)
    p.add_argument("clip_ids", nargs="+")
    p = sub.add_parser("remove-from-library",
                       help="forget sources' saved context everywhere (original files are not touched)")
    p.add_argument("clip_ids", nargs="+")
    p = sub.add_parser("add-to-project", help="add library sources to a Project, reusing their analysis")
    p.add_argument("--project", required=True)
    p.add_argument("clip_ids", nargs="+")
    p = sub.add_parser("delete-project", help="forget a Project; its footage stays in the library")
    p.add_argument("--project", required=True)
    p = sub.add_parser("set-note", help="save the creator's note for a clip in a Project (empty text clears it)")
    p.add_argument("--project", help="defaults to the clip's only Project")
    p.add_argument("--clip", required=True)
    p.add_argument("--text", required=True)
    p = sub.add_parser("set-reuse", help="allow or prevent reuse of sources across projects")
    p.add_argument("--allowed", required=True, choices=["yes", "no"])
    p.add_argument("clip_ids", nargs="+")
    p = sub.add_parser("set-segment-role", help="record the creator's footage role for a Segment")
    p.add_argument("--segment", required=True)
    p.add_argument("--role", required=True, choices=[*roles.ROLES, "suggested"],
                   help='"suggested" clears the correction')
    p = sub.add_parser("set-excluded", help="exclude clips from, or restore them to, default search results")
    p.add_argument("--project", required=True)
    p.add_argument("--excluded", required=True, choices=["yes", "no"])
    p.add_argument("clip_ids", nargs="+")
    p = sub.add_parser("check-sources", help="re-verify originals: mark missing, changed (stale) or restored clips")
    destination(p)
    p = sub.add_parser("retry", help="re-analyse chosen clips from their originals, keeping their IDs and notes")
    destination(p)
    p.add_argument("clip_ids", nargs="+")
    p = sub.add_parser("relink", help="point a clip at the same original file in a new location")
    destination(p)
    p.add_argument("--clip", required=True)
    p.add_argument("source", type=Path)
    p = sub.add_parser("offline-proof",
                       help="with networking off: index one new clip live, search it, and save an evidence report")
    p.add_argument("--project", required=True)
    p.add_argument("--query", action="append", default=[], help="search to run afterwards (repeatable)")
    p.add_argument("--report-dir", type=Path, default=Path.home() / ".clipco" / "evidence")
    p.add_argument("source", type=Path)
    p = sub.add_parser("snapshot")
    destination(p)
    p = sub.add_parser("search", help="search the saved index (reads only; starts no model)")
    p.add_argument("--project")
    p.add_argument("--scope", choices=["project", "library"], default="project")
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=SEARCH_PAGE)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--include-excluded", action="store_true", help="also match clips the creator excluded")
    args = parser.parse_args(argv)
    if getattr(args, "library", False):
        args.project = None

    ollama = OllamaVision(args.vision_model)
    try:
        if args.command == "mcp-status":
            from .mcp_check import connection_status
            emit("result", mcp=connection_status(args.home))
        elif args.command == "search":
            emit("result", search=Index(args.home).search(args.project, args.query, args.limit, args.offset,
                                                             include_excluded=args.include_excluded,
                                                             scope=args.scope))
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
                clip_ids = [worker.store.resolve_clip(c, args.project) for c in args.clip_ids]
                worker.remove_clips(args.project, clip_ids)
                emit("result", removed=clip_ids, project_id=args.project)
            elif args.command == "remove-from-library":
                clip_ids = [worker.store.resolve_clip(c) for c in args.clip_ids]
                emit("result", removed=clip_ids, projects=worker.remove_from_library(clip_ids))
            elif args.command == "add-to-project":
                emit("result", **worker.add_to_project(args.project, [worker.store.resolve_clip(c)
                                                                       for c in args.clip_ids]))
            elif args.command == "set-reuse":
                clip_ids = [worker.store.resolve_clip(c) for c in args.clip_ids]
                worker.store.set_reuse(clip_ids, args.allowed == "yes")
                emit("result", reuse_allowed=args.allowed == "yes", clip_ids=clip_ids)
            elif args.command == "set-segment-role":
                emit("result", segment_id=args.segment, role=worker.store.set_segment_role(
                    args.segment, None if args.role == "suggested" else args.role))
            elif args.command == "delete-project":
                worker.delete_project(args.project)
                emit("result", deleted=args.project)
            elif args.command == "set-note":
                clip_id = worker.store.resolve_clip(args.clip, args.project)
                project = args.project
                if project is None:
                    projects = [m["project_id"] for m in worker.store.memberships(clip_id)]
                    if len(projects) != 1:
                        raise ValueError(f"clip {clip_id} is in {len(projects)} Projects; pass --project")
                    project = projects[0]
                emit("result", note=worker.store.set_note(project, clip_id, args.text), clip_id=clip_id,
                     project_id=project)
            elif args.command == "set-excluded":
                clip_ids = [worker.store.resolve_clip(c, args.project) for c in args.clip_ids]
                worker.store.set_excluded(args.project, clip_ids, args.excluded == "yes")
                emit("result", excluded=args.excluded == "yes", clip_ids=clip_ids)
            elif args.command == "snapshot":
                emit("result", snapshot=worker.snapshot(args.project) if args.project else worker.library_snapshot())
            elif args.command in ("check-sources", "retry"):
                started = time.monotonic()
                progress = lambda stage, detail: emit("progress", stage=stage, **detail)
                outcome = (worker.check_sources(args.project, progress) if args.command == "check-sources"
                           else worker.retry(args.project, [worker.store.resolve_clip(c, args.project)
                                                            for c in args.clip_ids], progress))
                emit("result", **outcome, elapsed=round(time.monotonic() - started, 2))
            elif args.command == "offline-proof":
                from .offline import offline_proof, write_report
                report = offline_proof(worker, args.project, args.source, args.query or ["the main point"],
                                       progress=lambda stage, detail: emit("progress", stage=stage, **detail))
                emit("result", report=report, saved_to=str(write_report(report, args.report_dir, ollama.host)))
                return 0 if report["verdict"]["offline_verified"] else 2
            elif args.command == "relink":
                emit("result", **worker.relink(args.project, worker.store.resolve_clip(args.clip, args.project),
                                               args.source))
            elif args.command in ("import", "import-sources"):
                started = time.monotonic()
                run = worker.import_clip if args.command == "import" else worker.import_sources
                outcome = run(args.project, args.source,
                              progress=lambda stage, detail: emit("progress", stage=stage, **detail))
                emit("result", **outcome, elapsed=round(time.monotonic() - started, 2))
    except Exception as e:  # reported to the app as a structured, displayable error
        print(f"clipco-worker: {type(e).__name__}: {e}", file=sys.stderr)
        emit("error", kind=type(e).__name__, message=str(e))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
