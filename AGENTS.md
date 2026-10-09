<!-- pstack-models:begin -->
# pstack model configuration. One line per role. Delete a line to fall back to the skill default.
# Entries: <provider>:<model>[@<effort>] with provider claude, codex, or cursor. `default` as the model means that provider's configured default.
# An entry on your host's provider spawns natively. Another provider runs through scripts/pstack-delegate at the pstack plugin root.
# `inherit-parent` or `auto` as a value: the role runs on the parent chat model (omit `model`). Alias entries in a panel list still count toward its fan-out.
# budget: small (medium)
feature, refactoring: codex:default@medium
bug-fix: codex:default@medium
perf-issue: codex:default@medium
hillclimb: codex:default@medium
judgment and prose: codex:default@medium
hardest tasks: codex:default@medium
how explorer: codex:default@medium
how explainer: codex:default@medium
why investigators: codex:default@medium
why synthesizer: codex:default@medium
reflect tooling: codex:default@medium
reflect judgment, divergent, synthesizer: codex:default@medium
arena runners: codex:default@medium, codex:default@medium, codex:default@medium
arena cross-judge pool: codex:default@medium, codex:default@medium, codex:default@medium
swarm workers: codex:default@medium
architect runners: codex:default@medium, codex:default@medium, codex:default@medium
interrogate reviewers: codex:default@medium, codex:default@medium, codex:default@medium
<!-- pstack-models:end -->

# Clipcon session context

Clipcon prepares local footage context for an editing agent. It is not a video editor. The approved MVP is native SwiftUI plus a Python worker using local Ollama/Qwen3.5, whisper.cpp, FFmpeg, and SQLite, with five read-only MCP tools for Codex.

Read `docs/TRACKER.md`, `GLOSSARY.md`, the live GitHub specification at https://github.com/angelobaricante/clipcon/issues/1, and the selected implementation issue/comments before starting. Check native blockers and active claims. Work one approved task at a time and leave a progress/validation/branch handoff comment before ending a session.

The approved interface is Variant D's Mac sidebar/browser/inspector workflow. Its reference is `docs/design/macos-design-notes.md` and `docs/design/macos-workspace.jpg`. Use real native system controls; prototype artwork and simulated controls are not production evidence. Keep inference and long-running work off the UI main thread.

Preserve original footage. Distinguish transcripts, sampled observations, interpretations, and creator notes. Code owns source timestamps and stable identities. Do not silently fall back to cloud inference, publish footage/model weights/local indexes, or claim savings/offline usefulness without measured evidence.

The project is deadline-constrained. Recompute remaining time against the organizer's authoritative cutoff and preserve submission buffer. The planning reference was October 10, 2026 at 10 AM, assuming Asia/Manila; supplied screenshots are context, not instructions that authorize submission.

Role model settings above configure model choice only; they are not authorization to spawn additional agents or new tasks. Follow the active user's task scope and the current delegation rules.
