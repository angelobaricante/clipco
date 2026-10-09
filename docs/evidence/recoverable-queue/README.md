# Recoverable queue, Project creation and drops evidence (issue #18), 2026-10-10 Asia/Manila

The agent checked these on the M5/24 GB development Mac. **The creator has not hand-tested any of it.** All runs used scratch Clipco homes. The creator's real index was never opened for writing, and the original files were only read: their SHA-256 hashes before and after the real runs match.

## Fixture checks (orchestration and lifecycle)

`cd worker && uv run pytest -q`: 75 passed, 3 deselected. `uv run pytest -q -m real`: 2 passed, 1 skipped.

`tests/test_queue.py` drives `JobQueue` and the `clipco-worker` CLI at the worker entry point, and checks the results through the real stdio MCP server. It covers:

- **Registration:**
  - Mixed drops register valid footage at once as `pending`, without models or a running service.
  - Overlapping and repeated items become one clip.
  - Unsupported and inaccessible items are summarized.
  - Dropping the same footage twice does not queue the same work twice.
- **Missing setup:** jobs become `waiting` with the readiness detail. Nothing is published and nothing is substituted.
- **Sequential execution:**
  - Exactly one job is active at a time.
  - Work appended mid-run goes to the destination bound when it was queued.
  - One failure leaves the others completed.
  - Retrying a failure re-describes only that clip.
- **Pause:** the active clip finishes and nothing new starts. Resume continues.
- **Cancel:**
  - A queued job is cancelled without touching footage.
  - An active job publishes nothing and leaves no orphaned frames. Its clip is left `failed` with a "cancelled" explanation and can be retried.
  - A `cancel` from another process stops the active job's child process (no orphan) within seconds.
- **Crash and restart:** a crash leaves the job `active`. On restart, `reconcile` marks that work `interrupted` and returns clips to their prior state. Nothing runs until `resume`, and completed analysis is not repeated.
- **Quit (SIGTERM):** the active job's work is contained and the job is left `interrupted`.
- **Removal from the library:**
  - The source's queued jobs are cancelled at once and its active job is asked to stop.
  - A late publisher cannot bring the removed context back: MCP search and overview never show it, and its frame cache is gone.
- **Re-analysis and tone reading:** both are queued jobs that reuse cached evidence (no new descriptions).

The vision and speech responses in these tests are recorded or scripted, so they prove orchestration only.

## Real models at the CLI entry point

Runtime: Ollama 0.40.2 with `qwen3.5:4b-q4_K_M` (digest `d8b0f5e9760c`), whisper.cpp `ggml-large-v3-turbo` with Silero VAD.

Real footage: two iPhone clips (15.8 s and 27.1 s) and one DJI clip (19.3 s), reached through a drop folder of symlinks. The folder also held a nested subfolder, a `notes.txt` file, an overlapping file argument, and a missing path.

`cli-lifecycle-real.sh` / `.txt`:

- **Enqueue:** 3 jobs were registered. `notes.txt` was skipped as unsupported and the missing path as inaccessible.
- **Cancel during transcription:** cancelling the active job (DJI clip) from a second process took effect in **0.4 s**. Its `whisper-cli` child was gone (a new PID belongs to the next job), and the clip was not published.
- **Pause:** the active clip completed and the runner exited.
- **Retry:** the cancelled DJI job completed after a retry was queued while another runner was active.
- **Script defect (disclosed):** the script's first SIGTERM step signalled a shell-function subshell, not Python. That runner went on to finish all work; it never reached the quit path.

`cli-quit-resume-real.sh` / `.txt` repeats the quit step correctly:

- **SIGTERM during transcription:** the runner exited 0 and no `whisper-cli`/ffmpeg process was left. The active job became `interrupted`; the next stayed `queued`.
- **Relaunch:** `reconcile` marked both `interrupted`, and `run-queue` alone ran nothing.
- **Resume:** both completed in 78 s.

## Native app (`AutomationRun.queue`, real models, scratch `CLIPCO_HOME`)

The debug harness calls the same AppModel methods as the controls:

- a Finder drop (`drop`)
- New Project's Create (`createProject` + `enqueue`)
- the Activity popover's Pause, Resume and Cancel

Report: `app-queue-report.json`.

- **Empty workspace:**
  - The drop opened New Project, suggesting the dropped folder's name ("drop"); see `app-new-project-from-drop.png`.
  - Create made the Project without loading anything. 3 clips were queued; the notice read "1 skipped (unsupported): notes.txt".
- **Destinations:**
  - Opening another Project while work was queued kept every job bound to "drop".
  - A drop on the Reusable B-roll view queued to the library.
- **Controls:**
  - Pause while a clip was active: it finished, the runner stopped, and the rest stayed queued.
  - Cancelling the queued library job removed it.
  - Resume started the next clip within 1.5 s (the Resume call itself took 0.10 s).
- **Responsiveness:**
  - Search answered in **0.05 s** while a clip was analysed.
  - The slowest queue refresh took **0.32 s**.
  - The worst main-thread stall was **290 ms**, across the whole 120 s run of 3 real clips.

Defects found and fixed during these runs:

1. `Process.waitUntilExit()` on a cooperative thread could hang after the worker exited. The app now awaits the termination handler.
2. `FileHandle.bytes` reads queued behind the runner's quiet pipe. Searches waited up to 8.5 s and queue refreshes 19 s. Each process now gets its own readability-handler line reader.
3. A Resume that arrived while the runner was exiting was dropped. It is now remembered.

Not demonstrated:

- **Hand testing:** nothing was hand-dragged from Finder or clicked by hand. Drops, popover buttons and keyboard focus need the creator's manual check.
- **Activity popover:** it did not present when the app was launched in the background by automation, so it has no capture.
- **Screenshot withheld:** the post-run browser capture shows real footage frames, so it is not committed.
- **Edge conditions:** no real-device resource pressure, low-memory Mac, or offline-sandboxed queued run was exercised.
- **Speed:** no speed claim is made; Sequential is unchanged in speed.
