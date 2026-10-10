# Native launch splash

Creator-requested follow-up to identity issue #22, using the emil-design-eng skill. Implementation lives in `app/Clipco/ClipcoApp.swift`; the existing `ClipcoLogo` template PDF and brand palette come from branding PR #24.

The launch overlay uses warm white #F7F6F2 and near-black #0E0D0C, the approved horizontal logo, three subtle frame outlines, and the existing “Your clips, in context.” tagline. It uses native SwiftUI and a standard Button, leaving macOS window chrome intact. App-owned presentation state prevents replay when another window opens or the app returns to the foreground. The workspace stays mounted and its existing startup task runs independently.

| Before | After | Why |
| --- | --- | --- |
| Workspace appears immediately | 280 ms opacity/0.97-scale logo reveal; 180 ms exit | A short branded opening with restrained motion |
| No launch identity | Actual vector/template logo and adaptive brand colors | Preserve the approved artwork and light/dark legibility |
| No launch skip | Native Open Workspace button and Escape dismiss immediately | Keyboard dismissal has no animation |
| No launch accessibility variants | Reduce Motion uses opacity only and a shorter timer; Reduce Transparency omits the radial wash | Respect system preferences |

The normal presentation timer is 850 ms, followed by an 180 ms fade. Reduce Motion uses 250 ms and opacity only. Neither timer waits on worker/model readiness; failed setup cannot trap the creator in the splash. Disappearance cancels the timer. The existing worker/inference boundary is unchanged.

## Validation

- Final `xcodebuild -project app/Clipco.xcodeproj -scheme Clipco -configuration Debug -derivedDataPath /private/tmp/clipco-splash-build CODE_SIGNING_ALLOWED=NO build`: **BUILD SUCCEEDED**.
- Native `NSHostingView` render harness compiled the production splash view and loaded the built `Assets.car`. Light/dark renders at 1000×650 points were visually inspected. Captures are `launch-splash-light.png` and `launch-splash-dark.png` beside this document.
- Harness measured auto-dismiss once per mounted splash: light 0.947 s, dark 0.912 s, Reduce Motion 0.277 s, Reduce Transparency 0.919 s. These include host layout/run-loop overhead and are not app launch benchmarks. Removing the view after 100 ms canceled its timer with zero dismissal callbacks.
- SwiftUI accessibility preferences are read-only environment values. Only in the temporary harness, their declarations were replaced by injected Bool inputs to exercise both code paths; production reads the real system preferences. Native captures in these variants also completed.
- `git diff --check -- app/Clipco/ClipcoApp.swift`: passed. No worker startup, footage/index access, or inference was performed by the render harness.

Limits: full running-app launch/reopen, VoiceOver, and physical Escape/button interaction remain manual checks. The running app was not quit or relaunched, to preserve any active queue. The new build is at `/private/tmp/clipco-splash-build/Build/Products/Debug/Clipco.app`. Existing Xcode project warning about duplicate Copy Bundle Resources phases predates this change.

The task branch is `codex/launch-splash`. Only the splash source and this evidence are committed; other branding, browser, specification, and queue-related local changes remain unstaged. Integrate after PR #24 supplies the logo resource. No submission, footage, model weights, or local indexes are included. The historical 10:00 Asia/Manila cutoff was approximately 1h40m away at task start, inside the reserved buffer; its authoritative organizer wording was not independently available in this session.
