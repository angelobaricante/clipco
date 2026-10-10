# Clipco demo scripts

Drafted October 10, 2026, Asia/Manila. Requested length: 45–60 seconds. Scripts use the creator's firsthand problem account, the supplied hackathon briefing, Clipco's local demo documentation, and Hiruno's writing method. Finalist selection is not guaranteed.

## Recommended version — about 55–60 seconds

Approximately 128 spoken words. Timing is a production target, not a recorded read.

| Time | Voiceover | Picture |
| --- | --- | --- |
| 0–10s | Hundreds of clips. One content idea. How does your AI agent find the right B-roll when it doesn’t know what’s in your footage? | Real footage browser or folder; overlay: “Hundreds of clips. Which ones fit?” |
| 10–17s | Making it inspect every video eats into your AI credits before the creative work even starts. | Illustrative discovery sequence; no invented token count or benchmark. |
| 17–29s | Meet Clipco. It indexes your clips using AI running locally on your Mac, with no cloud AI credits used for indexing. Even offline. | Actual native app import, networking off, local processing, ready state. Label sped-up footage. |
| 29–40s | It saves searchable transcripts and visual context, linked to the original footage and timestamps. | Transcript, visual descriptions, then source playback. |
| 40–53s | Now, your agent searches that context and inspects the relevant clips. Next video, script, or content idea? Reuse the context. | Reconnect for Codex; real query, timestamped result, relevant source; second request from same index. |
| 53–60s | Give your agent a head start. Clipco. Your clips, in context. | Logo and tagline. Overlay before end card: “Clipco indexing/search: local. Codex AI: online.” |

## Short version — about 45 seconds

Approximately 101 spoken words. Allow time for a readable retrieval result.

“Your AI agent can’t find the right B-roll if it doesn’t know what’s in your clips.

“But asking it to inspect your entire library eats into your AI credits.

“Clipco indexes your footage locally on your Mac, with no cloud AI credits used for indexing. Even offline.

“It saves searchable transcripts and visual context, linked to source timestamps.

“Your agent searches that context, then inspects the clips relevant to your idea.

“Next video or script? Reuse the context.

“Local preparation. Relevant footage. Clipco. Your clips, in context.”

Picture sequence: footage/problem (0–10s), local indexing (10–23s), searchable context (23–30s), online agent retrieval and playback (30–40s), reuse and logo (40–45s). Include the online-agent label and label accelerated processing.

## Judging alignment

The supplied briefing, page 14, weights Problem & Usefulness 25%, Local AI Implementation 25%, Technical Execution 20%, Innovation 15%, and Product & Demo Quality 15%. Page 24 recommends a demo video around one minute. These are organizer reference requirements for planning, not authorization to publish or submit.

- Problem & Usefulness: the agent lacks library-wide footage context; a creator needs relevant B-roll for a specific idea. Demonstrate a real retrieval request.
- Local AI Implementation: visible local speech/vision processing of a new clip with networking off, followed by useful local search. Initial model installation requires connectivity.
- Technical Execution: actual processing, tool calls, timestamped retrieval, and matching source playback.
- Innovation: persistent footage context reused across distinct creative requests. Do not claim this is unique in the market without research.
- Product & Demo Quality: readable native UI, one point per scene, and source playback as the payoff.

## Recording conditions and claim checks

- The attachment's TixFox reference is 38.55 seconds long. Sampled frames and a local whisper.cpp transcription show a problem hook, product reveal, short benefit/UI chapters, and a logo close. This is a local inspection, not a Hiruno-hosted analysis or a proven performance result.
- Show a genuinely new clip for live indexing, or label existing results “Previously indexed.” Edited footage must not imply instant processing.
- Do not put Codex on screen while claiming it is operating offline. Clipco inference/index/search are local; the downstream agent's inference is cloud-based.
- Local indexing does not spend cloud AI analysis credits; it still uses local compute, storage, and electricity. Connected agents still consume tokens/credits for retrieved context and their own reasoning. Faster and cheaper is an intended benefit of avoiding repeated library-wide inspection, not an established comparative result. Reusable context still consumes agent tokens when retrieved. No token benchmark was run, so no percentage, dollar, or universal savings claim belongs in the demo.
- Clipco visual descriptions come from sampled frames. This script does not claim complete video understanding or verified correction detection.
- Use permission-cleared footage and a recorded result that fits the footage shown. The query is illustrative until replaced with the real recorded prompt.
- Put model names in a readable overlay during processing: “Speech: whisper.cpp · Vision: Qwen3.5 via Ollama.” Full versions/frameworks/cloud services/reused assets/development-tool disclosures belong in the submission materials. Do not try to narrate the entire stack in this short video.

## Sources and session handoff

- Organizer briefing: /Users/angelobaricante/Downloads/AppBuildersPH Hackathon 2026 Participant Briefing.pdf, relevant pages 5–9, 14–16, 24–25.
- Reference video: /Users/angelobaricante/Downloads/Chain_-_SO_MANY_people_asked_me_for_PROMPTs_to_use_with_the_motion_graphics_S_2UoW9J.mp4.
- Product and evidence: docs/DEMO.md, the previously read README.md, and brand/clipco-brand-context.draft.md. Creator-run offline and Codex recordings were reported in documentation; they were not inspected during script drafting.
- Method: Hiruno create_content, free framework call. No paid Hiruno video analysis was started.
- Branch at preparation: codex/native-ui-polish. Script is uncommitted; no code changes, benchmark, publication, or submission was performed by this task.
- Briefing cutoff: October 10, 10:00 AM. At the 7:03 AM Asia/Manila time check, approximately 2 hours 57 minutes remained. Reserve final review/upload/submission time. No separate video is generated by this task.
- Next action: creator reads the scripts aloud, selects the wording, and pairs it with actual offline/index/retrieval footage. No GitHub implementation issue was selected or claimed for scriptwriting.

Latest messaging refinement: lead with missing footage context and finding relevant B-roll. Local indexing prepares persistent context; downstream agents retrieve it and inspect relevant sources. No new performance benchmark was run.
