import SwiftUI
import UniformTypeIdentifiers

enum InspectorTab: String, CaseIterable, Identifiable {
    case context = "Context", transcript = "Transcript", info = "Info"
    var id: Self { self }
}

struct InspectorView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

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
                let spoken = model.spokenLineID(in: clip)
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 16) {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(clip.displayLabel).font(.headline)
                                Text(clip.originalFilename).font(.caption).foregroundStyle(.secondary)
                                    .lineLimit(1).truncationMode(.middle)
                                HStack {
                                    Text(clip.roleLabel)
                                    if let duration = clip.duration { Text("· " + duration.timecode).monospacedDigit() }
                                }.font(.caption).foregroundStyle(.secondary)
                            }
                            StatusBanner(clip: clip)
                            if model.inspectorTab == .transcript, model.playingClipID == clip.id {
                                Toggle("Follow Playback", isOn: $model.followPlayback).toggleStyle(.checkbox)
                            }
                            switch model.inspectorTab {
                            case .context: ContextSection(clip: clip, spoken: spoken)
                            case .transcript: TranscriptSection(clip: clip, spoken: spoken)
                            case .info: InfoSection(clip: clip, project: model.project)
                            }
                        }
                        .padding(14)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .onScrollPhaseChange { _, phase in
                        if phase == .interacting, model.inspectorTab == .transcript,
                           model.playingClipID == clip.id { model.followPlayback = false }
                    }
                    .task(id: model.selectedHit) {
                        await Task.yield()
                        if let id = model.selectedHit, model.inspectorTab == .context {
                            proxy.scrollTo(id, anchor: .top)
                        }
                    }
                    .onChange(of: model.followPlayback) { _, follow in
                        if follow, let spoken { proxy.scrollTo(spoken, anchor: .center) }
                    }
                    .onChange(of: spoken) { _, line in  // keep the spoken line in view while it plays
                        guard let line, model.inspectorTab == .transcript, model.followPlayback else { return }
                        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.25)) {
                            proxy.scrollTo(line, anchor: .center)
                        }
                    }
                }
                .id(clip.id)
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

struct StatusBanner: View {
    @Environment(AppModel.self) private var model
    let clip: SourceClip
    @State private var locating = false

    var body: some View {
        switch clip.status {
        case .indexing:
            Label(clip.id == model.activity?.clipID ? model.activity?.stage ?? "Indexing" : "Indexing",
                  systemImage: "hourglass")
                .foregroundStyle(.secondary)
        case .pending:
            Label(model.analysisStatus(clip), systemImage: "clock").foregroundStyle(.secondary)
        case .failed:
            recovery(model.analysisStatus(clip), symbol: "exclamationmark.triangle.fill",
                     detail: clip.error ?? "Unknown error",
                     kept: clip.segments.isEmpty ? nil : "Context below is from an earlier analysis and is not current.")
        case .stale:
            recovery("Context may be out of date", symbol: "clock.badge.exclamationmark",
                     detail: clip.error ?? "The original or the analysis settings changed since it was indexed.",
                     kept: "Codex sees this clip as stale and gets no file location until it is re-analysed.")
        case .missing:
            recovery("Original not found", symbol: "questionmark.folder",
                     detail: clip.error ?? "The original is not at \(clip.sourcePath).",
                     kept: "Saved context, your note, and exclusion are kept. Codex gets no file location for it.")
        case .ready:
            EmptyView()
        }
    }

    private func recovery(_ title: String, symbol: String, detail: String, kept: String?) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(title, systemImage: symbol).foregroundStyle(.orange).font(.headline)
            if let kept { Text(kept).font(.caption).foregroundStyle(.secondary) }
            DisclosureGroup("Details") {
                Text(detail).font(.callout).textSelection(.enabled)
            }.font(.caption)
            HStack {
                if clip.status == .missing {
                    Button("Locate…") { locating = true }
                        .help("Choose the same file in its new location")
                    Button("Check Again") { Task { await model.checkSources() } }
                        .disabled(model.activity != nil || model.isCheckingSources)
                } else {
                    Button("Re-analyse") { Task { await model.retry([clip]) } }
                        .disabled(!model.canRetry([clip]))
                        .help("Analyse the original again; the clip keeps its note and exclusion")
                }
            }
        }
        .accessibilityElement(children: .contain)
        .fileImporter(isPresented: $locating, allowedContentTypes: [.movie]) { result in
            if case .success(let url) = result { Task { await model.locate(clip, at: url) } }
        }
    }
}

/// The creator's note and retrieval choice for one clip, saved through the worker.
struct CreatorControls: View {
    @Environment(AppModel.self) private var model
    let clip: SourceClip
    let projectID: String?
    @State private var draft = ""

