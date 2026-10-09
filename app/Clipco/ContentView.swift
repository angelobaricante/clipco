import AppKit
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
        .sheet(item: $model.agentConnection) { AgentConnectionSheet(agent: $0) }
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
            .alert("Couldn’t Complete the Action", isPresented: Binding(
                get: { model.errorMessage != nil }, set: { if !$0 { model.errorMessage = nil } })
            ) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(model.errorMessage ?? "")
            }
    }
}

/// Sidebar destinations: Projects and the reusable Footage library.
enum SidebarItem: Hashable {
    case project(Project.ID)
    case library
}

struct SidebarView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        List(selection: Binding<SidebarItem?>(
            get: {
                if model.showingLibrary { return .library }
                return model.project.map { .project($0.id) }
            },
            set: { item in
                switch item {
                case .library: Task { await model.openLibrary() }
                case .project(let id):
                    guard let project = model.projects.first(where: { $0.id == id }) else { return }
                    Task {
                        model.filter = .all
                        do { try await model.open(project) } catch { model.errorMessage = error.localizedDescription }
                    }
                case nil: break
                }
            })
        ) {
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
            Section("Footage Library") {
                Label(FootageFilter.reusable.rawValue, systemImage: FootageFilter.reusable.symbol)
                    .tag(SidebarItem.library)
                    .help("B-roll you allow to be reused, from every Project and library-only footage")
            }
            Section("AI Agents") {
                AgentConnectionRow(agent: .codex)
                AgentConnectionRow(agent: .claude)
            }
        }
        .safeAreaInset(edge: .bottom) {
            VStack(alignment: .leading, spacing: 8) {
                QueueSummary()
                ReadinessBadge()
                Button("Local Setup…", systemImage: "gearshape") { model.showSetup = true }
                    .buttonStyle(.borderless).font(.caption)
            }
            .padding(12)
        }
    }
}

/// Visible connection entry points; configured means saved locally, not an active agent session.
struct AgentConnectionRow: View {
    @Environment(AppModel.self) private var model
    let agent: EditingAgent

