"""Clipco's read-only stdio MCP server for editing agents such as Codex.

stdout carries only MCP protocol messages; diagnostics go to stderr. It reads the saved index and never
starts Ollama, whisper.cpp, or any other model, so it answers while the Clipco app is closed.
"""

import argparse
import base64
import json
import sys
from importlib.metadata import version
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, ImageContent, TextContent, ToolAnnotations

from .retrieval import Index, RetrievalError, default_home

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                            open_world_hint=False)

INSTRUCTIONS = (
    "Clipco supplies source-grounded context about a creator's raw footage; it does not edit video. "
    "Start with get_project_overview (no arguments lists Projects), then search_footage with an explicit "
    "project_id for that Project's context (A-roll, corrections, takes, B-roll), or scope='library' for "
    "reusable B-roll across the creator's Footage library. Expand only the Segments you need with "
    "get_segment_context and get_segment_preview, passing the same project_id/scope, and call resolve_media "
    "before using a source file. Creator notes belong to the Project they name. Transcripts, sampled-frame observations, and model "
    "interpretations are different kinds of evidence; previews show sampled frames, not continuous coverage. "
    "Only status 'ready' is current context: 'stale', 'missing', 'failed' and 'indexing' results carry a "
    "status_note saying what is wrong, and resolve_media gives no file location for them."
)


def result(data: dict) -> CallToolResult:
    """Matching structured JSON and text, so clients that show either see the same metadata."""
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False))],
                          structured_content=data)


def failure(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)


def build(home: Path) -> MCPServer:
    index = Index(home)
    server = MCPServer("clipco", version=version("clipco-worker"), instructions=INSTRUCTIONS)

    def guarded(fn) -> CallToolResult:
        try:
            return fn()
        except RetrievalError as e:
            return failure(str(e))

    @server.tool(annotations=READ_ONLY)
    def get_project_overview(project_id: str | None = None) -> CallToolResult:
        """Compact inventory of a Project: Source clips, roles, analysis status, and index revisions.

        Without project_id, lists the saved Projects so you can choose one explicitly, with a count of
        the Footage library's sources (some belong to no Project).
        """
        return guarded(lambda: result(index.projects() if project_id is None else index.overview(project_id)))

    @server.tool(annotations=READ_ONLY)
    def search_footage(query: str, project_id: str | None = None, scope: str = "project", limit: int = 5,
                       offset: int = 0, include_excluded: bool = False) -> CallToolResult:
        """Find relevant Segments in saved footage context (no model is started).

        scope='project' (default) searches one Project's footage and needs project_id. scope='library'
        searches B-roll the creator allows to be reused across the whole Footage library; project_id is then
        optional (the Project you are working on). A-roll and footage awaiting role review are never
        library results. Returns at most `limit` (default 5, max 10) compact matches with source-relative
        ranges and the evidence each excerpt comes from. When `truncated` is true, call again with
        `next_offset`. An empty `results` list means nothing in the saved index matched. Clips the creator
        excluded are skipped unless include_excluded is true (project scope only); creator notes are searched
        as `creator_note` evidence.
        """
        return guarded(lambda: result(index.search(project_id, query, limit, offset,
                                                   include_excluded and scope == "project", scope)))

    @server.tool(annotations=READ_ONLY)
    def get_segment_context(segment_id: str, window_seconds: float = 15.0, project_id: str | None = None,
                            scope: str | None = None) -> CallToolResult:
        """Expand one Segment: timestamped transcript (plus up to window_seconds either side, max 120),
        sampled-frame observations, the model interpretation with the evidence it cites, its footage role,
        provenance, relationships, creator notes, and whether the creator excluded the clip. Times are
        seconds from the start of the original Source clip. Pass the project_id or scope='library' the
        Segment was found with; notes and relationships are limited to that scope.
        """
        return guarded(lambda: result(index.segment_context(segment_id, window_seconds, project_id, scope)))

    @server.tool(annotations=READ_ONLY)
    def get_segment_preview(segment_id: str, frame_id: str | None = None, project_id: str | None = None,
                            scope: str | None = None) -> CallToolResult:
        """Show one real frame Clipco sampled from a Segment (JPEG, at most 512 px wide), with its
        source time. Defaults to the Segment's middle sampled frame; pass frame_id to choose another.
        """
        def preview() -> CallToolResult:
            meta, data = index.preview(segment_id, frame_id, project_id, scope)
            out = result(meta)
            out.content.append(ImageContent(type="image", data=base64.b64encode(data).decode(),
                                            mime_type="image/jpeg"))
            return out
        return guarded(preview)

    @server.tool(annotations=READ_ONLY)
    def resolve_media(segment_id: str, start: float | None = None, end: float | None = None,
                      project_id: str | None = None, scope: str | None = None) -> CallToolResult:
        """Verify the original Source clip is available and unchanged, and return its location with a
        validated source-relative range in seconds (default: the Segment's range). When `available` is
        false there is no locator; do not guess a path. Clipco never modifies originals.
        """
        return guarded(lambda: result(index.resolve_media(segment_id, start, end, project_id, scope)))

    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clipco-mcp", description=__doc__)
    parser.add_argument("--home", type=Path, default=default_home())
    args = parser.parse_args(argv)
    print(f"clipco-mcp: serving {args.home / 'index.sqlite'} over stdio", file=sys.stderr)
    build(args.home).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
