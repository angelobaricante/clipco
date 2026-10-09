import QuickLook
import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @Environment(AppModel.self) private var model
    @FocusState private var searchFocused: Bool
    @State private var dropTargeted = false

    var body: some View {
        @Bindable var model = model
        NavigationSplitView {
            SidebarView()
                .navigationSplitViewColumnWidth(min: 190, ideal: 220)
        } detail: {
            BrowserView()
                .overlay {
                    if let id = model.playingClipID, let clip = model.clips.first(where: { $0.id == id }) {
                        PlayerOverlay(clip: clip)
                    }
                }
                // Finder drops: videos, folders, or both. They go to what is open when dropped.
                .dropDestination(for: URL.self) { urls, _ in
                    model.drop(urls.filter(\.isFileURL))
                    return true
                } isTargeted: { dropTargeted = $0 }
                .overlay {
                    if dropTargeted {
                        DropHighlight(destination: model.showingLibrary ? "Footage library"
                                      : model.project?.name ?? "a new Project")
                    }
                }
                .safeAreaInset(edge: .bottom) {
                    if let notice = model.importNotice {
                        HStack {
                            Label(notice, systemImage: "tray.and.arrow.down").font(.callout).lineLimit(2)
                            Spacer()
                            Button("Show Activity") { model.showActivity = true }
                            Button("Dismiss") { model.importNotice = nil }
                        }
                        .padding(.horizontal, 12).padding(.vertical, 8)
                        .background(.bar)
                    }
                }
                .navigationTitle(model.showingLibrary ? "Reusable B-roll" : model.project?.name ?? "Clipco")
                .navigationSubtitle(model.trimmedQuery.isEmpty ? model.filter.rawValue : "Search")
                .searchable(text: $model.searchText, placement: .toolbar,
                            prompt: model.showingLibrary ? "Describe the shot, mood or idea" : "Search footage context")
                .searchFocused($searchFocused)
                .onChange(of: model.searchFocusRequest) { searchFocused = true }
                .task(id: model.searchText) {
                    try? await Task.sleep(for: .milliseconds(250))  // debounce typing
                    guard !Task.isCancelled else { return }
                    await model.search()
                }
        }
        .inspector(isPresented: $model.showInspector) {
            InspectorView()
                .inspectorColumnWidth(min: 280, ideal: 340, max: 520)
        }
        .quickLookPreview($model.quickLookURL)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Picker("View", selection: $model.browserMode) {
                    ForEach(BrowserMode.allCases) { Label($0.rawValue, systemImage: $0.symbol).tag($0) }
                }
                .pickerStyle(.segmented)
                .help("Show footage as a grid or a list (⌘1, ⌘2)")
            }
            ToolbarItem(placement: .primaryAction) {
                Button("Import", systemImage: "square.and.arrow.down") { model.showImport = true }
                    .help("Import a footage folder or source clip (⇧⌘I)")
            }
            ToolbarItem(placement: .primaryAction) {
                Button {
                    model.showActivity.toggle()
                } label: {
                    Label("Activity", systemImage: model.queue?.active != nil ? "arrow.triangle.2.circlepath"
                                                                              : "list.bullet.rectangle")
                }
                .help("Analysis queue: queued, active, waiting and finished jobs (⌥⌘A)")
                .popover(isPresented: $model.showActivity, arrowEdge: .bottom) { ActivityView() }
            }
            ToolbarItem(placement: .primaryAction) {
                Button("Inspector", systemImage: "sidebar.trailing") { model.showInspector.toggle() }
                    .help("Show or hide the inspector (⌘I)")
            }
        }
        .modifier(ProjectDialogs())
        .sheet(isPresented: $model.showImport) { ImportSheet() }
        .sheet(isPresented: $model.showNewProject, onDismiss: { model.newProjectFootage = [] }) {
            NewProjectSheet(footage: model.newProjectFootage)
        }
        .sheet(isPresented: $model.showSetup) { SetupSheet() }
    }
}

/// Destructive confirmations and error alerts for the Project window.
struct ProjectDialogs: ViewModifier {
    @Environment(AppModel.self) private var model

