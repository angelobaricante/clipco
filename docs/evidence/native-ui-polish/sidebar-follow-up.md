# Sidebar and selection follow-up

2026-10-10, Asia/Manila. Creator-requested emil-design-eng follow-up on codex/native-ui-polish.

| Before | After | Why |
| --- | --- | --- |
| All Footage, A-roll and B-roll occupy three sidebar destinations | One All Footage destination; native role menu beside browser count | Roles refine the current collection without competing with Project navigation |
| Empty inspector retains active tabs and large empty-state typography | Inspector-sized centered placeholder; tabs appear for one selected clip | Clear, quiet guidance with no inactive controls |
| Single and double tap handlers compete for recognition | Simultaneous single-tap selection alongside double-tap playback | Selection need not wait for the double-click failure timeout; no selection animation |

Validation:

- Final native build: `xcodebuild -project app/Clipco.xcodeproj -scheme Clipco -configuration Debug -derivedDataPath /private/tmp/clipco-sidebar-build CODE_SIGNING_ALLOWED=NO build`: BUILD SUCCEEDED. Swift macro compilation requires normal unsandboxed Xcode execution; the initial sandbox build failed to start macro plugins.
- Actual native app with isolated scratch index under /private/tmp/clipco-sidebar-review: verified one All Footage sidebar row, native All Roles/A-roll/B-roll menu, A-roll changes the visible collection while All Footage stays selected, and Excluded with zero matches clears selection and presents the centered inspector placeholder without tabs/divider.
- Native indexed single-click changes the selected card and corresponding inspector identity. Double-click opens actual AVKit playback for IMG_6188.MOV, with the same clip selected in the inspector; closing playback restores browsing. Accessibility-based checks verify functional behavior, not input-to-render timing.
- Native screenshots verified dark appearance and full-height empty-inspector placement. No screenshots, footage or scratch indexes published.
- `git diff --check`: passed. Worker code and inference pipeline unchanged; no new inference was initiated.

Limits: coordinate-only pointer automation returned noWindowsAvailable, while indexed native clicks and double-clicks succeeded. No measured click-to-render latency, processing-load profile, full VoiceOver run, or light appearance check. Selection recognition no longer explicitly waits for double-click failure in source; real-device timing remains unmeasured.

Existing #18 queue lifecycle acceptance and unrelated #22 branding changes remain separate. Historical 10:00 Manila planning reference was less than two hours away at session start, already inside the agreed submission buffer; organizer cutoff was not independently verified and no submission was authorized.
