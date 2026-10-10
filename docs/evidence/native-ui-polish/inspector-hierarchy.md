# Context inspector hierarchy — task #32

Creator-requested cleanup of the right sidebar on 2026-10-10. Branch: `codex/inspector-hierarchy`.

| Before | After | Why |
| --- | --- | --- |
| Single-segment title repeats the clip heading | One clip heading and a compact Segment playback row | Avoid duplicate reading |
| Role picker mixes value and attribution | Effective role menu with Suggested / Set by you below | Separate the decision from its origin |
| Tone value competes with a long model identifier | Emotional tone value with a native Edit menu | Prioritize what the creator needs |
| Role reasons and tone explanations occupy the review area | Analysis details starts collapsed | Supporting information stays available on demand |
| Long sampled-observation heading | Sampled frames with a count | Make the evidence section easier to scan |

Summary text remains labeled Model interpretation. Analysis details retains summary model provenance, suggested role and grounds, suggested tone explanations/model identity, possible meanings, depicted emotion and limitations. Saved creator role/tone choices, native reset actions, pending-state disabling, timestamp playback links, observations, transcript and relationships keep their existing worker bindings. No inference or worker changes.

## Validation

- `xcodebuild -project app/Clipco.xcodeproj -scheme Clipco -configuration Debug -derivedDataPath /tmp/clipco-inspector-build build`: **BUILD SUCCEEDED**. The build needed compiler sandbox access outside the restricted execution sandbox.
- `git diff --check`: passed.
- Launched the rebuilt native app and inspected actual saved footage through computer use. A single-segment clip fit summary, role, tone and collapsed evidence sections in the roughly 340-point inspector; no title duplication. Multi-segment footage retained its segment titles/ranges, and an existing creator role choice remained labeled Set by you.
- Opened the role menu: direct Use Suggested, A-roll, B-roll, Mixed and Needs review choices; no additional submenu.
- Opened the tone menu: vocabulary toggles, No Tone and Use Suggested present. Closed both menus without changing saved choices.
- Expanded Analysis details: model identity, role basis, tone explanations, possible meanings, depicted emotion and full limitations were accessible.

This is native UI verification, not a new inference-quality or offline test. No footage, index or screenshots of private source material are included. Creator corrections were not written during this check. The recorded 10:00 Asia/Manila cutoff was already inside the reserved submission buffer at session start; no submission action occurred.
