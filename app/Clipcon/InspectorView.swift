import AVKit
import SwiftUI

enum InspectorTab: String, CaseIterable, Identifiable {
    case context = "Context", transcript = "Transcript", info = "Info"
    var id: Self { self }
}

struct InspectorView: View {
    @Environment(AppModel.self) private var model
    @State private var player = PreviewPlayer()

    var body: some View {
        @Bindable var model = model
        VStack(spacing: 0) {
            Picker("Inspector section", selection: $model.inspectorTab) {
                ForEach(InspectorTab.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(12)
            Divider()
            if let clip = model.selectedClip {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        SourcePreview(clip: clip, player: player)
                        StatusBanner(clip: clip)
                        switch model.inspectorTab {
                        case .context: ContextSection(clip: clip, player: player)
                        case .transcript: TranscriptSection(clip: clip)
                        case .info: InfoSection(clip: clip, project: model.project)
                        }
                    }
                    .padding(14)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else if model.selection.count > 1 {
                ContentUnavailableView("\(model.selection.count) Clips Selected", systemImage: "square.stack",
                                       description: Text("Select one clip to inspect its context."))
            } else {
                ContentUnavailableView("No Selection", systemImage: "sidebar.trailing",
                                       description: Text("Select a clip to inspect its context."))
            }
        }
    }
}

/// One AVPlayer for the inspector, pointed at the selected clip's verified original.
@MainActor
@Observable
final class PreviewPlayer {
    let player = AVPlayer()
    private(set) var clipID: SourceClip.ID?
    private var revision: Int?
    private(set) var access: SourceAccess?

    /// Checks the original again whenever the clip or its analysed revision changes.
    func show(_ clip: SourceClip) async {
        guard clip.id != clipID || clip.revision != revision || access == nil else { return }
        clipID = clip.id
        revision = clip.revision
        access = nil
        player.pause()
        let checked = await SourceAccess.check(clip)
        guard clipID == clip.id else { return }  // the selection moved on meanwhile
        access = checked
        if case .available(let url) = checked {
            player.replaceCurrentItem(with: AVPlayerItem(url: url))
        } else {
            player.replaceCurrentItem(with: nil)
        }
    }

    /// Plays from a source-relative time of the shown clip.
    func play(from seconds: Double) {
        player.seek(to: CMTime(seconds: seconds, preferredTimescale: 600), toleranceBefore: .zero,
                    toleranceAfter: .zero)
        player.play()
    }

    var canPlay: Bool { if case .available = access { true } else { false } }
}

/// AppKit's standard AVKit player view. (SwiftUI's `VideoPlayer` aborts while loading its type metadata on
/// macOS 26.5 in this build, so the AppKit view is hosted directly.)
struct SystemPlayerView: NSViewRepresentable {
    let player: AVPlayer

    func makeNSView(context: Context) -> AVPlayerView {
        let view = AVPlayerView()
        view.controlsStyle = .inline
        view.player = player
        return view
    }

    func updateNSView(_ view: AVPlayerView, context: Context) {
        if view.player !== player { view.player = player }
    }
}

/// Real playback of the original file, only after it is verified to be the one that was indexed.
struct SourcePreview: View {
    let clip: SourceClip
    let player: PreviewPlayer

    var body: some View {
        Group {
            switch player.access {
            case .available?:
                SystemPlayerView(player: player.player)
                    .accessibilityLabel("Original \(clip.originalFilename)")
            case nil:
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            case let state?:
                ContentUnavailableView {
                    Label(state == .missing ? "Original Not Found" : state == .changed ? "Original Changed"
                                                                                       : "Not Yet Verified",
                          systemImage: "film.slash")
                } description: {
                    Text(state == .missing ? "The file is not at its indexed location."
                         : state == .changed ? "The file changed since it was indexed, so it is not played."
                         : "Playback is available once analysis has checked the source.")
                }
            }
        }
        .aspectRatio(16 / 9, contentMode: .fit)
        .background(.quaternary, in: .rect(cornerRadius: 6))
        .clipShape(.rect(cornerRadius: 6))
        .task(id: clip.id) { await player.show(clip) }
        .onChange(of: clip.revision) { Task { await player.show(clip) } }
    }
}

struct StatusBanner: View {
    @Environment(AppModel.self) private var model
    let clip: SourceClip

    var body: some View {
        switch clip.status {
        case .indexing:
            Label(clip.id == model.activity?.clipID ? model.activity?.stage ?? "Indexing" : "Indexing",
                  systemImage: "hourglass")
                .foregroundStyle(.secondary)
        case .pending:
            Label("Waiting for analysis", systemImage: "clock").foregroundStyle(.secondary)
        case .failed:
            VStack(alignment: .leading, spacing: 8) {
                Label("Analysis failed", systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                Text(clip.error ?? "Unknown error").font(.callout).textSelection(.enabled)
                Button("Retry Analysis") {
                    Task {
                        await model.importFootage([URL(filePath: clip.sourcePath)], newProjectName: nil,
                                               context: model.project?.context ?? "")
                    }
                }
                .disabled(model.activity != nil)
            }
        default:
            EmptyView()
        }
    }
}

/// The creator's note and retrieval choice for one clip, saved through the worker.
struct CreatorControls: View {
    @Environment(AppModel.self) private var model
    let clip: SourceClip
    @State private var draft = ""
    @FocusState private var editing: Bool

    var body: some View {
        EvidenceGroup(title: "Creator note", symbol: "note.text", note: "your words, shared with Codex") {
            TextField("Note", text: $draft, prompt: Text("Context the editing agent should know"), axis: .vertical)
                .lineLimit(2...6)
                .textFieldStyle(.roundedBorder)
                .focused($editing)
                .onSubmit(save)
                .onChange(of: editing) { if !editing { save() } }
                .accessibilityLabel("Creator note for \(clip.originalFilename)")
            HStack {
                if let note = clip.note, draft.trimmingCharacters(in: .whitespacesAndNewlines) == note.text {
                    Text("Saved \(Date(timeIntervalSince1970: note.updatedAt).formatted(date: .omitted, time: .shortened))")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Save Note", action: save)
                    .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines) == (clip.note?.text ?? ""))
            }
        }
        .onAppear { draft = clip.note?.text ?? "" }
        // A note saved elsewhere replaces an untouched draft, so a stale draft never overwrites it.
        .onChange(of: clip.note) { if !editing { draft = clip.note?.text ?? "" } }
        .onDisappear { if editing { save() } }  // switching clips mid-edit keeps what was typed
        Toggle(isOn: Binding(get: { !clip.excluded },
                             set: { include in Task { await model.setExcluded([clip], !include) } })) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Include in retrieval")
                Text(clip.excluded ? "Excluded from new default searches. Context Codex already retrieved is not revoked."
                                   : "Codex can find this clip when it searches the Project.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .toggleStyle(.switch)
    }

    private func save() {
        let text = draft, id = clip.id
        Task { await model.saveNote(text, for: id) }
    }
}

struct ContextSection: View {
    let clip: SourceClip
    let player: PreviewPlayer

    var body: some View {
        CreatorControls(clip: clip).id(clip.id)
        Divider()
        if clip.segments.isEmpty {
            Text("No saved context yet.").foregroundStyle(.secondary)
        }
        ForEach(clip.segments) { segment in
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline) {
                    Text(segment.label).font(.headline)
                    Spacer()
                    Button("\(segment.start.timecode)–\(segment.end.timecode)") { player.play(from: segment.start) }
                        .buttonStyle(.link)
                        .font(.caption.monospacedDigit())
                        .disabled(!player.canPlay)
                        .help("Play the original from \(segment.start.timecode)")
                        .accessibilityLabel("Play from \(segment.start.timecode) to \(segment.end.timecode)")
                }
                EvidenceGroup(title: "Model interpretation", symbol: "sparkles",
                              note: segment.interpretation.model) {
                    Text(segment.interpretation.text)
                }
                EvidenceGroup(title: "Sampled frame observations", symbol: "photo",
                              note: "\(segment.observations.count) still frames, not continuous coverage") {
                    ForEach(segment.observations, id: \.frame.id) { obs in
                        HStack(alignment: .top, spacing: 8) {
                            FrameImage(path: obs.frame.path)
                                .frame(width: 72, height: 40).clipShape(.rect(cornerRadius: 4))
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Frame at \(obs.frame.time.timecode)")
                                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                                Text(obs.text)
                            }
                        }
                    }
                }
                EvidenceGroup(title: "Speech", symbol: "waveform", note: "whisper.cpp transcript") {
                    if segment.transcript.isEmpty {
                        Text("No speech detected").foregroundStyle(.secondary)
                    }
                    ForEach(segment.transcript) { line in
                        Text("“\(line.text)”")
                    }
                }
                if !segment.relationships.isEmpty {
                    EvidenceGroup(title: "Suggested relationships", symbol: "link",
                                  note: "derived from saved evidence; none is preferred") {
                        ForEach(segment.relationships) { related in
                            VStack(alignment: .leading, spacing: 2) {
                                HStack(spacing: 4) {
                                    Image(systemName: related.symbol)
                                    Text(related.title).fontWeight(.semibold)
                                    if related.excluded { Text("· excluded").foregroundStyle(.secondary) }
                                }
                                Text("\(related.originalFilename) \(related.start.timecode)–\(related.end.timecode)")
                                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                                Text("“\(related.excerpt)”").lineLimit(3)
                            }
                            .help(related.basis)
                            .accessibilityElement(children: .combine)
                        }
                    }
                }
            }
            .font(.callout)
            Divider()
        }
    }
}

