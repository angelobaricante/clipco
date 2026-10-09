# Reusable footage and import improvements

Status: decisions 1–21 accepted by the creator on 2026-10-10 (Asia/Manila); awaiting final confirmation of the consolidated implementation brief. No application behavior has changed. This extends the completed MVP without rewriting its historical specification or evidence.

## Requested direction

The creator wants B-roll retrieval to consider useful footage outside the current Project, including footage that supports the intended emotion. A-roll should stay associated with its content idea. They also want drag-and-drop import of clips and folders, easier Project creation, and faster processing on capable devices while preserving sequential processing on constrained devices.

## Verified starting point

- `search_footage` requires a Project ID and searches both roles within that Project. Ranking uses saved text matches, without emotional or semantic similarity.
- A-roll/B-roll is a whole-clip classification. Mixed recordings and voice-over footage need explicit consideration before treating that classification as reuse eligibility.
- Source clips belong to one Project. Importing the same file into another Project creates a separate clip and analysis; cross-project retrieval needs a duplicate policy.
- Vision analysis receives two sampled frames per Segment and timestamped transcript text. It does not watch continuous video or listen to raw audio. Emotional tone would be an attributed interpretation, with evidence limits stated explicitly.
- New Project creation is embedded in the import sheet and gated by analysis readiness. The worker already supports creating an empty Project independently.
- Import supports multiple files/folders through a file picker, without drag-and-drop handling. Batch indexing runs sequentially; progress tracks one active clip.
- The worker owns atomic SQLite publication. Its current database connection cannot simply be shared across background threads. Parallel processing needs coordinated writes and job ownership.

Relevant code: `worker/src/clipcon_worker/{retrieval,store,pipeline,vision,relationships}.py`, `app/Clipcon/{Sheets,AppModel,WorkerClient}.swift`.

## Accepted first-round decisions

1. Preserve Project footage-context retrieval, including A-roll, corrections, and repeated takes. Cross-project reuse retrieval considers B-roll only. A-roll remains project-bound as a product rule.
2. Consider all eligible indexed B-roll across Projects by default, preserving its origin and allowing creator restrictions. No scanning of unrelated folders.
3. Emotional tone describes possible audience response, with multiple plausible interpretations, evidence-based explanations, and creator correction. Keep it separate from observable content and depicted-person emotion.
4. Determine role and reuse eligibility per Segment, including useful cutaways inside mixed Source clips. Keep a clip-level browsing summary and support creator correction.
5. Add an independent New Project action requiring a name, with optional context and footage. Drops onto an open Project add there; drops into an empty workspace offer a new Project with a suggested name. Originals stay in place.
6. Keep Sequential as the default processing mode. Offer Auto for bounded overlap only where measured beneficial, reducing concurrency under memory or thermal pressure without lowering analysis quality.

## Accepted second-round decisions

7. Prioritize narrative suitability and emotional fit. Give the current Project a modest preference when candidates are otherwise comparable. Allow metaphorical support with an explained connection; avoid footage that implies false facts.
8. Separate Allow reuse across projects from Exclude from agent results. Disabling reuse preserves original-Project retrieval; exclusion blocks retrieval through the excluded membership. Both controls are reversible. Decision 16 clarifies shared-source behavior.
9. Share one Source clip and its unchanged analysis across Project memberships. Keep notes and exclusions Project-specific. Group duplicate discovery candidates while preserving their associations.
10. Use a small, consistent set of searchable emotional tones plus an explanatory description. Allow multiple tones or no supported suggestion. Keep creator corrections separately attributable; do not present model confidence as a measured probability.
11. Start with visual emotional tone from sampled evidence and transcript context. Do not infer unanalyzed music or motion. Validate suggestions against real playback before deciding whether richer sampling or audio analysis is necessary.
12. Expose a Reusable B-roll library view in the app and explicit library retrieval scope for Codex. Preserve Project search. Cross-project results retain origin, ranges, tone, and fit explanations; preview and source resolution remain available.
13. Register accepted drops immediately and queue analysis, including while another batch runs or setup is incomplete. Show waiting-for-setup states without silent model downloads. Accept valid items from mixed drops and summarize unsupported/inaccessible items.
14. Show queued, active, completed, and failed clips. Pause stops starting jobs while active clips finish. Cancel removes queued analysis without deleting footage; active cancellation stops safely and remains retryable. Offer to resume unfinished work after interruption while preserving completed results.
15. Keep existing context usable during an explicit queued library upgrade; missing new metadata is Not analyzed rather than neutral. Reuse valid cached evidence where possible. Preserve creator notes, exclusions, and source references; opening the app must not trigger whole-library reanalysis.

