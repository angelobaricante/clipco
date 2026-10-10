# MCP context quality

Status: design interview in progress, 2026-10-10 (Asia/Manila). The creator confirmed the two decisions below. No replacement retrieval algorithm, new synthesis layer, or implementation task has been approved.

## Confirmed decisions

1. The primary outcome is evidence-grounded footage discovery: given a video idea, the editing agent finds useful A-roll, any relevant spoken correction, and supporting B-roll with verifiable source ranges and clear uncertainty. The editing agent retains editing choices.
2. Remove #19 (Auto/adaptive processing) from this MVP, rather than merely postponing its implementation. Retain the Sequential pipeline and recoverable queue. Pause further feature expansion while evaluating and improving MCP context quality; #18 still needs its recorded manual verification and integration.

## Verified baseline at design review

- SQLite already saves transcript evidence, sampled observations, Segment interpretations, source references, and suggested correction/take/B-roll relationships. Interpretation citations validate reference existence, not semantic truth.
- MCP search uses weighted lexical matching over saved context; it has no semantic embeddings or inference at query time.
- Default search returns five Segments with bounded excerpts. Context expansion has item limits but no global serialized-text/token cap. Project overview is an inventory, not a synthesized guide across clips.
- Real-model tone evidence reports weak/repetitive suggestions and an unsupported motion inference from stills. Existing fixture checks demonstrate policy and orchestration; real creator requests with expected ranges still need quality review. The token-savings benchmark remains unrun.
- #16/#17 are closed. #18 is open and claimed, on pushed branch `task/18-recoverable-queue` at `f396afb`, with manual UI verification/integration outstanding. #19 was unclaimed and blocked by #18 when the creator removed it.

Publication update (2026-10-10): #18 is now closed and integrated, and there are no open implementation issues. The status above records the earlier design-review baseline; context-quality implementation remains unapproved.

Relevant code: `worker/src/clipco_worker/{retrieval,relationships,store,vision}.py`. Quality limitations: [reusable retrieval evidence](../evidence/reusable-retrieval/README.md). Scope: [current specification](../reusable-footage-spec.md).

## Concept under consideration

[Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) proposes persistent synthesis and connections between raw sources. Clipco already applies part of that pattern at Segment level. A bounded guide across clips could help the editing agent reuse relationships, but a full wiki rewrite has no demonstrated advantage over the existing pipeline. Preserve original evidence, attribution, stable source references, creator restrictions, local analysis, and the five read-only MCP tools.

The creator clarified the intended benefit: give the editing agent a table of contents so it can navigate to clips suited to a user's request. This suggests a compact footage guide organized by topics and source-linked Segments, with detail expanded on demand. Faster discovery and better relevance remain hypotheses; a guide cannot establish that a candidate is the perfect clip, recover unsampled evidence, or validate a weak model interpretation by repeating it. The current Project overview supplies a clip inventory but no topic-to-Segment navigation.

## Open design frontier

- Whether to adopt a compact table of contents mapping topics to source-linked A-roll, correction/take relationships, and supporting B-roll, with evidence expanded on demand. Scope, update rules, pagination, and MCP exposure depend on this decision.
- The real-footage acceptance set and response budget for comparing current retrieval with proposed context improvements. Include paraphrased requests and no suitable match so irrelevant padding cannot pass.

These are proposals awaiting creator answers. Implementing an algorithm or synthesis layer requires the final shared-understanding confirmation after the interview; recording the confirmed scope removal is already authorized.