    func body(content: Content) -> some View {
        content
            .confirmationDialog(
                model.clipsToRemove.count == 1
                    ? "Remove “\(model.clipsToRemove[0].originalFilename)” from this Project?"
                    : "Remove \(model.clipsToRemove.count) clips from this Project?",
                isPresented: Binding(get: { !model.clipsToRemove.isEmpty },
                                     set: { if !$0 { model.clipsToRemove = [] } }),
                presenting: model.clipsToRemove
            ) { clips in
                Button("Remove from Project", role: .destructive) { Task { await model.remove(clips) } }
            } message: { clips in
                Text("Your notes and exclusions for " + (clips.count == 1 ? "it" : "them")
                     + " in this Project are deleted. The analysed context stays in your Footage library for other "
                     + "Projects, and the original video " + (clips.count == 1 ? "file stays where it is."
                                                                                : "files stay where they are."))
            }
            .confirmationDialog(
                model.clipsToRemoveFromLibrary.count == 1
                    ? "Remove “\(model.clipsToRemoveFromLibrary[0].originalFilename)” from the Footage library?"
                    : "Remove \(model.clipsToRemoveFromLibrary.count) clips from the Footage library?",
                isPresented: Binding(get: { !model.clipsToRemoveFromLibrary.isEmpty },
                                     set: { if !$0 { model.clipsToRemoveFromLibrary = [] } }),
                presenting: model.clipsToRemoveFromLibrary
            ) { clips in
                Button("Remove from Library", role: .destructive) { Task { await model.removeFromLibrary(clips) } }
            } message: { clips in
                let projects = Set(clips.flatMap(\.projects).map(\.name)).sorted()
                Text("Clipco deletes the transcript, frame observations, roles, and every Project's notes for "
                     + (clips.count == 1 ? "this clip" : "these clips")
                     + (projects.isEmpty ? "" : " (in \(projects.joined(separator: ", ")))")
                     + ". Codex can no longer retrieve it. The original video files are not affected.")
            }
            .confirmationDialog(
                "Delete the Project “\(model.projectToDelete?.name ?? "")”?",
                isPresented: Binding(get: { model.projectToDelete != nil },
                                     set: { if !$0 { model.projectToDelete = nil } }),
                presenting: model.projectToDelete
            ) { project in
                Button("Delete Project", role: .destructive) { Task { await model.delete(project) } }
            } message: { _ in
                Text("Clipco deletes this Project's notes and exclusions. Its footage stays in your Footage "
                     + "library with its analysed context. Your original video files are not affected.")
            }
            #if DEBUG
            // `-ClipcoSelectionLog /path` records each selection change, to verify mouse selection from outside.
            .onChange(of: model.selection) {
                guard let path = UserDefaults.standard.string(forKey: "ClipcoSelectionLog") else { return }
                let names = model.clips.filter { model.selection.contains($0.id) }.map(\.originalFilename)
                try? (names.sorted().joined(separator: ",") + "\n").write(toFile: path, atomically: true,
                                                                         encoding: .utf8)
            }
            #endif
            .alert("Something went wrong", isPresented: Binding(
                get: { model.errorMessage != nil }, set: { if !$0 { model.errorMessage = nil } })
            ) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(model.errorMessage ?? "")
            }
    }
}

/// A sidebar row: a footage filter of the open Project, or another Project to open.
enum SidebarItem: Hashable {
    case filter(FootageFilter)
    case project(Project.ID)
    case library
}

