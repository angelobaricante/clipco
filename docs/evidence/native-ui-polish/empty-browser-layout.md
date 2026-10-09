# Empty browser layout follow-up

Creator-requested fix, October 10, 2026 (Asia/Manila), using emil-design-eng.

| Before | After | Why |
| --- | --- | --- |
| Empty browser shrinks to intrinsic content height, moving its count/filter inset into the middle of the detail pane | Browser expands to the available width and height before adding its top inset | Header stays at the top; native unavailable content centers in the remaining region |
| Empty message explains transcript, sampled-frame and queue implementation | Short drop/import guidance and original-file assurance | Makes the next action clear |

The shared frame also applies to no-Project and zero-match browser branches. Native ContentUnavailableView, menu picker and import action are retained; selection behavior and the worker are unchanged.

Validation:

- `xcodebuild -project app/Clipco.xcodeproj -scheme Clipco -configuration Debug -derivedDataPath /private/tmp/clipco-empty-browser-build CODE_SIGNING_ALLOWED=NO build`: **BUILD SUCCEEDED**. Existing optional-coercion/worker warnings remain unrelated.
- Compiled the production SwiftUI views and AppModel with a temporary AppKit NSHostingView rendering harness. Rendered an empty Project at 1000×800 and 600×500 points in dark and light appearance. Compared the original BrowserView from main with the changed version. The original host shrank to 267 points high at both sizes; the fixed host occupied all 800/500 points. Inspected native PNG renders: count/filter at the top, empty content centered below, guidance and button fit at both widths. No worker startup, inference, footage or index access in this harness.
- `git diff --check`: passed.

Limits: direct native app inspection via computer-use timed out. These are native offscreen view renders, not an end-to-end NavigationSplitView/pointer/VoiceOver run. Import action is unchanged and was not activated. No timing or processing-load performance claim. Screenshots/harness remain local in `/private/tmp/clipco-empty-layout`; no footage or index is published.

The layout fix is also copied into the primary checkout's BrowserView.swift so the next normal app build includes it. Unrelated primary-checkout branding/spec changes are preserved and excluded from this branch. Existing #18 queue lifecycle acceptance remains separate.
