# Reusable retrieval and emotional tone evidence (issue #17), 2026-10-10 Asia/Manila

These were checked by the agent on the M5/24 GB development Mac. **The creator has not reviewed any of it.** The expected-range quality cases below still need the creator's judgement.

## Fixture checks (policy and orchestration only)

`cd worker && uv run pytest -q` passed 66 tests, with 3 deselected. `tests/test_tone.py` adds two of them. Both run the worker entry points (`Worker.enrich_tone`, `clipco-worker set-segment-tones`) and check the results through the real stdio MCP server. They cover:

- **Tone states**
  - Footage indexed before tone analysis is shown as `not_analyzed`, but it is still found by content.
  - A required `tone` filter never matches it. The response reports how many such Segments were skipped.
  - `none_supported` (analysed, no tone found) is distinct from `not_analyzed`.
- **Enrichment**
  - Explicit `enrich-tone` uses only the saved frames and transcript, with 0 speech calls and 0 new descriptions.
  - Already enriched footage is not read again.
- **Creator tones** are stored apart from the model's suggestions (`state: creator`). The suggestions and the evidence are not rewritten, and the creator can revert to the suggestions.
- **After re-analysis:** a correction whose Segment range a re-analysis no longer has is kept and shown (`unmatched_tone_corrections`).
- **Tone during analysis:** a new import or re-analysis reads tone as part of the analysis, at the creator's request on 2026-10-10. Footage analysed before tone existed stays `not_analyzed` until the creator asks for `enrich-tone` (the inspector's Read Emotional Tone); launch and search never upgrade it. A tone failure leaves the published analysis intact, with tone Not analyzed.
- **Literal fit wording:** a literal fit names what it rests on. A model interpretation or label is described as the model's, never as what the footage shows.
- **Ranking**
  - Better-fitting footage from another Project outranks weaker footage from the current Project.
  - When fits are comparable, the requesting Project's own footage leads, whichever Project is requesting.
  - Literal, metaphorical and purely emotional fits each get their own explanation.
  - Footage from elsewhere carries a caution that it does not document the requesting Project's events.
  - Standalone footage takes part.
  - Filler words ("something") do not pad the results, and a mood with no support returns nothing.
  - Project scope is unchanged.

The tone readings in these tests are scripted, so they prove only policy and orchestration, not tone quality.

## Real-model tone enrichment (on a copy of the real index)

`clipco-worker --home <copy> enrich-tone --library` ran on a `.backup` copy of `~/Library/Application Support/Clipco/index.sqlite` and its frame cache. **The creator's real index was not modified.**

- **Runtime:** Ollama `qwen3.5:4b-q4_K_M` (digest `d8b0f5e9760c`), with tone recipe 1. Input was the saved sampled frames, their observations, and the transcript.
- **Result:** 10 Segments across 4 ready clips in 108.0 s, about 10.8 s per Segment. 3 stale clips were skipped (status `not ready`), and none failed.
- **Citations:** every saved suggestion cites saved frame IDs, and no references were rejected.

Observed quality limits, from reading the outputs (not yet checked against playback):

- **Low variety:** "calm", "curious" and "nostalgic" make up almost every reading, and "nostalgic" rests on weak grounds (e.g. "reminiscent of early tech tutorials").
- **Motion from stills:** in one Segment (IMG_6189 18.1–27.1 s), "tense" is justified by "sudden, blurry motion in the second frame". That reads motion into a blurred still, which the prompt forbids.
- **Viewer vs. person:** two Segments describe the depicted person as "neutral" or "focused" in `depicted_emotion`, kept apart from viewer tone as designed.

## Offline saved-library retrieval

`library-queries-offline.txt` was produced by an MCP stdio session (`clipco-mcp`) against the enriched copy, run under `sandbox-exec` with a profile that denies **all** network access, loopback included. The MCP server therefore could not reach Ollama or anything else. Calls covered:

- overview
- five library searches, one with `tone='tense'`
- `get_segment_context` and `resolve_media` with `scope='library'`

All succeeded. `resolve_media` returned `available: true` for the unchanged original.

- The A-roll talking head is never a library result. "talking to the camera" returns only a B-roll laptop Segment, whose interpretation mentions the camera.
- "something joyful" returns nothing, because no saved reading supports joy.
- An earlier run, before the filler-word fix, padded that query with unrelated footage. That defect is now covered by a test.

## Native app

The Debug `Clipco.app` was launched with `open -n --env CLIPCO_HOME=<copy>` and `-ClipcoAutomationReview IMG_6189.MOV -ClipcoAutomationLibrary YES`. The automation calls the same model functions as the sidebar's Reusable B-roll item, the inspector's Tones menu (`-ClipcoAutomationTones 2:tense`) and the search field. `app-review-report.json` records:

- **Library view:** 2 reusable clips.
- **Tones:** the correction appears as `creator: Tense (suggested curious,tense, creator tense)`.
- **Search:** 5 library results, each with its fit kind and explanation.
- **Behaviour:** selection was preserved across view changes, and the source was verified as available.

`app-reusable-broll-search.png` is a capture of that window alone. Controls were **not** clicked by hand, and playback was not exercised in this run.

## Not yet demonstrated

- **Creator review:** the creator has not established literal, emotional or metaphorical requests with measured expected ranges across two Projects plus standalone footage. In the real index, the only ready reusable B-roll (IMG_6188, IMG_6189) belongs to one Project, so the cross-project cases need more creator footage.
- **Tone quality:** suggestions have not been compared with actual playback.
- **Offline enrichment:** local real-model enrichment inside the offline sandbox (as `offline-proof --sandbox` does for import) was not run.
