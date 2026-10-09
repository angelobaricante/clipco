# Clipco — macOS MVP

Status: ready-for-agent

## Problem Statement

A creator records raw A-roll and B-roll, then asks an editing agent such as Codex to assemble a video. Before editing, the agent must discover what the source clips contain. Repeatedly opening files, inspecting frames, and reading long transcripts can consume context, tokens, and time. Filenames alone rarely identify a spoken correction, repeated take, or useful supporting shot. Cloud-dependent analysis also becomes unavailable when the creator loses connectivity.

The creator needs reusable, source-grounded footage context that remains useful on their Mac and lets an editing agent inspect only the material relevant to the current request. Reduced cost and improved reliability are hypotheses to measure, not guaranteed outcomes.

## Solution

A native macOS local footage assistant imports a project folder, transcribes speech and describes sampled frames on the device, and saves a searchable footage index. The creator reviews clips in the approved Variant D workspace: sidebar, footage browser, and a collapsible Context/Transcript/Info inspector. Notes and reversible exclusions refine the context without modifying originals.

Five read-only MCP tools let Codex discover relevant segments, inspect evidence and previews, and resolve original media ranges. The app supplies knowledge; the editing agent chooses edits and operates its own editing tools. After initial dependency/model downloads, local indexing, search, and review must work without internet. Codex's own remote inference may still require connectivity.

## User Stories

1. As a Creator, I want to create a Project around my content idea, so that the footage context reflects the video I intend to make.
2. As a Creator, I want to import raw Source clips from a folder, so that I can prepare my recorded A-roll and B-roll together.
3. As a Creator, I want originals to stay intact, so that indexing cannot destroy or silently rename my footage.
4. As a Creator, I want model and service readiness shown before analysis, so that I can resolve setup problems without guessing.
5. As a Creator, I want local speech transcription, so that spoken explanations become searchable without uploading my raw audio.
6. As a Creator, I want local visual observations from sampled frames, so that supporting shots become discoverable without cloud video inference.
7. As a Creator, I want analysis stages and per-clip progress, so that I know what is complete and what is still processing.
8. As a Creator, I want to use completed results during indexing, so that processing the remaining footage does not block review.
9. As a Creator, I want to browse All Footage, A-roll, and B-roll, so that I can focus on the relevant material.
10. As a Creator, I want descriptive labels alongside original filenames, so that I can understand clips without losing their source identity.
11. As a Creator, I want grid and list views to share selection, so that I can choose the browsing mode suited to the current task.
12. As a Creator, I want the inspector to follow my selected clip, so that its context and source details remain easy to inspect.
13. As a Creator, I want to hide the inspector or sidebar, so that I can give the footage browser more room.
14. As a Creator, I want to search footage context, so that I can find a specific explanation or supporting shot.
15. As a Creator, I want timestamped transcripts linked to the Source clip, so that I can verify what was actually said.
16. As a Creator, I want sampled-frame observations distinguished from interpretations, so that I understand the limits of the analysis.
17. As a Creator, I want Spoken corrections related to earlier statements, so that I can choose the intended explanation without losing evidence.
18. As a Creator, I want Repeated takes identified as related attempts, so that I can compare them rather than accept an automatic preference.
19. As a Creator, I want suggested A-roll/B-roll relationships, so that I can find supporting footage for an explanation.
20. As a Creator, I want real source previews, so that I can verify a description against the actual footage.
21. As a Creator, I want persistent creator notes, so that later retrieval includes information the model could not infer.
22. As a Creator, I want to exclude and restore clips in agent results, so that I control what the Editing agent discovers.
23. As a Creator, I want indexing reused for unchanged footage, so that new editing requests do not repeat expensive analysis.
24. As a Creator, I want changed footage marked stale, so that outdated context is not treated as current.
25. As a Creator, I want missing sources identified explicitly, so that a cached description is not mistaken for accessible media.
26. As a Creator, I want a failed clip to preserve the rest of the index, so that one problem does not invalidate my entire Project.
27. As a Creator, I want simple retry and source-restoration guidance, so that I can recover from failures.
28. As a Creator, I want native Mac keyboard, focus, appearance, and window behavior, so that review feels familiar and responsive.
29. As a Creator, I want actionable Codex MCP setup instructions, so that my Editing agent can connect to the saved index.
30. As an Editing agent, I want an explicit Project overview, so that I know which footage and analysis are available.
31. As an Editing agent, I want a small relevant Segment result set, so that discovery does not load the entire index into context.
32. As an Editing agent, I want expandable transcript windows and relationships, so that I can investigate relevant evidence on demand.
33. As an Editing agent, I want a separate frame-preview tool, so that I can verify a selected Segment visually.
34. As an Editing agent, I want original media locations and validated source-relative ranges, so that my editing tools can use the correct source material.
35. As an Editing agent, I want unavailable and truncated results stated explicitly, so that I do not infer missing evidence or invent a clip.
36. As a Creator, I want local indexing and review after an offline restart, so that the core product remains useful when the cloud disappears.
37. As a Creator, I want measured discovery tokens, latency, and retrieval quality, so that I can assess the product's actual efficiency.

