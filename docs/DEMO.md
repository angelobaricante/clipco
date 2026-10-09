# Demo, evidence, and submission readiness (task #7)

This page lists what has been measured, how to reproduce it, and what still needs the creator. Nothing here has been submitted or published on the creator's behalf. Preparing these materials is not a submission.

## Evidence so far

| Claim | Status | Evidence |
| --- | --- | --- |
| Local indexing and search with the internet unreachable | **Process-level proof done.** Machine-level run (Wi-Fi off) is still for the creator to do. | [`evidence/offline-proof-sandbox-2026-10-10.json`](evidence/offline-proof-sandbox-2026-10-10.json) |
| Codex retrieves footage context through MCP | Done in #3/#4 (real Codex sessions, `codex-cli 0.162.0-alpha.2`) | Issues #3, #4 |
| Correction-plus-B-roll query through Codex MCP | **Not demonstrated.** No corpus with a spoken correction has been recorded yet. | — |
| Discovery tokens: direct inspection vs. MCP | **Harness built, not run.** The creator chose not to spend Codex credits or send footage yet. | `clipcon-benchmark` (below) |
| Warm retrieval latency | Measured: 1–5 ms per MCP tool call | Below |

No token savings are claimed until the benchmark has been run and its answers graded.

### Offline proof, process level (2026-10-10 00:01 Asia/Manila)

`scripts/clipcon offline-proof --sandbox` stopped Ollama and restarted it cold. Both Ollama and the worker ran inside a macOS `sandbox-exec` profile ([`scripts/offline.sb`](../scripts/offline.sb)) that denies every network connection except loopback. The clip was imported into a fresh, empty index.

- **Offline conditions:** the worker tried TCP connections to `1.1.1.1:443`, `8.8.8.8:53` and `captive.apple.com:80`. All three were refused (`PermissionError: Operation not permitted`). Loopback to Ollama worked.
  - This is a process-level proof. The Mac itself was still online, because this agent session needs the network.
  - The profile allows Unix sockets, so name lookups through the system resolver may still have worked. Only connections were blocked.
  - The machine-level run below is the stronger proof.
- **Live inference:** `611D69BD-…MP4` (69.9 s, HEVC 1440×2560, English) was analysed live: `live_inference: true`, `ready`, 3 Segments.
  - Total import time, including the cold model load: **30.1 s**.
  - The same footage had been indexed earlier in the creator's main index. The proof index started empty, so nothing was reused.
- **Search:** "DJI camera" and "presenter talking to camera" each returned the clip's Segments locally, in 0.3–0.4 ms.
- **Models:**
  - speech: whisper.cpp `ggml-large-v3-turbo.bin` with Silero VAD v5.1.2;
  - vision: `qwen3.5:4b-q4_K_M` on Ollama, digest `d8b0f5e9…`.
- **Memory:**
  - worker: at most 1,974 MB. This is an upper bound: the worker's peak plus its largest child's (whisper-cli/ffmpeg) peak, which may not have happened at the same moment. The JSON field from this run is named `worker_plus_largest_child_peak_mb`;
  - Ollama's loaded model: 3,254 MB, all on the GPU.
  - Ollama's process resident size could not be read inside the sandbox (`ps` is blocked there), and the report says so.
- **Originals:** the SHA-256 of the source was identical before and after (`5112fa90…`).

### Warm retrieval (2026-10-10, creator's real index, read-only)

[`scripts/measure-mcp-latency.py`](../scripts/measure-mcp-latency.py) calls the real stdio MCP server the way Codex does. Output: [`evidence/warm-retrieval-2026-10-10.txt`](evidence/warm-retrieval-2026-10-10.txt).

- Server start plus handshake took 241 ms (606 ms in an earlier run).
- Warm calls, 5 repeats each:

| Tool | Latency |
| --- | --- |
| `get_project_overview` | 1.0–4.7 ms |
| `search_footage` | 1.5–2.5 ms |
| `get_segment_context` | 1.0 ms |
| `get_segment_preview` | 1.3 ms |
| `resolve_media` | 1.0 ms |