struct SidebarView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        List(selection: Binding<SidebarItem?>(
            get: { model.showingLibrary ? .library : .filter(model.filter) },
            set: { item in
                switch item {
                case .library: Task { await model.openLibrary() }
                case .filter(let filter):
                    if model.showingLibrary, let project = model.project {
                        Task {
                            do { try await model.open(project) } catch { model.errorMessage = error.localizedDescription }
                            model.filter = filter
                        }
                    } else {
                        model.filter = filter
                    }
                case .project(let id):
                    guard let project = model.projects.first(where: { $0.id == id }) else { return }
                    Task {
                        do { try await model.open(project) } catch { model.errorMessage = error.localizedDescription }
                    }
                case nil: break
                }
            })
        ) {
            Section(model.project?.name ?? "No Project") {
                ForEach([FootageFilter.all, .aRoll, .bRoll]) { filter in
                    FilterRow(filter: filter, count: model.showingLibrary ? nil : model.count(filter))
                }
            }
            Section("Review") {
                ForEach([FootageFilter.needsReview, .excluded]) { filter in
                    FilterRow(filter: filter, count: model.showingLibrary ? nil : model.count(filter))
                }
            }
            Section("Footage Library") {
                Label(FootageFilter.reusable.rawValue, systemImage: FootageFilter.reusable.symbol)
                    .tag(SidebarItem.library)
                    .help("B-roll you allow to be reused, from every Project and library-only footage")
            }
            Section("Projects") {
                Button("New Project…", systemImage: "plus") { model.showNewProject = true }
                    .buttonStyle(.borderless).foregroundStyle(.secondary)
                    .help("Create a Project; footage is optional (⌘N)")
                if !model.projects.isEmpty {
                    ForEach(model.projects) { project in
                        let isOpen = project.id == model.project?.id && !model.showingLibrary
                        Label(project.name, systemImage: isOpen ? "folder.fill" : "folder")
                            .fontWeight(isOpen ? .semibold : .regular)
                            .tag(SidebarItem.project(project.id))
                            .accessibilityAddTraits(isOpen ? .isSelected : [])
                            .contextMenu {
                                Button("Delete Project…", systemImage: "trash", role: .destructive) {
                                    model.projectToDelete = project
                                }
                                .disabled(!model.canDelete)
                            }
                    }
                }
            }
        }
        .safeAreaInset(edge: .bottom) {
            VStack(alignment: .leading, spacing: 8) {
                QueueSummary()
                ReadinessBadge()
            }
            .padding(12)
        }
    }
}

struct FilterRow: View {
    let filter: FootageFilter
    /// Nil while the library is shown, whose clips are not this Project's.
    let count: Int?

    var body: some View {
        Label(filter.rawValue, systemImage: filter.symbol)
            .badge(count ?? 0)
            .tag(SidebarItem.filter(filter))
            .accessibilityLabel(count.map { "\(filter.rawValue), \($0) \($0 == 1 ? "clip" : "clips")" } ?? filter.rawValue)
    }
}

struct ReadinessBadge: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Button {
            model.showSetup = true
        } label: {
            HStack(spacing: 6) {
                Image(systemName: symbol).foregroundStyle(tint)
                Text(title).font(.caption)
                Spacer(minLength: 0)
            }
        }
        .buttonStyle(.plain)
        .help(model.readiness?.detail ?? "Checking local models")
        .accessibilityLabel("Analysis readiness: \(title)")
    }

    private var title: String {
        guard let r = model.readiness else { return "Checking…" }
        return switch r.state {
        case .ready: "Local models ready"
        case .cold: "Models installed"
        case .loading: "Loading model…"
        case .modelMissing: "Model missing"
        case .serviceUnavailable: "Ollama not running"
        case .toolsMissing: "Media tools missing"
        case .workerUnavailable: "Worker unavailable"
        case .inferenceFailed: "Inference failed"
        }
    }

    private var symbol: String {
        switch model.readiness?.state {
        case .ready, .cold: "checkmark.circle.fill"
        case .loading, nil: "hourglass"
        default: "exclamationmark.triangle.fill"
        }
    }

    private var tint: Color {
        switch model.readiness?.state {
        case .ready, .cold: .green
        case .loading, nil: .secondary
        default: .orange
        }
    }
}

/// Shown while footage is dragged over the window: where it will be imported.
struct DropHighlight: View {
    let destination: String

    var body: some View {
        RoundedRectangle(cornerRadius: 10)
            .strokeBorder(Color.accentColor, lineWidth: 3)
            .background(Color.accentColor.opacity(0.08), in: .rect(cornerRadius: 10))
            .overlay {
                Label("Import into \(destination)", systemImage: "tray.and.arrow.down")
                    .font(.title3).padding(12).background(.regularMaterial, in: .capsule)
            }
            .padding(6)
            .allowsHitTesting(false)
    }
}