## Implementation Decisions

1. **Environment and scope.** Target a configured Apple Silicon macOS development demo on the verified M5 Mac with 24 GB unified memory, macOS 26.5.1, and Xcode 26.3. Use English demo footage and Codex first. This is a greenfield product: the existing artifacts are planning documents and a browser prototype, not production code.
2. **Native interface.** Implement Variant D in SwiftUI with real system window chrome. Use standard sidebar/split-view navigation, a shared-selection footage browser, a collapsible inspector, toolbar search/actions, and contained import/setup sheets. Prefer native controls, semantic colors, SF Symbols, accessible labels, keyboard focus, and reduced-motion behavior. The browser prototype is a visual/interaction reference; do not ship it as the app or recreate its simulated window controls.
3. **Worker boundary.** The local Python indexing worker orchestrates FFmpeg extraction, whisper.cpp transcription, Ollama reasoning, validation, and index writes. It owns SQLite writes. UI requests changes through the worker and receives progress/results asynchronously; inference, media decoding, and long-running file work do not run on the main actor. A separate lightweight Python stdio MCP helper reads the index without loading inference models.
4. **Inference candidate.** Start with local Ollama and `qwen3.5:4b-q4_K_M`. Ollama is a separately installed/running demo dependency, accessed on loopback with its documented cloud-disabled configuration. Use whisper.cpp English Small for speech. Installation and initial weight downloads need connectivity; normal analysis uses cached local assets. Pin the runtime, dependencies, model digest/revision, and analysis recipe that pass the real smoke test.
5. **Early proof.** Before full UI development, verify real image-plus-transcript inference with schema-conforming results, measured speech timestamps, and offline reuse. After dependencies/weights are ready, allow up to 45 minutes for the inference gate within the first task's three-hour budget. Download/setup time still counts against that task and the deadline.
6. **Persistent domain data.** Persist Projects, Source clips, Segments, transcript evidence, sampled-frame references, descriptions, provenance, relationships, creator notes, exclusions, and indexing states/revisions in SQLite. Code assigns persistent project/clip/segment IDs. Keep source identity distinct from descriptive labels, filesystem locations, and model-generated text.
7. **Grounding.** FFmpeg/media metadata and speech alignment supply source-relative timestamps. The worker defines evidence/segment IDs and validates all start/end bounds against duration. Models refer to supplied IDs; unsupported IDs or invented timing do not become trusted context. Visual analysis describes sampled evidence, not continuous coverage of the entire video.
8. **Relationships and provenance.** Distinguish transcription, sampled observations, interpretations, and creator notes in UI and MCP output. Suggested Spoken correction and Repeated take relationships retain the original evidence. Supporting B-roll associations are suggestions, not commands that override the creator or automatically choose edits.
9. **Saved-index retrieval.** Search uses saved context without starting the VLM. The matching algorithm is an implementation choice validated on the approved queries. Defaults prioritize compact source-grounded excerpts, with explicit expansion instead of a full-index dump. Content and analysis-configuration changes invalidate affected cached results.
10. **MCP surface.** Provide the five tools below through a lightweight stdio server. Use explicit Project/Segment references rather than a hidden GUI-active Project. Keep stdout reserved for MCP protocol output and send diagnostic logs to stderr. Normal retrieval must not wait for model startup.

