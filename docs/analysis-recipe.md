# Analysis recipe and cache identity

Clipco reuses saved footage context when a Source clip and the analysis configuration are unchanged. It re-runs speech and vision inference only when one of the inputs below changes.

## Cache identity (per Source clip)

`analysis_key = sha256(json({source, recipe, speech, vision}, sort_keys))`, where:

| Input | Value | Source |
| --- | --- | --- |
| `source` | SHA-256 of the file's bytes | `pipeline.fingerprint` |
| `recipe` | `pipeline.RECIPE` (version, segment target, frames per segment, frame cap, frame width) | code |
| `speech` | whisper.cpp model filename and byte size, language setting, prompt, context limit, VAD model | `WhisperCppSpeech.identity` |
| `vision` | Ollama model tag and installed digest | `OllamaVision.identity` |

A ready clip whose size and modification time match the indexed values keeps its saved fingerprint instead of being rehashed. MCP applies the same check live on every read, so a moved or edited original is reported `missing` or `stale` and gets no locator before Clipco re-checks. Checking sources (when a Project opens, or **Clip ▸ Check Original Files**) hashes only originals whose size or modification time differ. Identical content makes the clip `ready` again. Different content, or a different recipe or model, marks it `stale` until it is re-analysed. A re-analysis of a failed, stale or missing clip reuses its saved context without inference when the content and settings still match. If any input differs, the clip keeps its identity (`clip_id`) and is re-analysed into a new revision. The new revision publishes atomically, replacing the old Segments in one transaction.

Relationships (Spoken correction, Repeated take, suggested supporting B-roll) are derived in code from the published Segments (`relationships.py`). They are recomputed inside every publish transaction. When the rules' `VERSION` changes, the store recomputes them for every Project the next time it opens. No model is involved, so re-deriving them never re-runs inference.

## Current recipe

- `RECIPE` version 6: about 30 s Segments with boundaries between transcript lines; 10 s Segments for clips without speech; 2 sampled frames per Segment (1 when a clip would exceed 24 frames); frames 512 px wide. The vision model describes only what the frames show and the transcript says. It does not receive the Project description, which reaches agents through `get_project_overview` instead. With no speech detected, it is told not to describe anyone as speaking or explaining.
- Speech: whisper.cpp `ggml-large-v3-turbo.bin`, language auto-detected per clip. Only audio that Silero VAD (`ggml-silero-v5.1.2.bin`, sha256 `29940d98d42b91fbd05ce489f3ecf7c72f0a42f027e4875919a28fb4c04ea2cf`) detects as voice is transcribed. Without VAD, whisper invented "Konec." and "I don't know how much it is…" over the creator's silent B-roll.
- Role: a clip is suggested as A-roll when speech covers at least half its duration **and** the vision model reports a person facing the camera, addressing the viewer, in at least half of its speaking Segments. Otherwise it is B-roll. The clip's `role_basis` records both measurements.
- Vision: Ollama `qwen3.5:4b-q4_K_M`, digest `d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04` (Ollama 0.40.2).

The recipe that passes the three discovery queries on the agreed tutorial corpus will be recorded here once that corpus is indexed (#4).

## Known limitation

Computing `vision` asks the local Ollama service for the installed digest. Ollama is not asked to load the model. If Ollama is not running, the digest is empty, and a model with the same name is treated as unchanged rather than stale. A changed recipe or model is detected when Clipco checks sources, not live through MCP: until the app re-checks, MCP still reports those clips `ready`.
