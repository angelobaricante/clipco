# Clipcon

**Your clips, in context.**

Clipcon is a local footage assistant for creators. It prepares searchable, source-grounded context from raw A-roll and B-roll on a Mac, then supplies relevant segments to an AI editing agent through MCP.

The approved MVP uses native SwiftUI, a local Python worker, Ollama/Qwen3.5, whisper.cpp, FFmpeg, SQLite, and a lightweight read-only MCP server. It provides footage knowledge; the downstream agent makes edits using its own tools.

## Project status

Task #2 (one real clip through local analysis and native review) is in progress. Real inference, native UI behavior, offline operation, and savings still need to be demonstrated. The image below is an approved browser design study with illustrative media, not a running native app.

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

The initial target is a configured Apple Silicon Mac with English and Tagalog/Taglish footage. Initial runtime/model installation requires connectivity; useful local inference and index retrieval must then work offline. Codex's own remote inference may require internet. Preserve original footage, measure efficiency fairly, and distinguish live processing from cached context.

Model weights, raw footage, local indexes, and environment-specific caches are kept outside Git.

## Run the current slice (task #2: import one clip)

Verified on an M5 Mac (24 GB) with macOS 26.5.1 and Xcode 26.3. These are one-time setup steps and need internet:

```sh
brew install ffmpeg ollama whisper-cpp uv xcodegen
mkdir -p ~/.clipcon/models ~/.clipcon/logs
# Multilingual speech (English, Tagalog, Taglish), ~1.6 GB
curl -L -o ~/.clipcon/models/ggml-large-v3-turbo.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin
# Local Ollama: loopback only, cloud features disabled
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=1 ollama serve > ~/.clipcon/logs/ollama.log 2>&1 &
ollama pull qwen3.5:4b-q4_K_M
(cd worker && uv sync)
```

Run the app:

```sh
cd app && xcodegen generate && open Clipcon.xcodeproj   # then Run (⌘R)
```

Click **Import** (⇧⌘I), name the Project, describe the intended video, choose a clip, then click **Analyze**. Originals are read but never modified. The index and sampled frames live in `~/Library/Application Support/Clipcon/`.

Tests:

```sh
cd worker
uv run pytest                 # behavioral import/readiness checks (real FFmpeg, recorded inference)
uv run pytest -m real -s      # real whisper.cpp + Ollama smoke test; prints a timing/model report
```

Speech language is detected per clip (`CLIPCON_SPEECH_LANGUAGE=auto`); force it with `en` or `tl`. To fall back to the smaller English-only model, download `ggml-small.en.bin` and set `CLIPCON_WHISPER_MODEL=~/.clipcon/models/ggml-small.en.bin`. Tagalog/Taglish quality is only as good as measured on real footage; run `CLIPCON_TAGALOG_CLIP=/path/clip.mp4 uv run pytest -m real -s -k tagalog`.

The worker CLI is also usable directly: `uv run clipcon-worker readiness|warmup|projects|create-project|import|snapshot`.