- Result sizes: `search_footage` returned 1.2–7.9 K characters, and `get_segment_preview` returned 33 K characters (one JPEG frame, base64). Characters are not tokens.

Against the spec's provisional targets:
- **Under 2 s warm retrieval:** met on this M5/24 GB Mac.
- **Under 10 min demo indexing:** not measured on a demo corpus. One 70 s clip took 30 s cold.
- Neither result establishes support for lower-memory Macs.

## Reproduce

### Machine-level offline proof (creator)

1. While online, run `scripts/clipcon start` once so the dependencies and models are cached.
2. Create a Project for the proof. To keep your main index untouched, point the scratch commands at a separate home:
   ```sh
   export CLIPCON_HOME=~/clipcon-offline-proof
   worker/.venv/bin/clipcon-worker create-project --name "Offline proof"   # note the prj_… id
   ```
3. Turn the Mac's networking off: Wi-Fi off and Ethernet unplugged. Optionally restart the Mac.
4. Run the proof on a clip that has never been indexed in that home:
   ```sh
   scripts/clipcon offline-proof --project prj_… --query "what you say in the clip" /path/to/new-clip.mov
   ```
5. The command refuses if any probe target answers, so a connected Mac cannot pass. It prints the verdict and saves a JSON report under `~/.clipcon/evidence/`. Exit code 0 means verified, 2 means the run finished but wasn't verified (it lists the reasons), and 1 means it refused.
6. Still offline, run `scripts/clipcon start` (everything it uses should already be cached; note it if anything fails) and review the clip in the app. Take the screenshots now.
7. Turn networking back on before the Codex handoff. Codex's own inference needs internet; do not claim Codex works offline.

`--sandbox` gives the process-level variant shown above, without turning the Mac offline.

### Discovery benchmark (creator-authorized; sends footage to OpenAI and spends Codex credits)

- **Baseline route:** Codex inspects the originals directly (filenames, `ffprobe`, sampled frames, any transcription it can run). This sends frames and transcripts to OpenAI.
- **MCP route:** Codex can use Clipcon's MCP server.
- **Same conditions on both routes:** same prompt, same model, same sandbox, same footage folder (left read-only), plus a scratch working folder. All other configured MCP servers are disabled on both routes.

1. Copy [`evidence/benchmark-queries.example.json`](evidence/benchmark-queries.example.json). Write the three discovery requests for your corpus, and fill in each request's expected file and time range after watching the footage.
2. Run:
   ```sh
   worker/.venv/bin/clipcon-benchmark --send-footage-to-codex --model <the same model for both routes> \
     --footage /path/to/project/originals --queries my-queries.json
   ```
   - The command refuses to run without `--send-footage-to-codex`.
   - Each route runs requests 1–3 in one Codex session, then asks request 1 again in the same session. That last row shows conversation/prompt-cache reuse. It is not a fresh-session repeat.
   - Codex's sandbox does not stop the baseline from reading Clipcon's own index. The report counts any shell command that touches it (`Index reads` column) and warns. A baseline that read the index is not a clean comparison.
3. The JSON report records, per request, from Codex's own session log:
   - input, cached and uncached input tokens, and output and reasoning tokens;
   - model requests, and tool calls by tool;
   - failed tool calls (retries);
   - tool-result text characters and images returned;
   - wall time.
4. Unavailable categories are listed in the report. Codex's log does not separate billed image tokens or tool-result tokens. Do not convert characters into tokens.
5. Grade each answer against `expected` by hand. A route that finds the wrong Segment does not count as a saving.
6. One-time indexing cost is separate: use the import time and memory from the offline proof. Downstream editing and rendering are outside the comparison.
7. Report the measured outcome, even if it is under the 50% target. Subscription credits are not API costs. A dollar figure needs then-current API rates for the exact model.

## Tested setup

