import SwiftUI

struct ContentView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        NavigationSplitView {
            SidebarView()
                .navigationSplitViewColumnWidth(min: 190, ideal: 220)
        } detail: {
            BrowserView()
                .navigationTitle(model.project?.name ?? "Clipcon")
                .navigationSubtitle(model.trimmedQuery.isEmpty ? model.filter.rawValue : "Search")
                .searchable(text: $model.searchText, placement: .toolbar, prompt: "Search footage context")
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
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button("Import", systemImage: "square.and.arrow.down") { model.showImport = true }
                    .help("Import a footage folder or source clip (⇧⌘I)")
            }
            ToolbarItem(placement: .primaryAction) {
                Button("Inspector", systemImage: "sidebar.trailing") { model.showInspector.toggle() }
                    .help("Show or hide the inspector (⌘I)")
            }
        }
        .confirmationDialog(
            "Remove “\(model.clipToRemove?.originalFilename ?? "")” from this Project?",
            isPresented: Binding(get: { model.clipToRemove != nil }, set: { if !$0 { model.clipToRemove = nil } }),
            presenting: model.clipToRemove
        ) { clip in
            Button("Remove from Project", role: .destructive) { Task { await model.remove(clip) } }
        } message: { _ in
            Text("Clipcon deletes its transcript, frame observations, and suggested relationships for this clip. "
                 + "The original video file stays where it is.")
        }
        .confirmationDialog(
            "Delete the Project “\(model.projectToDelete?.name ?? "")”?",
            isPresented: Binding(get: { model.projectToDelete != nil }, set: { if !$0 { model.projectToDelete = nil } }),
            presenting: model.projectToDelete
        ) { project in
            Button("Delete Project", role: .destructive) { Task { await model.delete(project) } }
        } message: { _ in
            Text("Clipcon deletes the saved context for every clip in this Project, and Codex can no longer "
                 + "retrieve it. Your original video files are not affected.")
        }
        .sheet(isPresented: $model.showImport) { ImportSheet() }
        .sheet(isPresented: $model.showSetup) { SetupSheet() }
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
}

struct SidebarView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        List(selection: Binding<SidebarItem?>(
            get: { .filter(model.filter) },
            set: { item in
                switch item {
                case .filter(let filter): model.filter = filter
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
                ForEach(FootageFilter.allCases) { filter in
                    Label(filter.rawValue, systemImage: filter.symbol)
                        .badge(model.count(filter))
                        .tag(SidebarItem.filter(filter))
                }
            }
            if !model.projects.isEmpty {
                Section("Projects") {
                    ForEach(model.projects) { project in
                        let isOpen = project.id == model.project?.id
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
                if let activity = model.activity {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        VStack(alignment: .leading) {
                            Text(activity.filename).lineLimit(1).truncationMode(.middle)
                            Text(activity.stage).foregroundStyle(.secondary)
                        }
                        .font(.caption)
                    }
                    .accessibilityElement(children: .combine)
                }
                ReadinessBadge()
            }
            .padding(12)
        }
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