/// The sidebar's view of the analysis queue: the active clip, what remains, and what needs the creator.
struct QueueSummary: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if let q = model.queue, q.unfinished > 0 || q.count(.failed) > 0 {
            Button { model.showActivity = true } label: {
                VStack(alignment: .leading, spacing: 4) {
                    if let activity = model.activity {
                        HStack(spacing: 8) {
                            ProgressView().controlSize(.small)
                            VStack(alignment: .leading) {
                                Text(activity.filename).lineLimit(1).truncationMode(.middle)
                                Text(activity.stage).foregroundStyle(.secondary)
                            }
                        }
                    }
                    Text(summary(q)).foregroundStyle(attention(q) ? Color.orange : Color.secondary)
                }
                .font(.caption)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .buttonStyle(.plain)
            .help("Show the analysis queue")
            .accessibilityElement(children: .combine)
        }
    }

    private func attention(_ q: QueueState) -> Bool {
        q.count(.waiting) + q.count(.interrupted) + q.count(.failed) > 0
    }

    private func summary(_ q: QueueState) -> String {
        var parts: [String] = []
        let total = q.jobs.count, done = q.count(.completed)
        if q.count(.active) + q.count(.queued) > 0 { parts.append("\(done) of \(total - q.count(.cancelled)) done") }
        if q.count(.queued) > 0 { parts.append("\(q.count(.queued)) queued") }
        if q.paused { parts.append("Paused") }
        if q.count(.waiting) > 0 { parts.append("\(q.count(.waiting)) waiting for setup") }
        if q.count(.interrupted) > 0 { parts.append("\(q.count(.interrupted)) interrupted") }
        if q.count(.failed) > 0 { parts.append("\(q.count(.failed)) failed") }
        return parts.joined(separator: " · ")
    }
}

/// The analysis queue: per-job state and progress, with pause, resume, cancel and retry.
struct ActivityView: View {
    @Environment(AppModel.self) private var model

    private static let order: [AnalysisJob.State] = [.active, .queued, .waiting, .interrupted, .failed, .completed,
                                                     .cancelled]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header.padding(12)
            Divider()
            if let q = model.queue, !q.jobs.isEmpty {
                List {
                    ForEach(Self.order, id: \.self) { state in
                        let jobs = q.jobs.filter { $0.state == state }
                        if !jobs.isEmpty {
                            Section(title(state) + " (\(jobs.count))") {
                                ForEach(jobs) { JobRow(job: $0) }
                            }
                        }
                    }
                }
                .listStyle(.inset)
            } else {
                ContentUnavailableView("No Analysis Jobs", systemImage: "tray",
                                       description: Text("Dropped and imported footage is queued here."))
                    .frame(maxHeight: .infinity)
            }
        }
        .frame(width: 440, height: 460)
        .task { await model.refreshQueue() }
    }

    @ViewBuilder private var header: some View {
        let q = model.queue
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Analysis Queue").font(.headline)
                Text(q?.paused == true ? "Paused · the active clip finishes, nothing new starts"
                     : "Sequential · one clip at a time")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if let q, q.paused || q.count(.interrupted) + q.count(.waiting) > 0 {
                Button("Resume", systemImage: "play.fill") { Task { await model.resumeQueue() } }
                    .help("Run queued, interrupted and waiting jobs")
            } else {
                Button("Pause", systemImage: "pause.fill") { Task { await model.pauseQueue() } }
                    .disabled(q == nil || q!.count(.queued) + q!.count(.active) == 0)
                    .help("Start no new jobs; the active clip finishes")
            }
            Button("Clear", systemImage: "xmark.circle") { Task { await model.clearFinishedJobs() } }
                .disabled((q?.finished ?? 0) == 0)
                .help("Clear completed and cancelled jobs from this list")
        }
        .labelStyle(.iconOnly)
    }

    private func title(_ state: AnalysisJob.State) -> String {
        switch state {
        case .active: "Analyzing"
        case .queued: "Queued"
        case .waiting: "Waiting for Setup"
        case .interrupted: "Interrupted"
        case .failed: "Failed"
        case .completed: "Completed"
        case .cancelled: "Cancelled"
        }
    }
}