struct EvidenceGroup<Content: View>: View {
    let title: String
    let symbol: String
    let note: String?
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 4) {
                Label(title, systemImage: symbol).font(.caption.weight(.semibold))
                if let note { Text("· \(note)").font(.caption).foregroundStyle(.secondary) }
            }
            .foregroundStyle(.secondary)
            content
        }
        .accessibilityElement(children: .contain)
    }
}

struct TranscriptSection: View {
    let clip: SourceClip

    var body: some View {
        let lines = clip.segments.flatMap(\.transcript)
        if lines.isEmpty {
            Text("No speech transcribed.").foregroundStyle(.secondary)
        }
        ForEach(lines) { line in
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(line.start.timecode).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                    .frame(width: 52, alignment: .trailing)
                Text(line.text).textSelection(.enabled)
            }
        }
    }
}

struct InfoSection: View {
    let clip: SourceClip
    let project: Project?

    var body: some View {
        Form {
            Section("Source") {
                LabeledContent("Original file", value: clip.originalFilename)
                LabeledContent("Location") { Text(clip.sourcePath).textSelection(.enabled).lineLimit(3) }
                if let d = clip.duration { LabeledContent("Duration", value: d.timecode) }
                if let w = clip.width, let h = clip.height { LabeledContent("Resolution", value: "\(w)×\(h)") }
                if let fps = clip.fps { LabeledContent("Frame rate", value: String(format: "%.2f fps", fps)) }
                if let language = clip.speechLanguageName { LabeledContent("Spoken language", value: "\(language) (detected)") }
                LabeledContent("Codecs", value: [clip.videoCodec, clip.audioCodec].compactMap { $0 }
                    .joined(separator: " / "))
                if let role = clip.role {
                    LabeledContent("Role", value: role == "a-roll" ? "A-roll" : "B-roll")
                    if let basis = clip.roleBasis { Text("Suggested: \(basis)").font(.caption).foregroundStyle(.secondary) }
                }
            }
            Section("Index") {
                LabeledContent("Status", value: clip.status.rawValue.capitalized)
                LabeledContent("Retrieval", value: clip.excluded ? "Excluded from default search" : "Included")
                LabeledContent("Revision", value: "\(clip.revision)")
                if let project { LabeledContent("Project ID") { Text(project.id).textSelection(.enabled) } }
                LabeledContent("Clip ID") { Text(clip.id).textSelection(.enabled) }
                LabeledContent("Segments", value: "\(clip.segments.count)")
            }
            if let a = clip.analysis {
                Section("Analysis") {
                    LabeledContent("Speech", value: "\(a.speech.engine) · \(a.speech.model)")
                    LabeledContent("Vision", value: "\(a.vision.engine) · \(a.vision.model)")
                    if let digest = a.vision.digest, !digest.isEmpty {
                        LabeledContent("Model digest", value: String(digest.prefix(12)))
                    }
                    LabeledContent("Elapsed", value: String(format: "%.1f s", a.elapsed))
                    LabeledContent("Completed", value: Date(timeIntervalSince1970: a.finishedAt)
                        .formatted(date: .abbreviated, time: .shortened))
                }
            }
        }
        .formStyle(.grouped)
        .scrollDisabled(true)
        .padding(-14)
    }
}