## Accepted third-round decisions

16. Project exclusion is membership-specific. Library retrieval may use an allowed membership but must omit the excluded membership's notes and context. Source-level Allow reuse across projects applies everywhere; disabling it blocks all cross-project reuse.
17. The library owns indexed sources independently. Deleting a Project removes its associations and Project-specific notes while retaining library footage. Remove from Library separately removes saved context, never the original. Support direct library import without a placeholder Project.
18. Support Mixed and Needs review roles. Unresolved portions stay outside reusable results until analysis or creator correction identifies eligible B-roll; ordinary Project review remains available.
19. Otherwise eligible B-roll without tone metadata can appear in content-based discovery with Emotional tone: Not analyzed. It cannot satisfy an emotional-tone filter through invented metadata. Not analyzed differs from analyzed with no supported tone suggestion.
20. Sequential must still respect available resources. Wait when pressure is temporary and provide actionable guidance when the configuration cannot run. Do not silently reduce the model or analysis quality. Establish device support through measurements; evaluate smaller-model support separately.
21. Deliver four verified increments: library foundation, reusable retrieval, import experience and persistent queue, then adaptive processing. Verify each before proceeding. Compare Sequential and Auto on identical footage and quality settings; retain sequential execution wherever overlap has no measured benefit.

## Consolidated behavior

Project retrieval supplies the story's evidence, including A-roll, corrections, and repeated takes. Library retrieval supplies eligible reusable B-roll from any indexed source, including standalone library footage. B-roll can support a story literally or metaphorically; suggestions retain their evidence and never imply that unrelated footage documents an event in the current story.

Role, emotional tone, and reuse eligibility apply to source-relative Segments. Model suggestions and creator corrections remain attributable. Code owns timestamps and stable references. Mixed or unresolved roles need review before reuse; unanalysed emotional tone is explicit. Analysis describes the footage independently of the Project's intended video. Story context influences discovery, not the underlying observations.

A Source clip has shared analysis and optional Project memberships. Memberships carry Project-specific notes and exclusions. Source-wide reuse permission gates every cross-project candidate. For a shared source, only eligible memberships and their context may contribute to a library result; expansion must not accidentally reveal excluded membership notes. Standalone footage uses library context without requiring a Project. Project deletion and membership removal preserve library sources; library removal is a separate explicit action that clears saved context, not original media.

Reuse discovery prioritizes suitability and emotional fit, with a modest current-Project preference among comparable candidates. Results explain their support, identify origin and ranges, group duplicates, and permit evidence expansion and media verification. An empty or weak match must not be padded with unsuitable footage. Preserve compact default results and explicit pagination. Existing Project retrieval calls continue working; preserve the five read-only MCP tools while adding explicit retrieval scope and scoped context expansion. Retrieval remains local and uses saved representations without starting speech or vision inference.

The app exposes Project browsing and a Reusable B-roll library view with native controls, real previews, role/tone correction, and reuse controls. New Project creation is independent of imports and model readiness. Drops onto an open Project target that Project; direct library imports target the library; an empty initial workspace offers Project creation with a suggested name. Import destinations stay attached to their jobs even if the user switches Projects during processing. Existing file-picker import remains available.

Imports register promptly, summarize invalid items, and enter a durable queue. Queued items retain their source and destination across app restarts. Setup or temporary resource problems produce explicit waiting states. Pause blocks new jobs while active clips finish. Cancel never deletes footage; active cancellation stops safely and leaves retryable work. Interrupted work offers explicit resume without repeating completed results. Original-preservation checks, source availability, coherent index publication, and responsive browsing remain mandatory.

Sequential is the default. Auto can overlap independently bounded media, speech, and vision stages only when the installed runtime and measured resource envelope support useful overlap. Coordinate writes and job ownership; do not share the existing thread-bound Store connection between worker threads. Track aggregate and per-job progress. Resource reductions affect concurrency rather than analysis quality. The only existing hardware evidence is the M5/24 GB demo; support and speed on other devices are unverified until measured.

## Four implementation tasks