| Tool | Behavior |
| --- | --- |
| `get_project_overview` | Compact Project inventory, readiness, and analysis status |
| `search_footage` | Five relevant Segments by default; continuation/truncation explicit |
| `get_segment_context` | Surrounding timestamped transcript, relationships, provenance, and creator notes |
| `get_segment_preview` | Separate bounded image result with source/frame reference |
| `resolve_media` | Verified original source location and validated source-relative range |

11. **Tool results.** Compact matching JSON/text metadata identifies Project, Source clip, Segment, original filename, excerpt/description, evidence basis, analysis status, and index revision. Hard text/result/image limits are selected during implementation and checked by the benchmark. No match returns an empty result. Preview rendering and media access are tested with the installed Codex client. A returned local path is not an operating-system permission grant.
12. **State and publication.** Track pending, indexing, ready, failed, stale, and missing. Publish complete results coherently; readers must not see partial writes as ready. Partial failures preserve completed clips. Source availability is checked before returning usable media locations; changed sources remain stale until refreshed.
13. **Creator controls.** Persist notes and reversible exclusion through worker-owned writes. New default search results respect exclusions. Previously retrieved agent context cannot be retroactively erased. Keep raw transcripts and model observations attributable; notes augment them rather than silently replacing original evidence.
14. **Recovery/setup.** Provide actionable states for worker/service unavailable, missing model, model loading, inference failure, missing media, and changed sources. Retry uses the same source identity when appropriate. Do not silently download models during offline operation or fall back to cloud inference.
15. **Delivery order.** Implement six approved vertical tasks: one real clip (3h), Codex MCP (2h), full-Project discovery (4h), native review/notes (2.5h), recovery (1.5h), and offline proof/demo (2h). Each depends on the preceding demonstrable path. Recompute remaining wall-clock time and protect at least two hours for overrun/submission; estimates do not override the organizer cutoff.
16. **Authorized cuts.** Reduce frame sampling and the live demo subset if needed while preserving usable local speech and vision. A smaller researched Ollama candidate requires a fresh vision/schema quality check and explicit disclosure. Cut decorative polish/customization/sorting first; a single grid browser is an approved fallback if necessary. Preserve sidebar/inspector review and real MCP retrieval. A cached full index plus a live newly imported clip is allowed when clearly disclosed. Never substitute hand-authored descriptions or the HTML prototype for working local AI evidence.

## Testing Decisions

