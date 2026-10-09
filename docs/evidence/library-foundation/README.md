# Library foundation evidence (issue #16), 2026-10-10 Asia/Manila

Agent-verified on the M5/24 GB development Mac. No claim here comes from the creator, and none extends to other hardware.

## Fixture checks (orchestration only)

`cd worker && uv run pytest -q` passed 64 tests, with 3 deselected. Seven of them are in `tests/test_library.py`. They run the worker entry points and check the results through the real stdio MCP server. Covered:

- Migration of an index written by the released legacy worker (commit 6cde551), not a hand-made schema.
- Membership reuse with no inference.
- Notes and exclusions scoped to each Project.
- Reuse permission.
- Mixed-recording Segment roles and corrections.
- Library-only import and duplicate grouping.
- Remove from Library racing an active analysis.
- Transcript lines bounded by a measured silence.

The speech and vision responses in these tests are recorded or scripted, so they prove orchestration but not model quality.

`uv run pytest -q -m real` passed 2 tests and skipped 1.

## Migrating a copy of the real local index

A `.backup` copy of `~/Library/Application Support/Clipcon/index.sqlite` was migrated by running `clipcon-worker --home <copy> projects`. The copy had 3 Projects, 12 clips, 32 Segments, 1 note and 12 relationships. After migration it had 12 memberships, 1 note, 32 Segments and 12 re-derived relationships, with statuses unchanged (2 ready, 10 stale). Every Segment was marked `needs_review` with its legacy whole-clip basis. No inference ran.

For all 32 Segments, `segment_context` from the legacy code before migration matched the new code after migration on these fields:

- transcript
- observations
- interpretation
- exclusion
- status
- revision
- notes
- relationships
- project

Result: 0 differences. The creator's real index was not migrated. It is still in the legacy schema, and its running app instance was not touched.

## Real-model mixed recording

`mixed-site-visit.mp4` was composed with FFmpeg in the session scratchpad from the creator's own footage. The originals' SHA-256 hashes were unchanged afterwards. The 50-second recording has three parts:

| Range | Content |
| --- | --- |
| 0–20 s | Talking head from `611D69BD…MP4` |
| 20–35 s | Silent cutaway from `IMG_6188.MOV` |
| 35–50 s | `IMG_6189.MOV` with narration from `611D…` at 20–35 s |

Runtime: whisper.cpp `ggml-large-v3-turbo.bin` with Silero VAD v5.1.2, and Ollama 0.40.2 `qwen3.5:4b-q4_K_M` (digest `d8b0f5e9760c`), recipe 7. The import took 20.6 s.

- **First run, before the silence bound:** whisper.cpp stretched one 13-word line over 6.43–37.8 s. The cutaway was absorbed into a speech Segment, and every Segment was suggested as A-roll.
- **With measured silence (FFmpeg `silencedetect`, −45 dB, at least 10 s; measured silence 20.0–35.0 s):** the Segments were 0–20 s A-roll (92% speech, facing camera), 20–37.8 s **B-roll** (0% speech; the frames show a laptop editing screen), and 37.8–50 s A-roll.
- **Limitation:** the last Segment is narration over another person at a desk. The model judged that person to be facing the camera, so the suggestion is wrong. The creator's correction to B-roll is stored separately (`suggested a-roll, creator b-roll`), and that Segment then appears in library search. Before the correction, library expansion refused it as A-roll.

## Native app

The Debug build of `Clipcon.app` was launched with `open -n --env CLIPCON_HOME=<scratch home>` and `-ClipconAutomationReview`. The automation calls the same model functions as the inspector's reuse switch (`-ClipconAutomationReuse`) and its Segment role menu (`-ClipconAutomationRole`).

- **Run 1:** reuse turned off and the correction cleared.
- **Run 2:** reuse turned on and Segment 3 set to B-roll. MCP library search then returned both B-roll Segments, with both Projects as origins.

The screenshot `app-inspector-shared-source.png` shows the real native controls: the reuse switch, Segment roles, the "Also in" list of the shared source, and the per-Segment role menu. The automation invoked these controls programmatically; it did not click them.
