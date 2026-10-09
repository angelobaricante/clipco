import SwiftUI

enum InspectorTab: String, CaseIterable, Identifiable {
    case context = "Context", transcript = "Transcript", info = "Info"
    var id: Self { self }
}

struct InspectorView: View {
    @Environment(AppModel.self) private var model

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
                        StatusBanner(clip: clip)
                        switch model.inspectorTab {
                        case .context: ContextSection(clip: clip)
                        case .transcript: TranscriptSection(clip: clip)
                        case .info: InfoSection(clip: clip, project: model.project)
                        }
                    }
                    .padding(14)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                ContentUnavailableView("No Selection", systemImage: "sidebar.trailing",
                                       description: Text("Select a clip to inspect its context."))
            }
        }
    }
}

struct StatusBanner: View {
    @Environment(AppModel.self) private var model
    let clip: SourceClip

    var body: some View {
        switch clip.status {
        case .indexing, .pending:
            Label(model.activity?.stage ?? "Indexing", systemImage: "hourglass")
                .foregroundStyle(.secondary)
        case .failed:
            VStack(alignment: .leading, spacing: 8) {
                Label("Analysis failed", systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                Text(clip.error ?? "Unknown error").font(.callout).textSelection(.enabled)
                Button("Retry Analysis") {
                    Task {
                        await model.importClip(URL(filePath: clip.sourcePath), newProjectName: nil,
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

struct ContextSection: View {
    let clip: SourceClip

    var body: some View {
        if clip.segments.isEmpty {
            Text("No saved context yet.").foregroundStyle(.secondary)
        }
        ForEach(clip.segments) { segment in
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline) {
                    Text(segment.label).font(.headline)
                    Spacer()
                    Text("\(segment.start.timecode)–\(segment.end.timecode)")
                        .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
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