| Item | Version | License |
| --- | --- | --- |
| Hardware | Mac17,2, Apple M5, 24 GB | — |
| macOS / Xcode | 26.5.1 / 26.3 (17C529) | — |
| FFmpeg (Homebrew) | 8.1.1, built `--enable-gpl --enable-version3` | GPL-3.0-or-later |
| whisper.cpp (Homebrew `whisper.cpp`, formerly `whisper-cpp`) | 1.9.5 | MIT |
| Speech model | `ggml-large-v3-turbo.bin` (1.62 GB) | MIT (OpenAI Whisper weights) |
| Voice activity model | `ggml-silero-v5.1.2.bin` | MIT (Silero VAD) |
| Ollama (Homebrew) | 0.40.2, loopback only, `OLLAMA_NO_CLOUD=1` | MIT |
| Vision model | `qwen3.5:4b-q4_K_M`, digest `d8b0f5e9760c…` | Apache-2.0 (from `ollama show --license`) |
| Python / MCP SDK | 3.14.3 / `mcp` 2.3.0 (protocol `2026-07-28`) | MIT (MCP SDK) |
| uv / xcodegen | 0.11.28 / 2.45.4 | — |
| Codex client used for MCP checks | `codex-cli 0.162.0-alpha.2` (bundled with the ChatGPT app) | — |

Setup and run instructions: [README](../README.md).

## Known quality limits

- Visual context comes from sampled frames, not continuous video understanding. Actions between samples can be missed.
- Tagalog/Taglish transcription quality is measured only on the creator's own site-visit footage. A 3.4 s clip was misdetected as Russian, and a 12.8 s clip as Spanish.
- Speech-to-camera role detection depends on the vision model. In the site-visit Project, clips with mostly speech were labelled B-roll because nobody faces the camera.
- No corpus with a spoken correction or repeated take has been recorded yet. Correction detection has not been shown on real footage.
- Recipe/model changes are detected when the app checks sources, not live through MCP (see [analysis-recipe.md](analysis-recipe.md)).
- Opening a second window with File ▸ New Clipcon Window shows an empty browser (found in #6).

## Disclosures

- **AI coding tools:**
  - OpenAI Codex (ChatGPT app) was used to plan the specification and create the issues.
  - Anthropic Claude Code was used to implement tasks #2–#7.
  - Commits carry co-author lines where Claude Code made them.
- **Reused assets:**
  - The approved interface direction came from a throwaway browser prototype (`prototype/footage-review-flow`). The prototype is not shipped.
  - Test fixtures are generated with FFmpeg test sources.
  - No third-party footage is in the repository.
  - The creator should confirm there is nothing else to disclose under the hackathon's rules.
- **Inference runs locally:** core inference (speech, vision) runs on the Mac with no cloud fallback. Codex, the downstream agent, uses OpenAI's cloud.

## Demo path (about 3 minutes)

1. **Offline (networking off):** show the Wi-Fi menu turned off. Run `scripts/clipcon offline-proof` on a new clip, then show the verdict line.
2. **App:** open the Project. Show the new clip ready, alongside the cached ones. Say clearly that the other clips were indexed earlier.
3. **Review:** select a clip and play it (double-click). The transcript follows playback. Add a creator note, then exclude a clip.
4. **Online again:** in Codex, ask the discovery request. Show the `search_footage` → `get_segment_context` → `resolve_media` calls and the returned source ranges.
5. **Recovery:** move an original away. It shows "Original not found", then **Locate…** brings it back (#6).
6. **Numbers:** show the benchmark table, only if it has been run and graded.

## Submission checklist (creator)

- [ ] Confirm the organizer's authoritative cutoff and time zone (planning assumption: 2026-10-10 10:00 Asia/Manila). Keep the buffer.
- [ ] Machine-level offline proof run, with the report saved and screenshot/recording taken.
- [ ] Codex correction-plus-B-roll query recorded, if a correction corpus exists. Otherwise, state that it wasn't demonstrated.
- [ ] Benchmark run and graded, or explicitly reported as not run.
- [ ] Screenshots: workspace, inspector, offline verdict, Codex tool calls.
- [ ] Short screen recording of the demo path.
- [ ] Repository check: no raw footage, model weights, local indexes or personal paths committed (`git ls-files`, plus a review of `docs/evidence/`).
- [ ] README states what was and wasn't demonstrated.
- [ ] Disclosures above confirmed against the hackathon rules.
- [ ] Submit once, yourself. Single-submission constraint: check everything before submitting.
