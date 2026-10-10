# Clipco — Brand Context draft

Prepared October 10, 2026 (Asia/Manila), using Hiruno's Brand Context framework. Ready for creator review; proposed positioning and voice are labelled below. This document does not establish implementation completion or customer validation.

## Brand overview

**Name:** Clipco.

**Existing tagline:** Your clips, in context.

**One-liner:** Clipco analyzes your footage locally and builds reusable, searchable context that AI agents can draw on when editing videos, writing scripts, or planning content.

**Proposed lead message:** Help your AI agent find the right clips for your idea.

**Creator-refined pain point:** An AI agent lacks context about the footage library, making it difficult to select suitable clips or B-roll without inspecting the videos. Clipco prepares that searchable context locally and persists it across creative requests.

**Local cost distinction:** Clipco indexing uses on-device AI, with no cloud AI credits spent on that indexing. Local compute and storage still have costs; a connected agent still uses credits for retrieval context, reasoning, and any further inspection. Faster and cheaper is a proposed benefit to measure, not an established result.

**Proposed supporting message:** Prepare context from your clips locally, then let your agent retrieve the relevant moments for each new idea.

**Category:** Local footage assistant for creators.

Clipco indexes footage and supplies context through read-only MCP tools. An editing agent uses that context to make editing decisions and operate its own editing tools. Clipco's scope is footage knowledge and discovery; a footage-editing timeline is outside the approved MVP.

**Stage:** Working hackathon MVP with ongoing improvements. Public availability, pricing, monetization, and distribution terms: not yet provided.

## Target audience

**Confirmed intended user:** Creators who record raw footage and specify an intended video.

**Initial environment:** A configured Apple Silicon Mac. The README identifies English and Tagalog/Taglish footage as the initial scope; quality claims require real-footage evidence.

**Creator-confirmed audience direction:** Creators using AI agents for video editing, scriptwriting, or content creation who experience repeated footage analysis and folder discovery. Market size and broader demand have not been validated.

**Jobs to be done:**

- Reuse prepared footage context across new video, script, and content requests.
- Retrieve relevant footage context for an idea without requiring a fresh folder-wide review as the default starting point.
- Ground a script or content plan in what the creator actually recorded.
- Find source-grounded Segments that support an intended video.
- Review spoken explanations, repeated takes, and corrections before choosing material.
- Find supporting B-roll within a Project or from a reusable Footage library.
- Add creator intent while keeping it distinguishable from model interpretations.

## Problems and needs

**Primary evidence:** The creator's firsthand account supplied in this conversation. These describe their experience, not universal behavior of all AI agents.

1. Understanding footage consumes the agent's token budget. With a large clip collection, the creator experiences substantial token use during preparation, before the agent reaches the requested creative work. Hundreds of clips is the creator's illustrative scale, not a measured benchmark dataset.
2. The preparation repeats across requests. The creator reports that asking for another video or piece of content leads to the agent analyzing the footage again rather than drawing on durable footage knowledge.
3. Discovery requires folder crawling. The creator reports that the agent must explore the footage folder to learn what is available and which clips fit the request.

**Core problem:** Useful knowledge about the footage is not carried forward reliably in the creator's current agent workflow. Each new creative request can become another footage-discovery task.

**Desired change:** Prepare persistent footage context locally and make it retrievable for subsequent requests. The agent starts with relevant saved context and follows source references when closer inspection is needed.

**Outcome hypothesis:** Reusing prepared context could reduce repeated analysis and discovery work. Token savings, latency improvements, and quality at library scale remain unmeasured.

## Alternatives and positioning

**Creator-reported current approach:** Let the AI agent crawl footage folders and analyze clips for each new creative request. Repetition and token consumption are reported friction in this workflow; they are not independently benchmarked competitor findings.

**Other workflow alternatives to investigate:** Manually review footage and write notes; search transcripts; organize clips by folders; maintain agent-accessible context manually. No comparative claims have been established.

**Proposed positioning statement:** For creators using AI agents to edit videos, write scripts, and plan content from their footage, Clipco is a local footage assistant that builds persistent, source-grounded context their agents can retrieve across requests. It gives the creator's workflow a reusable foundation for finding footage and developing ideas.

## How the promise connects to real work

**Illustrative scenario, not a measured case study:** A creator has hundreds of clips and asks an agent for a video about a topic. Later, they ask for a script or another video using the same library. Their current workflow repeatedly discovers and interprets the material. With Clipco, the intended workflow is to prepare the footage index locally, then retrieve relevant saved context for each request.

- For editing: retrieve the main explanation, spoken correction, and supporting B-roll, with source timestamps.
- For scriptwriting: retrieve recorded statements and creator notes so the agent can develop a script grounded in available material.
- For content planning: explore indexed topics and footage to propose ideas the creator can support with their recordings.

These are downstream agent uses of Clipco context. The agent still needs to reason about each new request and may inspect original media. New or changed footage, failed analysis, and requested enrichment may require processing. Avoid promising that indexing eliminates all future analysis or token use.

## Distinctive approach

- Native Mac sidebar, footage browser, and inspector workflow.
- Local analysis using a Python worker and local models; persistent footage context in SQLite.
- Reusable context is the central value: prepare footage knowledge locally, persist it, and retrieve relevant portions across creative requests.
- Read-only MCP retrieval for editing agents.
- Original footage preserved; source identities and timestamps owned by code.
- Transcripts, sampled observations, interpretations, and creator notes kept distinct.
- Shared Footage library, Project membership, and creator-controlled B-roll reuse are part of the approved extension. Check the live tracker before presenting every extension feature as finished.

These describe product choices. They do not establish exclusivity, superiority, or measured benefits over competing products.

