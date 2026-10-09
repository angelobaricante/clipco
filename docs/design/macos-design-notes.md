# macOS workspace prototype — Variant D

Question: Does a familiar Mac library/browser/inspector workflow make footage context easier to inspect than the earlier workspace, wizard, or table layouts?

The original four-variant study is on the `prototype/footage-review-flow` branch; view `review-flow.prototype.html?variant=D` there. The committed screenshot records the approved direction. This is an HTML interaction study with illustrative SVG thumbnails, not a native application or real video player. Everything stays in memory. Original variants remain available for comparison.

## Verdict

On October 9, 2026, the creator chose Variant D: “bro i like it! lets go with this D.” The MVP will implement its macOS sidebar/browser/inspector workflow in native SwiftUI. Context notes, reversible exclusion, explicit indexing/source failures, and simple retry/restore affordances are retained. A full transcript editor and a footage-editing timeline are outside this decision. Real media playback, actual source access, persistent notes, and live MCP setup still need implementation. The prototype validates the direction, not native performance.

During native review the same day, the creator changed playback: instead of Quick Look or a player in the inspector, double-click (or Space) opens a player covering the footage browser while the inspector stays beside it, and the transcript highlights the line being spoken. Quick Look remains on ⌘Y.

## Interaction design

- A persistent source sidebar organizes All Footage, A-roll, B-roll, Needs Review, and Excluded. Counts and selection remain visible.
- The main browser prioritizes footage thumbnails and descriptive labels, with original filenames underneath. Grid and list views share selection and filters.
- A trailing inspector reveals Context, Transcript, and Info for the selected clip. It can be hidden to give the browser more room.
- The window toolbar holds import, view switching, inspector visibility, and search. Codex connection is a secondary action in the sidebar.
- Import and connection use contained sheets. Double-click or Space opens an illustrative Quick Look preview. Up/down moves clip selection; Command-F focuses search; Command-I toggles the inspector; Shift-Command-I opens import.
- Context separates speech evidence, suggested corrections, and creator notes. Notes save in memory on leaving the field; exclusion is reversible.
- Incomplete, failed, and missing-source examples show explicit status with recovery actions. These actions simulate recovery rather than touching the filesystem.
- System typography, neutral surfaces, restrained blue accents, hierarchy through spacing, light/dark appearance, and reduced-motion support replace the earlier web-dashboard styling. SVG line icons are placeholders, not actual SF Symbols.

## Native implementation mapping

The production interface should be SwiftUI, using the system's real window chrome and controls. The HTML's traffic lights, materials, preview, and sheets only communicate layout. Do not reproduce browser chrome as custom native controls or ship the prototype in a WKWebView.

| Prototype region | Proposed native component |
| --- | --- |
| Project window | `WindowGroup` with standard macOS title bar and toolbar |
| Sidebar and browser | `NavigationSplitView`; a selectable `List` for source navigation |
| Grid/list mode | `LazyVGrid` for thumbnails; `Table` or `List` for source rows; one shared selection |
| Context inspector | `.inspector(isPresented:)` with system-managed width and standard controls |
| Search and actions | `.searchable`, `.toolbar`, native `Picker`, `Button`, and `Toggle` |
| Import | `.fileImporter` for source selection plus a small project-context sheet |
| Media inspection | Real `AVPlayer` playback or system Quick Look after resolving source access |
| Setup | `.sheet` with service/model status and the verified MCP registration command |
| Keyboard/menu access | SwiftUI `Commands`, keyboard shortcuts, focus management, and standard menu items |
| Appearance and accessibility | System semantic colors/materials, SF Symbols, VoiceOver labels, focus rings, and reduced-motion preference |

These are proposed implementation choices, not an implemented Swift module or a guarantee that every behavior has been validated against the current SDK.

## Keep the interface responsive

One observable UI state owns selection, filter, inspector visibility, and the currently displayed index snapshot. View code does not run FFmpeg, speech inference, or Ollama calls. The approved Python worker owns the analysis pipeline and SQLite writes; the app submits requests and receives incremental progress/completed results asynchronously. The read-only MCP helper consumes the same persistent index independently of window state.

Update view-facing state on the main actor. Cancel obsolete searches/thumbnail requests, avoid decoding large videos on the main thread, and load previews lazily. Indexing should preserve navigation and access to completed clips. User gestures should receive immediate visual feedback even when analysis takes time. Native controls provide platform behavior; actual smoothness still requires measurement in the real app.

Start with standard macOS 26 components, allowing the operating system to supply its current materials. Avoid adding decorative glass panels around footage or hand-building the sidebar/window system. Package all model and backend work outside this visual prototype.

## Sources

Apple's [Designing for macOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-macos/), [Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars), [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars), and [Windows](https://developer.apple.com/design/human-interface-guidelines/windows) inform the platform patterns. The component mapping is our proposed application of those patterns, with [NavigationSplitView](https://developer.apple.com/documentation/swiftui/navigationsplitview) and [inspector](https://developer.apple.com/documentation/swiftui/view/inspector(ispresented:content:)) as native starting points. Some Apple pages expose only JavaScript placeholders to the web reader; this is not an exhaustive HIG compliance audit.