struct JobRow: View {
    @Environment(AppModel.self) private var model
    let job: AnalysisJob

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: symbol).foregroundStyle(tint).frame(width: 16)
            VStack(alignment: .leading, spacing: 2) {
                Text(job.originalFilename).lineLimit(1).truncationMode(.middle)
                Text("\(job.operationTitle) · \(model.destinationName(job))")
                    .font(.caption).foregroundStyle(.secondary)
                if job.state == .active {
                    Text(job.cancelRequested ? "Stopping…" : model.activity?.stage ?? "Starting")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let error = job.error, job.state != .completed {
                    Text(error).font(.caption).foregroundStyle(job.state == .cancelled ? Color.secondary : .orange)
                        .lineLimit(3).textSelection(.enabled)
                }
            }
            Spacer()
            if job.state == .active { ProgressView().controlSize(.small) }
            if job.canRetry {
                Button("Retry", systemImage: "arrow.clockwise") { Task { await model.retry([job]) } }
                    .labelStyle(.iconOnly).buttonStyle(.borderless).help("Queue this job again")
            }
            if job.canCancel {
                Button("Cancel", systemImage: "xmark.circle.fill") { Task { await model.cancel([job]) } }
                    .labelStyle(.iconOnly).buttonStyle(.borderless)
                    .help(job.state == .active ? "Stop this analysis; nothing is saved and the footage is kept"
                                               : "Remove this job; the footage is kept")
            }
        }
        .accessibilityElement(children: .contain)
    }

    private var symbol: String {
        switch job.state {
        case .active: "waveform"
        case .queued: "clock"
        case .waiting: "hourglass"
        case .interrupted: "pause.circle"
        case .failed: "exclamationmark.triangle.fill"
        case .completed: "checkmark.circle.fill"
        case .cancelled: "minus.circle"
        }
    }

    private var tint: Color {
        switch job.state {
        case .completed: .green
        case .failed, .waiting, .interrupted: .orange
        default: .secondary
        }
    }
}

/// New Project: only a name is required. Context and footage are optional, and nothing waits for the models.
struct NewProjectSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var name: String
    @State private var context = ""
    @State private var sources: [URL]
    @State private var choosing = false

    init(footage: [URL]) {
        _sources = State(initialValue: footage)
        _name = State(initialValue: AppModel.suggestedName(for: footage))
    }

    private var trimmedName: String { name.trimmingCharacters(in: .whitespaces) }

    var body: some View {
        Form {
            Section("Project") {
                TextField("Name", text: $name, prompt: Text("Water filter tutorial"))
                TextField("Context", text: $context, prompt: Text("Optional: what is the intended video about?"),
                          axis: .vertical)
                    .lineLimit(2...4)
            }
            Section("Footage (optional)") {
                LabeledContent(sources.isEmpty ? "None yet" : sources.count == 1 ? sources[0].lastPathComponent
                                                                                  : "\(sources.count) items") {
                    HStack {
                        if !sources.isEmpty { Button("Clear") { sources = [] } }
                        Button("Choose…") { choosing = true }
                    }
                }
                if sources.count > 1 {
                    ForEach(sources, id: \.self) { url in
                        Label(url.lastPathComponent, systemImage: AppModel.isFolder(url) ? "folder" : "film")
                            .font(.callout).lineLimit(1).truncationMode(.middle)
                    }
                }
                Text("You can also drop videos and folders on the Project later. Footage is queued and analysed "
                     + "locally one clip at a time; if the models are not set up yet, it waits.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .frame(width: 460)
        .fileImporter(isPresented: $choosing, allowedContentTypes: [.folder, .movie], allowsMultipleSelection: true) {
            if case .success(let urls) = $0 { sources = urls }
        }
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button("Create") {
                    let (name, context, footage) = (trimmedName, context, sources)
                    dismiss()
                    Task {
                        guard let created = await model.createProject(name: name, context: context) else { return }
                        if !footage.isEmpty { await model.enqueue(footage, into: created.id) }
                    }
                }
                .disabled(trimmedName.isEmpty)
            }
        }
    }
}