| Task | Scope | Completion evidence |
| --- | --- | --- |
| 1. Library foundation | Library-owned sources, Project memberships, migration, duplicate grouping, segment roles/corrections, source reuse permission, scoped exclusions, safe Project/library removal | Existing index migrates without losing notes, exclusions, usable source references, or analysis; mixed roles and shared-source permission cases work through app/worker/MCP boundaries |
| 2. Reusable retrieval | Saved emotional metadata and explicit enrichment, compact cross-project ranking/explanations, app library browsing, MCP scopes, scoped evidence expansion | Real-footage relevance and tone review; default top-five includes verified expected choices; unrelated A-roll and restricted membership context do not leak; offline saved-index retrieval works |
| 3. Import and queue UX | Independent Project creation, native multi-item/folder drops, direct library import, durable Sequential queue, pause/cancel/resume, waiting and progress states | Native interaction checks plus interruption/restart and mixed-drop behavior; imports work before setup and during active jobs; completed footage remains reviewable |
| 4. Adaptive processing | Auto limits and resource feedback, safe stage overlap and atomic publication, throughput/memory measurements | Same-corpus Sequential/Auto comparison with quality parity; pressure reduces new work safely; no duplicated jobs or partial ready results; no speed or low-end support claim without evidence |

Create these as approved GitHub implementation issues after final shared-understanding confirmation. Work one at a time with native blockers, claims, and progress/validation handoffs. Keep the completed demo usable throughout. Confirm any remaining submission deadline against the organizer's authoritative cutoff before scheduling implementation; the historical 10:00 Asia/Manila assumption alone is insufficient.

## Acceptance scenarios

1. A Project's spoken correction and repeated take remain retrievable; its A-roll never becomes a cross-project reuse candidate.
2. A verified B-roll Segment from an older Project outranks weaker current-Project footage for a suitable narrative/emotional request. Comparable current-Project candidates receive only the agreed preference.
3. A literal request and a metaphorical support request return suitable footage with different explanations; the latter does not falsely claim depicted events occurred in the requesting Project.
4. One file imported into two Projects reuses unchanged analysis and appears once per matching Segment, preserving associations. Excluding membership A omits A's notes while allowed membership B can still support discovery. Disabling source reuse prevents every cross-project result.
5. Deleting the last Project association retains library analysis and discoverability for otherwise eligible B-roll. Remove from Library removes its index context and queued work safely while the original remains unchanged.
6. A mixed recording contains independently classified narrative and cutaway ranges. Mixed/Needs review ranges stay out of reuse; creator correction preserves its attribution and changes eligibility.
7. A sampled quiet scene can have multiple supported tone suggestions with evidence and limitations. No reaction, music, or motion absent from the analysis is presented as an observation. A creator can revise or dismiss suggestions without rewriting raw evidence.
8. Not analyzed footage remains eligible for content searches when its role/permission are established, but cannot match a required tone through missing metadata. An explicit upgrade enriches it without silently launching a whole-library reanalysis or retranscribing valid cached speech.
9. Creating an empty Project succeeds without a model. Native drops of multiple videos and nested folders register valid sources, summarize errors, deduplicate selections, and preserve the intended destination through later navigation.
10. A drop during processing appends durable work; missing setup or temporary resource pressure keeps jobs waiting. Pause, queued cancellation, active cancellation, interruption, and explicit resume preserve completed results and original footage.
11. Searches, previews, Project changes, and creator review remain responsive during indexing. Missing/changed sources never resolve to usable media locators; model services are unnecessary for saved-index retrieval.
12. Real-model Sequential and Auto runs on the same corpus retain the same analysis settings and satisfy the same grounding checks. Record throughput, memory, resource state, and failures. If overlap fails to help or causes pressure, Auto safely limits new concurrency.

Subjective quality checks require creator-reviewed real clips and expected relevant ranges. Deterministic fixtures can verify policy, queue, migration, and failure behavior but do not prove emotional quality or measured hardware throughput.

Resolved terms are captured in `GLOSSARY.md`; durable boundary decisions are recorded in `docs/adr/`. The next step is final confirmation of this consolidated scope, not another open product decision.

## Research

[Ollama's concurrency documentation](https://docs.ollama.com/faq#how-does-ollama-handle-concurrent-requests) describes per-model parallel requests and additional context-memory allocation. It does not establish that this installed vision model will benefit from parallel requests. Actual throughput and memory pressure must be measured before selecting concurrency limits or claiming speed improvements.

[Apple's SwiftUI drag-and-drop documentation](https://developer.apple.com/documentation/SwiftUI/Adopting-drag-and-drop-using-SwiftUI) provides native receiving APIs. File/folder access and the existing worker import boundary still require app-level handling.
