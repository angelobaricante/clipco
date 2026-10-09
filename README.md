# Clipcon

**Your clips, in context.**

Clipcon is a local footage assistant for creators. It prepares searchable, source-grounded context from raw A-roll and B-roll on a Mac, then supplies relevant segments to an AI editing agent through MCP.

The approved MVP uses native SwiftUI, a local Python worker, Ollama/Qwen3.5, whisper.cpp, FFmpeg, SQLite, and a lightweight read-only MCP server. It provides footage knowledge; the downstream agent makes edits using its own tools.

## Project status

Planning is complete and implementation has not started. Real inference, native UI behavior, offline operation, and savings still need to be demonstrated. The image below is an approved browser design study with illustrative media, not a running native app.

![Approved macOS workspace direction](docs/design/macos-workspace.jpg)

## Build one task at a time

- [Approved MVP specification](https://github.com/angelobaricante/clipcon/issues/1)
- [Implementation tasks](https://github.com/angelobaricante/clipcon/issues)
- [First task: import one source clip and review real local context](https://github.com/angelobaricante/clipcon/issues/2)
- [Session handoff and tracker guide](docs/TRACKER.md)
- [Native design direction](docs/design/macos-design-notes.md)
- [Domain glossary](GLOSSARY.md)

For a new agent session, ask:

> Work on https://github.com/angelobaricante/clipcon/issues/2. Read AGENTS.md and the parent specification, verify dependencies, and implement the task through its acceptance checks. Record progress and validation in the issue before ending the session.

Later sessions use the next unblocked implementation issue. GitHub issues and their comments are the authoritative work state; this project does not depend on one chat's history.

## Demo boundaries

The initial target is a configured Apple Silicon Mac and English footage. Initial runtime/model installation requires connectivity; useful local inference and index retrieval must then work offline. Codex's own remote inference may require internet. Preserve original footage, measure efficiency fairly, and distinguish live processing from cached context.

Model weights, raw footage, local indexes, and environment-specific caches are kept outside Git. Runnable app/setup instructions will be added as the implementation tasks are completed.