    private var noteKey: String { "note:\(projectID ?? "library"):\(clip.id)" }
    private var saving: Bool { model.pendingUpdates.contains(noteKey) }
    @FocusState private var editing: Bool

    var body: some View {
        if model.showingLibrary {
            LabeledContent("Projects", value: clip.projects.isEmpty ? "Library only"
                                                                    : clip.projects.map(\.name).joined(separator: ", "))
                .help("Notes and exclusions belong to each Project; open one to change them")
        } else {
            projectControls
        }
        Toggle(isOn: Binding(get: { clip.reuseAllowed },
                             set: { allowed in Task { await model.setReuse(clip, allowed) } })) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Allow reuse across projects")
                Text(clip.reuseAllowed ? "Its B-roll segments can be suggested for other videos."
                                       : "Only its own Projects can use it. Applies in every Project.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .toggleStyle(.switch)
        .accessibilityLabel("Allow reuse across projects")
        .disabled(model.pendingUpdates.contains("reuse:\(clip.id)"))
        if model.pendingUpdates.contains("reuse:\(clip.id)") { ProgressView("Saving reuse choice…").controlSize(.small) }
        LabeledContent("Segment roles", value: clip.roleSummary.text)
        ForEach(clip.unmatchedRoleCorrections, id: \.self) { kept in
            Label("Your \(SegmentRole.name(kept.role)) choice for \(kept.start.timecode)–\(kept.end.timecode) "
                  + "no longer matches a segment after re-analysis. Choose the role again below.",
                  systemImage: "exclamationmark.triangle")
                .font(.caption).foregroundStyle(.orange)
        }
        ForEach(clip.unmatchedToneCorrections, id: \.self) { kept in
            Label("Your tones (\(kept.tones.isEmpty ? "none" : kept.tones.joined(separator: ", "))) for "
                  + "\(kept.start.timecode)–\(kept.end.timecode) no longer match a segment after re-analysis. "
                  + "Choose them again below.", systemImage: "exclamationmark.triangle")
                .font(.caption).foregroundStyle(.orange)
        }
        if clip.projects.count > 1 && !model.showingLibrary {
            LabeledContent("Also in") {
                Text(clip.projects.filter { $0.projectId != model.project?.id }.map(\.name)
                    .joined(separator: ", "))
            }
            .help("One shared analysis; each Project keeps its own note and exclusion")
        }
    }

    /// The open Project's own note and exclusion for this clip.
    @ViewBuilder private var projectControls: some View {
        EvidenceGroup(title: "Creator note", symbol: "note.text", note: "your words, shared with Codex") {
            TextField("Note", text: $draft, prompt: Text("Context the editing agent should know"), axis: .vertical)
                .lineLimit(2...6)
                .textFieldStyle(.roundedBorder)
                .focused($editing)
                .onSubmit(save)
                .onChange(of: editing) { if !editing { save() } }
                .accessibilityLabel("Creator note for \(clip.originalFilename)")
            if let error = model.updateErrors[noteKey] {
                Text(error).font(.caption).foregroundStyle(.red).textSelection(.enabled)
            }
            HStack {
                if saving { ProgressView("Saving…").controlSize(.small) }
                else if let note = clip.note, draft.trimmingCharacters(in: .whitespacesAndNewlines) == note.text {
                    Text("Saved \(Date(timeIntervalSince1970: note.updatedAt).formatted(date: .omitted, time: .shortened))")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Save Note", action: save)
                    .disabled(saving || draft.trimmingCharacters(in: .whitespacesAndNewlines) == (clip.note?.text ?? ""))
            }
        }
        .onAppear { draft = model.noteDrafts[noteKey] ?? clip.note?.text ?? "" }
        .onChange(of: draft) { model.noteDrafts[noteKey] = draft }
        // A note saved elsewhere replaces an untouched draft, so a stale draft never overwrites it.
        .onChange(of: clip.note) {
            if !editing && model.noteDrafts[noteKey] == nil { draft = clip.note?.text ?? "" }
        }
        .onDisappear { if editing { save() } }  // switching clips mid-edit keeps what was typed
        Toggle(isOn: Binding(get: { !clip.excluded },
                             set: { include in
                                 Task { await model.setExcluded([clip], !include, projectID: projectID) }
                             })) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Include in retrieval")
                Text(clip.excluded ? "Excluded from new default searches. Context Codex already retrieved is not revoked."
                                   : "Codex can find this clip when it searches the Project.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .toggleStyle(.switch)
        .accessibilityLabel("Include in Project retrieval")
        .disabled(model.pendingUpdates.contains("exclude:\(projectID ?? ""):\(clip.id)"))
        if model.pendingUpdates.contains("exclude:\(projectID ?? ""):\(clip.id)") {
            ProgressView("Saving retrieval choice…").controlSize(.small)
        }
    }

    private func save() {
        guard let projectID, !saving,
              draft.trimmingCharacters(in: .whitespacesAndNewlines) != (clip.note?.text ?? "") else { return }
        let text = draft, id = clip.id
        Task {
            var submitted = text
            while await model.saveNote(submitted, for: id, projectID: projectID) {
                guard let newest = model.noteDrafts[noteKey], newest != submitted else { break }
                submitted = newest
            }
        }
    }
}

/// A transcript line, highlighted while the player is speaking it.
struct SpokenLine: View {
    let text: String
    let isSpoken: Bool

    var body: some View {
        Text(text)
            .padding(.horizontal, 4)
            .padding(.vertical, 2)
            .background(isSpoken ? Color.accentColor.opacity(0.22) : .clear, in: .rect(cornerRadius: 4))
            .accessibilityAddTraits(isSpoken ? .isSelected : [])
            .accessibilityValue(isSpoken ? "Now playing" : "")
    }
}

struct ContextSection: View {
    @Environment(AppModel.self) private var model
    let clip: SourceClip
    let spoken: Segment.Line.ID?

    var body: some View {
        DisclosureGroup(clip.note == nil ? "Notes and retrieval" : "Creator note and retrieval") {
            CreatorControls(clip: clip, projectID: model.scopeProjectID)
                .id("\(model.scopeProjectID ?? "library"):\(clip.id)")
                .padding(.top, 8)
        }
        if clip.segments.contains(where: { $0.tone.state == "not_analyzed" }) {
            HStack {
                Text("Emotional tone not analyzed for \(clip.segments.filter { $0.tone.state == "not_analyzed" }.count) "
                     + "of \(clip.segments.count) segments.")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("Read Emotional Tone") { Task { await model.enrichTone([clip]) } }
                    .disabled(!model.canEnrichTone([clip]))
                    .help("Ask the local model for this clip's tone from its saved frames and transcript; "
                          + "nothing is re-transcribed")
            }
        }
        Divider()
        if clip.segments.isEmpty {
            Text("No saved context yet.").foregroundStyle(.secondary)
        }
        ForEach(clip.segments) { segment in
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline) {
                    Text(segment.label).font(.headline)
                    Spacer()
                    Button("\(segment.start.timecode)–\(segment.end.timecode)") {
                        Task { await model.openPlayer(clip.id, at: segment.start) }
                    }
                        .buttonStyle(.link)
                        .font(.caption.monospacedDigit())
                        .help("Play the original from \(segment.start.timecode)")
                        .accessibilityLabel("Play from \(segment.start.timecode) to \(segment.end.timecode)")
                }
                EvidenceGroup(title: "Model interpretation", symbol: "sparkles",
                              note: segment.interpretation.model) {
                    Text(segment.interpretation.text)
                }
                SegmentRolePicker(segment: segment)
                SegmentToneView(segment: segment)
                DisclosureGroup("Sampled frame observations (\(segment.observations.count) stills)") {
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
                }
                DisclosureGroup("Speech transcript") {
                EvidenceGroup(title: "Speech", symbol: "waveform", note: "whisper.cpp transcript") {
                    if segment.transcript.isEmpty {
                        Text("No speech detected").foregroundStyle(.secondary)
                    }
                    ForEach(segment.transcript) { line in
                        SpokenLine(text: "“\(line.text)”", isSpoken: line.id == spoken)
                    }
                }
                }
                if !segment.relationships.isEmpty {
                    DisclosureGroup("Suggested relationships (\(segment.relationships.count))") {
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
            }
            .font(.callout)
            .id(segment.id)
            Divider()
        }
    }
}

/// The Segment's footage role: the creator's choice, or the suggestion and its basis when there is none.
struct SegmentRolePicker: View {
    @Environment(AppModel.self) private var model
    let segment: Segment

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Picker("Role", selection: Binding(
                get: { segment.role.creator ?? "" },
                set: { choice in Task { await model.setRole(choice.isEmpty ? nil : choice, for: segment) } })) {
                Text("Suggested: \(SegmentRole.name(segment.role.suggested))").tag("")
                Divider()
                ForEach(SegmentRole.choices, id: \.self) { Text(SegmentRole.name($0)).tag($0) }
            }
            .pickerStyle(.menu)
            .disabled(model.pendingUpdates.contains("role:\(segment.id)"))
            .accessibilityLabel("Footage role from \(segment.start.timecode) to \(segment.end.timecode)")
            if model.pendingUpdates.contains("role:\(segment.id)") { ProgressView("Saving role…").controlSize(.small) }
            DisclosureGroup("Role basis") {
            Text(segment.role.creator == nil ? segment.role.basis
                                             : "Set by you. Suggested \(SegmentRole.name(segment.role.suggested)): "
                                               + segment.role.basis)
                .font(.caption).foregroundStyle(.secondary)
            }
            if segment.role.effective == "mixed" || segment.role.effective == "needs_review" {
                Text("Not offered for reuse until you choose a role.").font(.caption).foregroundStyle(.orange)
            }
        }
    }
}

/// Suggested emotional tones with their grounds, and the creator's own tones kept apart from them.
struct SegmentToneView: View {
    @Environment(AppModel.self) private var model
    let segment: Segment

