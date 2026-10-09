# Native UI polish validation

Implemented after docs/design/native-ui-ux-audit.md, on codex/native-ui-polish, based on task/18-recoverable-queue at f396afb.

| Before | After | Why |
| --- | --- | --- |
| Portrait cards grow taller than the browser | Bounded 16:9 thumbnails with fitted images and visible labels | Consistent scanning |
| Grid arrows move linearly; playback loses focus | Spatial arrows, Shift selection, scroll to selection, Escape restores focus | Predictable keyboard workflow |
| Search playback starts at zero; results stop at five | Matching Segment playback, stale-response rejection, immediate clear, Show More | Reach the matching moment |
| Library import displays the remembered Project | Explicit Library/Project/New Project destination captured at submit | Visible destination agrees with the job |
| Sheets dismiss before submission succeeds | Saving state, retained inputs, retry without duplicate Project creation | Recoverable failures |
| Clip role filters ignore Segment corrections | Effective Segment filters, Mixed badge, unresolved correction/review detection | Browser agrees with creator choices |
| Inspector details compete with useful context | Identity and interpretations first, native evidence disclosures, controllable transcript following | Faster reading with provenance |
| Metadata edits complete silently | Saving states, duplicate-operation guards, captured membership, retained failed note drafts | Navigation cannot retarget a save |
| Remembered Project controls appear in library | Scope-specific commands, sidebar filters, setup entry point, restored scope/view preferences | Clear navigation context |

## Validation

- Fresh Debug native build: BUILD SUCCEEDED, code signing disabled for local validation.
- Worker regression suite: 74 passed, 1 skipped, 3 deselected. No worker pipeline behavior changed.
- DEBUG native regression harness: 9 checks passed; sanitized result in regression.json. Separate scratch index with real indexed footage context; original index and footage were not modified. Checks corrected roles, review reasons, selection reconciliation, cross-Project note saving, continuation, nonzero playback and search clear.
- Live native UI on rebuilt app and scratch index: compact mixed-orientation grid; Down advances a visible row in four columns; Right advances one card; Shift+Right extends selection; Space opens AVKit; Escape followed by Right moves browser selection. Library import defaults to Footage Library. Search selection then Space starts the 7.9-second match at 8.33 seconds observed playback and reveals the matching inspector Segment. Library rows avoid relative “this Project” wording.
- git diff --check passed.

## Practical limits

No new frame-time benchmark or Instruments profile, full VoiceOver / Full Keyboard Access run, light mode / Increase Contrast pass, Finder drop exercise, or real processing-pressure trial was completed. Queue lifecycle acceptance work under #18 remains separate. This supports functional improvements, not Apple-equivalent performance. A persistent Activity window and per-scope selection/scroll restoration remain later refinements.

The opt-in DEBUG harness uses -ClipcoAutomationPolish YES -ClipcoAutomationOut with a scratch output path, and requires CLIPCO_HOME under /private/tmp/. Do not run it against the creator index. Real footage screenshots and the scratch index are not included here.
