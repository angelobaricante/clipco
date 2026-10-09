import QuickLook
import SwiftUI

struct ContentView: View {
    @Environment(AppModel.self) private var model
    @FocusState private var searchFocused: Bool

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
                .navigationTitle(model.project?.name ?? "Clipcon")
                .navigationSubtitle(model.trimmedQuery.isEmpty ? model.filter.rawValue : "Search")
                .searchable(text: $model.searchText, placement: .toolbar, prompt: "Search footage context")
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
                Button("Inspector", systemImage: "sidebar.trailing") { model.showInspector.toggle() }
                    .help("Show or hide the inspector (⌘I)")
            }
        }
        .modifier(ProjectDialogs())
        .sheet(isPresented: $model.showImport) { ImportSheet() }
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
                Text("Clipcon deletes the transcript, frame observations, roles, and every Project's notes for "
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
                Text("Clipcon deletes this Project's notes and exclusions. Its footage stays in your Footage "
                     + "library with its analysed context. Your original video files are not affected.")
            }
            #if DEBUG
            // `-ClipconSelectionLog /path` records each selection change, to verify mouse selection from outside.
            .onChange(of: model.selection) {
                guard let path = UserDefaults.standard.string(forKey: "ClipconSelectionLog") else { return }
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
                ForEach([FootageFilter.all, .aRoll, .bRoll]) { filter in
                    FilterRow(filter: filter, count: model.count(filter))
                }
            }
            Section("Review") {
                ForEach([FootageFilter.needsReview, .excluded]) { filter in
                    FilterRow(filter: filter, count: model.count(filter))
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

struct FilterRow: View {
    let filter: FootageFilter
    let count: Int

    var body: some View {
        Label(filter.rawValue, systemImage: filter.symbol)
            .badge(count)
            .tag(SidebarItem.filter(filter))
            .accessibilityLabel("\(filter.rawValue), \(count) \(count == 1 ? "clip" : "clips")")
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