## Fit and expectations

**Good-fit hypothesis:** A creator using a Mac and an editing agent who wants inspectable context for local footage.

**Scope expectation:** Clipco prepares footage knowledge. Editing and final rendering require downstream tools.

**Setup expectation:** Initial runtime and model installation requires connectivity. Local processing readiness depends on installed dependencies and models.

**Privacy expectation:** Clipco's analysis is local. Context retrieved by a connected agent may be sent to that agent's provider. Avoid blanket claims that every part of the workflow is private or offline.

## Audience language

Use the established terms Creator, Project, Source clip, Segment, Footage context, Footage library, A-roll, B-roll, Spoken correction, Creator note, and Editing agent.

**Suggested phrases, not customer quotes:**

- Give your AI agent footage context it can reuse.
- Your next idea can start with the footage context you've already prepared.
- Build reusable context from your clips, locally.
- Find the footage your video needs.
- Give your editing agent context from your clips.
- Find the spoken correction and supporting B-roll.

Avoid full understanding, guaranteed viewer reaction, emotion detection, and calling Clipco a video editor. Do not claim faster editing, token savings, or broad offline usefulness without attributable measurements.

**Creator's own words, supplied in this conversation:**

- "AI Agents will do it every time you ask it to create video or create content"
- "AI Agents need to crawl your entire folder know what clips it needs to use for your needs"
- "create a context with it that you can reusable every time ai needs it"

These are founder experience, not independent customer testimonials. The existing tagline comes from the README.

## Brand voice — proposed

**Tone:** Clear, calm, practical, and creator-focused.

**Style:** Concrete language about clips, sources, and intended videos. Lead with what the creator can do; explain implementation only when it informs a decision.

**Personality:** Thoughtful, precise, approachable.

**Example:** You ask for a new video. Your agent can draw on the footage context you've already prepared.

**Claim boundary:** Explain that visual descriptions and emotional tone are interpretations. Give sources and limitations for performance claims.

## Visual identity

**Existing approved mark:** Solid three-facet C/play mark. Preserve its proportions, the play triangle, and the intentional narrow opening. No film perforations.

**Asset colors from brand/README.md:**

- Black: #0E0D0C — dark artwork and web icon color.
- White: #FFFFFF — light artwork.
- Neutral background: #F7F6F2 — web icon background.

These are documented asset colors, not a newly invented full UI palette. Use black artwork on light backgrounds and white artwork on dark backgrounds. Keep clear space of at least one quarter of the mark's width. Below 120 px, use the mark alone.

**Logo variants:** Mark, horizontal lockup, stacked lockup, and wordmark; transparent SVG and PNG masters are in brand/assets/.

**Wordmark:** Supplied outlined artwork; no font dependency. Editable wordmark font family: not yet provided.

**Product typography:** System typography is the approved native direction. Exact marketing font families, weights, and fallbacks: not yet provided.

**Product appearance:** Native semantic colors, neutral surfaces, restrained blue accents, light/dark appearance, real system controls, SF Symbols, and reduced-motion support. Exact accent HEX: not yet provided. Hiruno's own colors and fonts do not apply to Clipco.

## Evidence and proof boundaries

The local README reports completed original MVP tasks #2–#6 and process-level indexing/search evidence with outbound networking denied. It reports a creator-run Wi-Fi-off demonstration whose evidence is not stored in this repository. The token benchmark was not run; no savings are claimed.

brand/VALIDATION.md records successful app builds, compiled icon/resource checks, and Canva template checks. It explicitly says native screen inspection was incomplete. Brand assets are not proof of inference quality or actual native layout.

**Problem evidence:** The creator reports firsthand friction from token-heavy clip analysis, repeated analysis across creative requests, and folder crawling. Agent/client configuration, actual clip count, token traces, and comparative measurements were not supplied.

**Customer metrics, independent testimonials, adoption figures, comparative benchmarks:** Not yet provided.

## Goals and success measures

**Product goal:** Let an editing agent discover source-grounded footage appropriate to a creator's intended video.

**Proposed communication goal:** Connect Clipco to the creator's lived problem: repeatedly spending agent effort discovering and interpreting the same footage. Explain how persistent local context can be reused for editing, scripts, and content ideas.

**Proposed demonstration outcome:** A creator can import footage, inspect prepared context, and retrieve a relevant correction and supporting B-roll through an editing agent.

**Public call to action, launch goal, and baseline metrics:** Not yet provided.

**Future validation:** Compare repeated creative requests over the same library with and without prepared context. Record initial indexing effort separately from subsequent retrieval, agent token use, retrieval relevance, required media inspection, and script/edit quality. No measurements are claimed here.

## Sources and open items

Read locally: README.md; GLOSSARY.md; docs/TRACKER.md; docs/design/macos-design-notes.md; brand/README.md; brand/VALIDATION.md. The existing brand kit links to https://www.canva.com/folder/FAHXi5EUd7Y; that live folder was not inspected for this draft.

Live specification: https://github.com/angelobaricante/clipco/issues/1. Both GitHub CLI and web retrieval failed during this session, so live claims, blockers, and implementation status were not reverified. No implementation issue was selected or claimed for this brand-context draft.

Updated from the creator's firsthand experience in this conversation: token consumption during clip understanding, repeated work across creative requests, folder crawling, and the proposed reusable local-context solution.

Open items: creator review of the refined messaging and voice; marketing typography; launch/distribution and pricing if relevant; independent customer-language evidence; public CTA; measured outcomes across repeated requests.

Hiruno provides the method and can format an accepted document for export. It does not persist a brand profile; reuse requires this saved context to be accessible.