    var body: some View {
        let tone = segment.tone
        EvidenceGroup(title: "Emotional tone", symbol: "heart.text.square",
                      note: tone.model.map { "interpreted by \($0) from sampled evidence" }) {
            HStack {
                Text(tone.summary).fontWeight(tone.state == "creator" ? .semibold : .regular)
                    .foregroundStyle(tone.state == "not_analyzed" ? .secondary : .primary)
                Spacer()
                Menu("Tones") {
                    ForEach(SegmentTone.vocabulary, id: \.self) { name in
                        Toggle(name.capitalized, isOn: Binding(
                            get: { tone.tones.contains(name) },
                            set: { on in
                                let chosen = SegmentTone.vocabulary.filter { $0 == name ? on : tone.tones.contains($0) }
                                Task { await model.setTones(chosen, for: segment) }
                            }))
                    }
                    Divider()
                    Button("No Tone") { Task { await model.setTones([], for: segment) } }
                    Button("Use Suggested") { Task { await model.setTones(nil, for: segment) } }
                        .disabled(tone.creator == nil)
                }
                .disabled(model.pendingUpdates.contains("tone:\(segment.id)"))
                .accessibilityLabel("Emotional tones from \(segment.start.timecode) to \(segment.end.timecode)")
            }
            if model.pendingUpdates.contains("tone:\(segment.id)") { ProgressView("Saving tones…").controlSize(.small) }
            DisclosureGroup("Tone evidence and limitations") {
            if tone.creator != nil {
                Text("Set by you. Suggested: " + (tone.suggested.isEmpty ? "none"
                                                  : tone.suggested.map(\.tone).joined(separator: ", ")))
                    .font(.caption).foregroundStyle(.secondary)
            }
            ForEach(tone.suggested, id: \.tone) { s in
                Text("\(s.tone.capitalized): \(s.explanation)").font(.caption)
            }
            ForEach(tone.connotations, id: \.idea) { c in
                Text("Could stand for “\(c.idea)”: \(c.explanation)").font(.caption)
            }
            if let depicted = tone.depictedEmotion, !depicted.isEmpty {
                Text("Shown by a person: \(depicted)").font(.caption).foregroundStyle(.secondary)
            }
            Text(tone.limitations).font(.caption).foregroundStyle(.secondary)
            }
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
    @Environment(AppModel.self) private var model
    let clip: SourceClip
    let spoken: Segment.Line.ID?

    var body: some View {
        let lines = clip.segments.flatMap(\.transcript)
        if lines.isEmpty {
            Text("No speech transcribed.").foregroundStyle(.secondary)
        }
        ForEach(lines) { line in
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Button(line.start.timecode) { Task { await model.openPlayer(clip.id, at: line.start) } }
                    .buttonStyle(.link)
                    .font(.caption.monospacedDigit())
                    .frame(width: 52, alignment: .trailing)
                    .help("Play from \(line.start.timecode)")
                    .accessibilityLabel("Play from \(line.start.timecode)")
                SpokenLine(text: line.text, isSpoken: line.id == spoken).textSelection(.enabled)
            }
            .id(line.id)
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
                LabeledContent("Segment roles", value: clip.roleSummary.text)
                if let role = clip.role {
                    LabeledContent("Whole-clip role", value: role == "a-roll" ? "A-roll" : "B-roll")
                    if let basis = clip.roleBasis { Text("Suggested: \(basis)").font(.caption).foregroundStyle(.secondary) }
                }
            }
            Section("Index") {
                LabeledContent("Status", value: clip.status.rawValue.capitalized)
                LabeledContent("Retrieval", value: clip.excluded ? "Excluded from default search" : "Included")
                LabeledContent("Reuse across projects", value: clip.reuseAllowed ? "Allowed" : "Not allowed")
                LabeledContent("Projects", value: clip.projects.map(\.name).joined(separator: ", "))
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
