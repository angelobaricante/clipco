# Clipco — reusable B-roll library and adaptive indexing

Status: ready-for-agent. Published as [specification #15](https://github.com/angelobaricante/clipco/issues/15). The creator accepted all 21 design decisions and confirmed the consolidated scope on 2026-10-10 (Asia/Manila). GitHub is the authoritative tracker.

## Problem Statement

A creator's useful B-roll is scattered across Projects. Current retrieval searches one Project at a time and primarily matches words, so footage from another content idea cannot help an editing agent find stronger visual or emotional support. Whole-clip A-roll/B-roll classification also hides cutaways inside mixed recordings. Reimporting one file into multiple Projects duplicates its analysis, while deleting a Project removes context that could remain useful.

Import and Project creation take unnecessary steps. Creation is coupled to footage selection and model readiness, the app accepts footage only through a picker, and indexing runs sequentially without a durable pause/cancel/resume queue. Creators need faster processing where their hardware benefits from overlap, while constrained devices remain responsive and retain the same analysis quality.

## Solution

Keep Project footage-context retrieval for the main narrative, corrections, and repeated takes. Add a persistent Footage library for reusable B-roll that can support another video's content or emotional tone, preserving evidence, source ranges, origin, and creator control. Current-Project footage receives a modest preference among comparable candidates; better-fitting footage from elsewhere remains eligible.

The native Mac app exposes a Reusable B-roll view and independent Project creation, accepts dropped videos and folders, and registers work in a recoverable queue. Sequential processing stays the default. Auto uses measured, bounded stage overlap where beneficial and reduces concurrency under memory or thermal pressure. Originals remain untouched; analysis and saved-index retrieval remain local.

## User Stories

1. As a Creator, I want a Footage library independent of Projects, so that useful material remains available beyond one content idea.
2. As a Creator, I want to associate one Source clip with several Projects, so that I can reuse its analysis without copying its identity.
3. As a Creator, I want unchanged analysis reused on reimport, so that adding a Project membership does not repeat expensive inference.
4. As a Creator, I want duplicate candidates grouped, so that repeated imports do not crowd discovery results.
5. As a Creator, I want Project-specific notes, so that an interpretation for one story does not silently become another story's context.
6. As a Creator, I want Project-specific exclusion, so that I can omit footage from one Project's agent results without removing it everywhere.
7. As a Creator, I want source-wide Reuse permission, so that I can prevent every cross-project reuse of selected footage.
8. As a Creator, I want to restore exclusions and reuse choices, so that these decisions remain reversible.
9. As a Creator, I want Project deletion to preserve library footage, so that removing an old idea does not discard reusable context.
10. As a Creator, I want a separate Remove from Library action, so that I can deliberately remove saved context without modifying original videos.
11. As a Creator, I want direct library import, so that reusable footage does not require a placeholder Project.
12. As a Creator, I want existing indexes migrated safely, so that my notes, exclusions, evidence, and source references survive this change.
13. As a Creator, I want roles assigned to Segments, so that cutaways within a narrative recording can be discovered separately.
14. As a Creator, I want Mixed and Needs review states, so that uncertain footage is not silently treated as reusable B-roll.
15. As a Creator, I want to correct Segment roles, so that my judgment can refine reuse eligibility.
16. As a Creator, I want a clip-level role summary, so that normal browsing remains understandable.
17. As a Creator, I want A-roll retained in its Project, so that I can find the main explanation and its corrections.
18. As a Creator, I want reusable discovery restricted to eligible B-roll, so that another Project's narrative does not become an inappropriate candidate.
19. As a Creator, I want B-roll considered across the indexed library, so that a stronger supporting shot is not hidden by Project boundaries.
20. As a Creator, I want comparable current-Project footage preferred, so that original context remains useful without restricting better alternatives.
21. As a Creator, I want literal and metaphorical support considered, so that imagery can reinforce both subject matter and emotional intent.
22. As a Creator, I want fit explanations, so that I can assess a recommendation rather than accept unexplained rankings.
23. As a Creator, I want emotional tone distinguished from visible content, so that a subjective interpretation does not masquerade as an observation.
24. As a Creator, I want more than one plausible tone when appropriate, so that ambiguous imagery remains useful across different stories.
25. As a Creator, I want a consistent tone vocabulary with explanatory text, so that similar suggestions remain searchable without losing nuance.
26. As a Creator, I want tone suggestions grounded in sampled evidence, so that I can inspect their basis and limitations.
27. As a Creator, I want creator tone corrections separately attributed, so that my decisions do not rewrite model observations or transcripts.
28. As a Creator, I want unsupported tones left unspecified, so that every clip is not forced into an emotion category.
29. As a Creator, I want Not analyzed distinguished from no supported tone, so that missing analysis is not interpreted as neutrality.
30. As a Creator, I want otherwise eligible B-roll discoverable before tone enrichment, so that existing footage remains useful during upgrades.
31. As a Creator, I want an explicit library upgrade, so that opening the app does not silently reanalyze all my footage.
32. As a Creator, I want valid cached evidence reused during enrichment, so that unchanged speech is not unnecessarily transcribed again.
33. As a Creator, I want a native Reusable B-roll view, so that I can browse and verify what my editing agent can discover.
34. As a Creator, I want source origin and timestamps retained, so that cross-project recommendations stay traceable.
35. As a Creator, I want real preview and playback, so that I can judge tone against the actual recording.
36. As a Creator, I want an independent New Project action, so that I can create an idea before footage or models are ready.
37. As a Creator, I want only a name required for a new Project, so that optional context and footage do not slow creation.
38. As a Creator, I want to drop several videos or folders into the app, so that importing is as direct as using Finder.
39. As a Creator, I want the destination clear before work is queued, so that later navigation cannot move my imports to another Project.
40. As a Creator, I want a suggested Project name when starting from a drop, so that an empty workspace is easy to populate.
41. As a Creator, I want valid items accepted from mixed drops, so that an unsupported file does not discard the useful ones.
42. As a Creator, I want errors and skipped items summarized, so that I know what was actually registered.
43. As a Creator, I want file-picker import retained, so that drag-and-drop is an option rather than a requirement.
44. As a Creator, I want imports accepted during indexing or incomplete setup, so that I do not have to wait before organizing footage.
45. As a Creator, I want queued, active, completed, failed, and waiting work visible, so that progress and blockers are understandable.
46. As a Creator, I want to pause new work, so that I can reduce activity while already active clips finish.
47. As a Creator, I want to cancel analysis without deleting footage, so that abandoning processing is reversible.
48. As a Creator, I want interrupted work offered for resume, so that restarting does not lose the queue or repeat completed results.
49. As a Creator, I want one failure to preserve other completed clips, so that an unreliable source does not invalidate the library.
50. As a Creator, I want responsive browsing during indexing, so that preparation does not prevent review.
51. As a Creator, I want Sequential processing by default, so that concurrency does not unexpectedly consume my device's resources.
52. As a Creator, I want Auto to use available compute when beneficial, so that stronger devices can finish sooner.
53. As a Creator, I want Auto to reduce new concurrency under pressure, so that throughput does not come at the expense of responsiveness.
54. As a Creator, I want the same quality settings in both modes, so that speed does not silently weaken analysis.
55. As a Creator, I want explicit guidance when a configuration cannot run, so that Sequential is not mistaken for guaranteed support on every Mac.
56. As a Creator, I want measured throughput and resource use, so that speed and supported-device claims reflect real evidence.
57. As an Editing agent, I want explicit Project and library retrieval scopes, so that results do not depend on the GUI's active Project.
58. As an Editing agent, I want compact ranked results with reasons and origin, so that I can discover suitable footage without loading the whole library.
59. As an Editing agent, I want scoped evidence expansion, so that following a shared source does not reveal excluded membership notes.
60. As an Editing agent, I want validated previews and media locators, so that I can verify and use the correct unchanged source range.
61. As an Editing agent, I want existing Project retrieval calls to keep working, so that the library upgrade does not break established workflows.
62. As an Editing agent, I want empty, truncated, unavailable, and unanalysed results explicit, so that I do not invent evidence or infer a missing tone.
63. As a Creator, I want local analysis and saved-index retrieval after setup, so that footage is not silently sent to cloud inference.

## Implementation Decisions

1. **Architecture and baseline.** Extend the working native SwiftUI app, Python worker, SQLite index, local Ollama/Qwen3.5 vision, multilingual whisper.cpp speech, FFmpeg processing, and lightweight stdio MCP helper. Preserve the five read-only MCP tools, the approved sidebar/browser/inspector workflow, source preservation, and off-main-thread processing. This is an extension of the completed MVP rather than a replacement specification for its historical work.
2. **Ownership.** The library owns Source clips and shared analyses independently of Projects. Project memberships hold their own creator notes and exclusions. A source can have zero, one, or many memberships. Source-wide Reuse permission is distinct from a membership's exclusion.
3. **Identity and cache.** Reimporting the same source creates or reuses a membership rather than another unchanged analysis. Source fingerprints and analysis recipe/runtime/model identity validate reuse; filenames alone never establish equality. Group duplicate candidates while preserving their associations and verified locators. Avoid silently merging conflicting creator context.
4. **Migration.** Version and migrate the existing Project-owned index without losing notes, exclusions, source references, useful completed analysis, or provenance. Preserve valid external IDs where possible; if duplicate consolidation changes canonical identity, retain mappings so previously returned references resolve honestly rather than silently addressing another source. Migration does not start inference or fabricate new role/tone evidence. Legacy whole-clip roles cannot be treated as newly verified Segment roles without adequate evidence or creator review.
5. **Deletion semantics.** Removing a Project membership or deleting a Project removes that association and its Project context while keeping the library source. Remove from Library is a separate explicit action that removes index context and handles associated memberships, references, and queued work coherently. Neither action deletes, moves, renames, or rewrites originals.
6. **Role granularity.** Persist Segment-level role suggestions and creator corrections. A-roll and B-roll can coexist in one Source clip; Mixed and Needs review Segments remain reviewable but are excluded from reusable results until clarified. Clip summaries reflect their Segments. A-roll is project-bound as a product rule, not a universal claim that narrative recordings can never be reused.
7. **Reuse eligibility.** Library candidates require supported B-roll role and source Reuse permission. A shared source may use an allowed membership while excluded membership notes/context remain absent. Source permission off blocks every cross-project candidate. Standalone sources require no artificial Project. Migration/enrichment must make eligibility and unknown states explicit.
8. **Context scope.** Project notes remain associated with their Project. Search, relationship expansion, Segment context, and previously held-reference lookups must preserve the requested scope; library discovery must not expose excluded membership notes through an expansion path. Already returned context cannot be retroactively erased. Existing explicit Project review behavior must not become an implicit bypass of source reuse restrictions.
9. **Independent analysis.** Shared observations, descriptions, and tone are derived from source evidence independently of a video's intended content idea. Project/story intent influences retrieval suitability, not the underlying descriptions. Code owns all source-relative bounds and evidence IDs; model-cited references are validated against supplied evidence.
10. **Emotional metadata.** Emotional tone is a suggested audience response, separate from observable content and depicted-person emotion. Store a small consistent vocabulary, supporting descriptions and evidence, multiple plausible suggestions when justified, and creator corrections with separate attribution. Do not present model confidence as a measured probability or a guaranteed viewer reaction.
11. **Evidence limits.** The first version infers visual emotional tone from sampled frames and transcript context. It does not claim continuous viewing or infer music, pacing, or motion absent from the inputs. Use actual playback and creator review to assess suggestions before expanding sampling or audio analysis. Retain model/recipe identity and provenance with enriched results.
12. **Tone states and upgrade.** Distinguish Not analyzed, analyzed with no supported suggestion, and supported suggestions/corrections. Otherwise eligible B-roll with missing tone can match content requests but cannot satisfy a required tone through invented metadata. Existing context stays useful; enrichment is explicitly requested and reuses valid cached evidence. Opening the app or running a search does not initiate whole-library reanalysis.
13. **Ranking.** Prioritize narrative suitability and emotional fit; a current-Project association is a modest preference among otherwise comparable candidates, never a hard boundary or an override of suitability. Literal and metaphorical support both need explanatory grounding. Retrieval must not falsely imply that unrelated footage documents an event in the requesting Project. Matching representations, weighting, and thresholds are implementation choices evaluated against the approved real-footage requests.
14. **Saved retrieval.** Discovery reads saved local context/representations without starting speech, vision, or an inference service. Preserve the lightweight MCP boundary and offline saved-index usefulness. Do not fill weak or empty searches with unsuitable candidates. Results are compact and paginated, with five by default and the existing bounded expansion/preview behavior retained.
15. **MCP contract.** Extend the existing overview, search, context, preview, and media-resolution tools with explicit Project/library scope and scoped expansion. Existing Project calls retain their meaning. Results identify Source clip, Segment, permitted origin associations, source-relative range, evidence basis, role/tone state, fit explanation, analysis status, and revision. Library results need no owning Project. No implicit GUI-selected Project or full-library dump is permitted.
16. **Native review.** Add a Reusable B-roll library view and shared-source-aware inspector controls using real native controls. Support browsing, real playback/preview, role/tone corrections, source Reuse permission, Project exclusion, and distinct Project/library removal. Preserve selection, grid/list behavior, keyboard access, and completed-footage review during analysis.
17. **Project creation.** New Project is independent of import and inference readiness. Require a name only; context and footage are optional. Creating a Project does not load a model or require a running inference service.
18. **Drop destinations.** Accept videos, multiple videos, folders, and mixed selections through native drag-and-drop while retaining the picker. Drops onto an open Project target it; direct library imports target the library; an empty initial workspace offers Project creation with a suggested name. Bind destinations when jobs are created, not when they later execute. Preserve existing recursive discovery/deduplication behavior and summarize inaccessible or unsupported items without discarding valid sources.
19. **Registration and jobs.** Register accepted footage promptly and persist jobs with source, destination, operation, progress, and outcome. Imports can append while indexing runs or setup is incomplete. Separate queue lifecycle from source-analysis availability; waiting for setup/resources is explicit and does not falsely mark old context as newly analyzed. Duplicate requests must not run the same work concurrently.
20. **Lifecycle.** Pause stops new jobs while active clips finish. Queued cancellation removes analysis work without deleting footage. Active cancellation stops safely, contains media/speech child-process work and active inference requests, and leaves a truthful retryable state. Restart reconciles interrupted work and offers explicit resume; completed analysis is reused rather than repeated. Source removal must not race an active publisher into resurrecting deleted index context.
21. **Coherent publication.** The worker owns SQLite writes and publishes completed evidence/analysis atomically. Readers can use completed sources while other work runs. Coordinate job ownership and writes rather than sharing the existing thread-bound Store connection among worker threads. Derivation/replacement of relationships must handle references across shared sources and scoped memberships without partial ready results.
22. **Sequential.** Sequential is the default and processes one analysis job at a time. It still checks resources and service/model readiness: temporary pressure waits, while a configuration that cannot run gets actionable guidance. No silent smaller-model substitution, reduced analysis quality, cloud fallback, or automatic model download is allowed.
23. **Auto.** Auto uses bounded, independently limited stage overlap only where the installed runtime and measured device envelope show benefit. Account for combined speech, media, vision, service context-memory, and other device activity. Reduce starting concurrency under memory/thermal pressure while preserving completed results and quality settings. An unsupported or unhelpful parallel stage may stay sequential.
24. **Measurement.** Compare the same corpus and model/recipe settings under Sequential and Auto. Record throughput, per-job and total wall time, observed memory/resource state, failures, and grounding/retrieval quality. The M5/24 GB demo is the only existing hardware evidence; do not infer low-memory support or speedups from it. A smaller-model configuration needs separate research, validation, and disclosure.
25. **Delivery.** Implement four successive vertical tasks: library foundation; reusable retrieval and review; import/queue UX; adaptive processing. Each must pass its external acceptance checks before the next starts. Ready-for-agent means specified, not unblocked or claimed. Preserve the completed demo and keep implementation claims, native dependencies, and evidence in GitHub.

## Testing Decisions

1. **Approved seam.** Reuse the creator-confirmed external-behavior seam: import/manage footage through the app/worker entry points and observe the persisted results through the same real stdio MCP boundary Codex uses. Check outputs, evidence, ranges, policy, availability, and job outcomes rather than SQL shape, helper functions, thread count, or mocks mirroring implementation.
2. **Prior art.** Build on the existing worker-entry-point-to-MCP tests for Project discovery, creator notes/exclusions, recovery, cache reuse, and offline proof. Use the existing native import/review automation and actual SwiftUI interactions for UI behavior. Recorded inference responses prove orchestration only; real Ollama/Whisper runs and creator-reviewed footage establish model behavior.
3. **Migration and ownership.** Exercise a representative old index with duplicate imports, distinct notes/exclusions, completed and unavailable sources, relationships, and held IDs. Verify unchanged context, scope-safe aliases, one reusable analysis, persistence across reopen, standalone sources, and library survival after the last membership disappears. Removal must preserve original hashes and cannot be undone by an in-flight publisher.
4. **Policy.** Through search plus context/relationship expansion, verify A-roll stays project-bound, unknown/mixed roles are absent from reuse, source reuse-off blocks library discovery, allowed membership B can support a source excluded in A, and A's notes/context stay absent. Check old Project requests and held references cannot accidentally expose new shared membership context.
5. **Role and tone quality.** Review real mixed footage and ambiguous imagery with measured ranges. Verify eligible cutaways, uncertainty handling, multiple justified tones, explicit sample limitations, creator correction provenance, and no fabricated continuous motion/audio claims. Distinguish tone absence from missing enrichment. Do not treat hand-authored fixture descriptions as real model evidence.
6. **Retrieval quality.** Establish creator-reviewed literal, emotional, and metaphorical discovery requests across at least two Projects and standalone footage, with hand-verified expected Segments. Include a case where better cross-project B-roll outranks weaker current-Project footage and a comparable-fit case showing the modest Project preference. Relevant expected material must appear in the default top five; false event implications, duplicates, excluded context, and unsuitable padding fail acceptance regardless of response size.
7. **Native UX.** In the real app, create an empty Project without models; drop multiple videos/nested folders and mixed valid/invalid items into Project, library, and empty-workspace destinations; change Projects while queued work waits; and exercise library selection, inspector corrections, reuse toggles, previews, keyboard/focus, and removal. Prototype artwork or simulated controls are not evidence.
8. **Queue behavior.** At the same worker entry point, append work during processing; wait for missing setup/resources; pause; cancel queued and active work; interrupt and restart; explicitly resume; retry a failure; and remove a queued/active source. Observe truthful states, no duplicate ownership, no orphaned processing, no partial ready publication, completed-result reuse, and preserved originals.
9. **Offline and recovery.** With dependencies cached and the offline condition recorded, retrieve/search/review saved library context without inference services. Separately demonstrate local real-model enrichment/import offline. Missing/changed originals must refuse usable source locators; a failed clip preserves other results. Codex's remote inference remains a separate online concern.
10. **Performance.** Use the same real corpus, analysis settings, and correctness checks in Sequential and Auto. Record resource measurements and UI responsiveness during overlap and pressure reductions. No fixed speedup or universal low-end support is promised. Where pressure cannot be produced safely on available hardware, distinguish injected scheduler-policy checks from measured real-device behavior.
11. **Evidence reporting.** Record exact commands, versions/digests, measured outcomes, creator-reported versus agent-verified results, and limitations on the appropriate task. Documentation-only specification publication does not constitute successful implementation, inference validation, or a new performance result.

## Out of Scope

- Cross-project reuse of A-roll, automatic edits, timelines, rendering, generated B-roll, destructive cuts, or publishing/submitting videos.
- Guaranteed viewer emotions, clinical emotion detection, continuous video understanding, or unobserved music/motion/pacing analysis in this first version.
- Scanning unrelated folders, uploading originals or local indexes, silent model downloads, or cloud inference fallback.
- Automatic full-library enrichment on launch/search, unnecessary retranscription of unchanged speech, or silent smaller-model/quality substitution.
- Accounts, collaboration, hosted storage, additional operating systems, Intel support, a self-contained installer, or guaranteed low-memory support.
- Guaranteed speed, token, or cost savings; the existing token benchmark remains unrun and is not retroactively validated by this spec.
- Reopening the completed MVP issues or replacing their historical results with unmeasured claims.

## Further Notes

The creator confirmed the design, terminology, testing seam, four-task order, and consolidated scope in this conversation. The glossary and five ADRs capture the ownership, scope, evidence, and processing trade-offs. The design brief retains the 21 individual decisions and twelve acceptance scenarios. GitHub carries authoritative task state; local documents are the reproducible specification snapshot.

Existing runtime and real-model evidence are recorded in the completed demo documentation. The multilingual English/Tagalog/Taglish speech change remains approved; accuracy or throughput on additional footage/devices still requires measurement. No new model candidate or inference dependency is selected by this specification.

The historical hackathon planning assumption was 2026-10-10 at 10:00 Asia/Manila. Verify the organizer's authoritative cutoff and whether it still governs the next implementation session before scheduling deadline work, preserving the agreed submission buffer. Creating a specification or implementation issues does not authorize submission. Do not claim all four increments fit the historical remaining time without estimates and evidence.

The parent issue is a specification, not an independently claimable implementation task. The first task has no implementation blocker; the remaining three are natively blocked in the agreed sequence. Start only after reading current issue comments, checking blockers/claims, and claiming one task. Leave progress, validation, branch/commit, and remaining-work handoffs. Close tasks through validated integration, and close the parent only after all accepted behavior is demonstrated.

| Order | Native sub-issue | Blocked by |
| --- | --- | --- |
| 1 | [#16 — Share library sources across Projects and review Segment roles](https://github.com/angelobaricante/clipco/issues/16) | None; check claims |
| 2 | [#17 — Discover reusable B-roll across the library with grounded emotional tone](https://github.com/angelobaricante/clipco/issues/17) | #16 |
| 3 | [#18 — Create Projects easily and import dropped footage through a recoverable queue](https://github.com/angelobaricante/clipco/issues/18) | #17 |
| 4 | [#19 — Adapt indexing concurrency to device resources with measured Auto processing](https://github.com/angelobaricante/clipco/issues/19) | #18 |

The confirmed design, updated glossary, and ADRs are available on the [design/specification branch](https://github.com/angelobaricante/clipco/tree/codex/reusable-footage-design). Read that approved vocabulary until these documents are integrated into the implementation baseline.