1. The creator approved one main external-behavior seam: import a fixture Project through the app/worker entry point and query it through the same MCP boundary Codex uses. Assert returned evidence, valid source ranges, relevant selection, and honest availability states, rather than internal implementation structure.
2. Add a small real Ollama/Whisper smoke test to prove speech and sampled-frame inference. Deterministic recorded responses can test orchestration and failure handling, but do not satisfy real-inference acceptance. There is no production test suite or prior implementation to inherit.
3. Exercise native import, selection, search, preview, inspector sections, notes, exclusions, keyboard/focus, and progress responsiveness in the actual SwiftUI app. Browser checks on the prototype do not prove native behavior or performance.
4. Use one English tutorial with 3–5 minutes of A-roll, six B-roll clips, a repeated take, and a spoken correction. Establish three discovery queries and manually verified expected Segments from the real corpus. Actual fixture timestamps must be measured, not copied from the illustrative prototype.
5. For each query, include a relevant expected Segment in the default top five. The correction query must expose both the earlier statement and correction, and supporting B-roll must be relevant without inventing facts such as visually measured water volume. Correctness is mandatory even when a shorter response would save more tokens.
6. Check stable IDs/ranges across reload, coherent completed writes, cache reuse without re-inference of unchanged footage, notes/exclusions reflected in MCP, and changed analysis inputs invalidating affected context.
7. Check failed clips preserving completed results, missing/changed sources refusing ready media resolution, meaningful retry/recovery, and source originals unchanged before/after indexing. Choose behavioral checks that exercise these real risks rather than duplicate the implementation.
8. With dependencies/weights cached, restart and index one newly supplied clip without internet, then search/review locally. Record how offline conditions are established. Demonstrate Codex handoff separately when Codex has the connection it needs. Local-only configuration alone is not proof of an offline restart.
9. Record cold startup/indexing, warm search/tool latency, repeated-query behavior, and observed memory on the verified M5/24 GB device. Under-two-second warm retrieval and under-ten-minute demo indexing are provisional targets. They do not establish support for lower-memory Macs.
10. Compare the same three discovery requests using the same Codex model/settings and source access: an efficient direct-inspection route versus this product's indexed MCP route. Allow sensible filenames, transcripts, sampled frames, and caching in the baseline. Do not require artificially exhaustive browsing.
11. Separate initial discovery from repeat/index-reuse requests. Report input, cached input, output, tool-result context, retries, image accounting where available, and wall time. Include tool overhead and account for one-time local indexing separately. State any unavailable token categories; text length is not a billed multimodal-token measurement. Downstream editing/rendering is outside discovery-only savings.
12. Aim for at least 50% lower discovery input while preserving retrieval quality; this is a measured hypothesis, not a release blocker. Report the actual outcome even when smaller. Dollar equivalents require current model/cached-token rates and are optional; subscription credits are not interchangeable with API token costs.

## Out of Scope

- A full editor, timeline, render engine, generated B-roll, automatic publishing, or guaranteed finished video.
- Automatic destructive cuts, original renaming/removal, or treating suggested relationships as approved editing decisions.
- Cloud inference fallback for core indexing/search; claims that Codex itself works offline.
- Claude parity before Codex works, other operating systems, Intel Mac support, or multilingual demo support.
- Accounts, payments, collaboration, hosted storage, or external service provisioning.
- A signed/notarized self-contained installer or full native Swift inference in this hackathon.
- Complete visual understanding, guaranteed cost savings, guaranteed elimination of agent freezes, or unmeasured low-memory-device support.
- Full transcript editing, elaborate sort/customization workflows, and a branding project.

## Further Notes

The creator approved the product/workflow, exact initial runtime candidate, MCP contract, Variant D direction, testing boundary, fallback priorities, and six-task granularity through the planning conversation. Planning decisions are recorded in the completed planning decisions; vocabulary is defined in the [domain glossary](https://github.com/angelobaricante/clipco/blob/main/GLOSSARY.md).

The approved design reference is [Variant D's native design notes](https://github.com/angelobaricante/clipco/blob/main/docs/design/macos-design-notes.md). The primary-source prototype is captured on local branch `prototype/footage-review-flow`, commit `317f2f14773f392feab8a189157a06e73f39764b`. It contains sample media illustrations and is not production app source.

The screenshot states October 10 at 10 AM as the cutoff; Asia/Manila is the planning timezone, subject to the organizer's authoritative deadline. At 4:42 PM on October 9, that interpretation leaves roughly 17 hours 18 minutes. Refresh this calculation at build start and preserve submission buffer. No product implementation, runtime installation, model download, or inference benchmark has yet been completed.

Runtime versions, supported formats, exact quality limitations, model licenses, and measured results must be recorded as implementation evidence. Disclose AI coding tools and any reused code/assets as required by the supplied hackathon rules. Preparing submission material does not itself authorize publishing a repository or submitting on the creator's behalf. The creator selected the public angelobaricante/clipco repository. GitHub issues are the authoritative implementation tracker; local planning files preserve the approved decision history.