    var body: some View {
        Button { model.agentConnection = agent } label: {
            HStack(spacing: 8) {
                Image(systemName: "point.3.connected.trianglepath.dotted")
                VStack(alignment: .leading, spacing: 2) {
                    Text(agent.rawValue)
                    Text(summary).font(.caption).foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
            }
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(agent.rawValue), \(summary), connection settings")
        .help("Connect Clipco’s saved footage context to \(agent.rawValue)")
        .task { if model.mcpStatus == nil { await model.checkMcp() } }
    }

    private var summary: String {
        guard let registrations = model.mcpStatus?.agents else {
            return model.isCheckingMcp ? "Checking…" : model.agentConnectionError == nil
                ? "Set up connection" : "Setup unavailable"
        }
        if agent == .codex {
            return registrations.first { $0.id == "codex" }?.title ?? "Set up connection"
        }
        let configured = registrations.filter { $0.id.hasPrefix("claude-") && $0.configured }.count
        if configured == 2 { return "Both apps configured" }
        if let connected = registrations.first(where: { $0.id.hasPrefix("claude-") && $0.configured }) {
            return connected.id == "claude-code" ? "Code configured" : "Desktop configured"
        }
        return "Set up connection"
    }
}

struct AgentConnectionSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let agent: EditingAgent
    @State private var claudeClient = "claude-desktop"
    @State private var confirmingDisconnect = false

    private var clientID: String { agent == .codex ? "codex" : claudeClient }
    private var registration: AgentRegistration? { model.mcpStatus?.agents?.first { $0.id == clientID } }
    private var busy: Bool { model.isCheckingMcp || model.connectingClient != nil }
    private var restartGuidance: String {
        clientID == "claude-desktop" ? "Quit and reopen Claude Desktop to apply changes."
            : "Start a new agent session to apply changes."
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("\(agent.rawValue) Connection").font(.title2.weight(.semibold))
            Text("Let your agent find footage, read its context, and locate the original clips.")
                .foregroundStyle(.secondary)
            if agent == .claude {
                Picker("Claude app", selection: $claudeClient) {
                    Text("Claude Desktop").tag("claude-desktop")
                    Text("Claude Code").tag("claude-code")
                }
                .pickerStyle(.segmented).disabled(busy)
            }
            if let registration {
                Label(registration.title,
                      systemImage: registration.configured ? "checkmark.circle" : "link")
                    .foregroundStyle(registration.configured ? Color.green : Color.secondary)
                if registration.state == "conflict" {
                    Text("This app has a different or disabled Clipco connection. Disconnect it here, then connect again to use this Clipco workspace.")
                        .font(.callout)
                }
                if !registration.installed {
                    Text("Install \(registration.name), then check setup again.").font(.callout)
                }
                if let error = registration.error { Text(error).font(.callout).foregroundStyle(.orange) }
                if registration.configured { Text(registration.guidance).font(.callout) }
                Text("Disconnect removes Clipco’s saved registration. \(restartGuidance)")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if let status = model.mcpStatus {
                Label(status.ok ? "Footage tools ready" : "Footage tools unavailable",
                      systemImage: status.ok ? "checkmark.circle" : "exclamationmark.triangle")
                    .font(.callout).foregroundStyle(.secondary)
                if let error = status.error { Text(error).font(.caption).textSelection(.enabled) }
            }
            if let error = model.agentConnectionError {
                Text(error).font(.callout).foregroundStyle(.orange).textSelection(.enabled)
            }
            Text("Connecting gives your agent access to saved footage context. Context it retrieves may be sent to its AI provider. Clipco’s analysis stays local.")
                .font(.caption).foregroundStyle(.secondary)
            if let registration {
                DisclosureGroup("Manual setup") {
                    VStack(alignment: .leading, spacing: 8) {
                        if let path = registration.configPath {
                            Text(path).font(.caption.monospaced()).textSelection(.enabled)
                        }
                        if let command = registration.setupCommand {
                            Text(command).font(.caption.monospaced()).textSelection(.enabled)
                            Button("Copy Command") { copy(command) }
                        } else if let json = registration.setupJson {
                            Text("Merge the Clipco entry into your app’s configuration, then quit and reopen the app.")
                                .font(.caption)
                            Text(json).font(.caption.monospaced()).textSelection(.enabled)
                            Button("Copy Configuration") { copy(json) }
                        }
                    }.padding(.top, 6)
                }
            }
            Divider()
            HStack {
                Button("Check Setup") { Task { await model.checkMcp() } }.disabled(busy)
                if busy { ProgressView().controlSize(.small) }
                Spacer()
                Button("Done") { dismiss() }.keyboardShortcut(.cancelAction).disabled(busy)
                if registration?.configured == true || registration?.state == "conflict" {
                    Button(registration?.configured == true ? "Disconnect" : "Disconnect Existing Connection", role: .destructive) {
                        if registration?.state == "conflict" {
                            confirmingDisconnect = true
                        } else {
                            Task { await model.connectAgent(clientID, disconnect: true) }
                        }
                    }
                    .disabled(busy)
                } else {
                    Button("Connect \(registration?.name ?? agent.rawValue)") {
                        Task { await model.connectAgent(clientID) }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(busy || registration?.installed != true || registration?.error != nil
                              || model.mcpStatus?.ok != true)
                }
            }
        }
        .padding(24).frame(width: 520)
        .interactiveDismissDisabled(busy)
        .alert("Disconnect the existing Clipco connection?", isPresented: $confirmingDisconnect) {
            Button("Disconnect", role: .destructive) {
                Task { await model.connectAgent(clientID, disconnect: true) }
            }
            Button("Cancel", role: .cancel) { }
        } message: {
            Text("This removes only the Clipco registration from \(registration?.name ?? agent.rawValue). You can then connect this workspace. \(restartGuidance)")
        }
        .task {
            model.agentConnectionError = nil
            await model.checkMcp()
        }
        .onChange(of: claudeClient) { model.agentConnectionError = nil }
    }

    private func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
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
        if q.count(.waiting) > 0 { parts.append("\(q.count(.waiting)) waiting") }
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
                Text(q?.paused == true ? (q?.active != nil ? "Pausing after the current clip" : "Paused")
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
        case .waiting: "Waiting for Setup or Resources"
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
    @State private var creating = false
    @State private var createdProjectID: String?
    @FocusState private var nameFocused: Bool

    init(footage: [URL]) {
        _sources = State(initialValue: footage)
        _name = State(initialValue: AppModel.suggestedName(for: footage))
    }

    private var trimmedName: String { name.trimmingCharacters(in: .whitespaces) }

    var body: some View {
        Form {
            Section("Project") {
                TextField("Name", text: $name, prompt: Text("Water filter tutorial"))
                    .focused($nameFocused)
                TextField("Context", text: $context, prompt: Text("Optional: what is the intended video about?"),
                          axis: .vertical)
                    .lineLimit(2...4)
            }
            .disabled(createdProjectID != nil)
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
        .disabled(creating)
        .onAppear { nameFocused = true }
        .fileImporter(isPresented: $choosing, allowedContentTypes: [.folder, .movie], allowsMultipleSelection: true) {
            if case .success(let urls) = $0 { sources = urls }
        }
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.disabled(creating) }
            ToolbarItem(placement: .confirmationAction) {
                Button(creating ? "Creating…" : createdProjectID == nil ? "Create" : "Retry Adding Footage") {
                    let (name, context, footage) = (trimmedName, context, sources)
                    creating = true
                    Task {
                        let destination: String
                        if let createdProjectID { destination = createdProjectID }
                        else {
                        guard let created = await model.createProject(name: name, context: context) else {
                            creating = false
                            return
                        }
                        destination = created.id
                        createdProjectID = created.id
                        }
                        let added = footage.isEmpty ? true : await model.enqueue(footage, into: destination)
                        if added { dismiss() }
                        creating = false
                    }
                }
                .disabled(trimmedName.isEmpty || creating)
            }
        }
    }
}
