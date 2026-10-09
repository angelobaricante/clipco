import Foundation
import Observation

enum FootageFilter: String, CaseIterable, Identifiable, Hashable {
    case all = "All Footage", aRoll = "A-roll", bRoll = "B-roll"

    var id: Self { self }

    var symbol: String {
        switch self {
        case .all: "film.stack"
        case .aRoll: "person.wave.2"
        case .bRoll: "photo.on.rectangle"
        }
    }

    func includes(_ clip: SourceClip) -> Bool {
        switch self {
        case .all: true
        case .aRoll: clip.role == "a-roll"
        case .bRoll: clip.role == "b-roll"
        }
    }
}

struct ImportActivity: Equatable {
    var filename: String
    var stage: String
    /// The Source clip currently being analysed, once the worker has registered it.
    var clipID: String?
}

/// Single observable UI state: selection, filter, inspector visibility, and the displayed index snapshot.
@MainActor
@Observable
final class AppModel {
    let worker = WorkerClient()

    var readiness: Readiness?
    var isCheckingReadiness = false
    var projects: [Project] = []
    var project: Project?
    var clips: [SourceClip] = []
    var filter: FootageFilter = .all
    /// Selected Source clips in the browser (Finder-style multiple selection).
    var selection: Set<SourceClip.ID> = []
    /// The clip a ⇧-click range or arrow key starts from: the last one clicked or moved to.
    var selectionAnchor: SourceClip.ID?
    var showInspector = true
    var inspectorTab: InspectorTab = .context
    var showImport = false
    var showSetup = false
    var mcpStatus: McpStatus?
    var isCheckingMcp = false
    var activity: ImportActivity?
    var errorMessage: String?
    /// Awaiting confirmation in a destructive dialog.
    var clipsToRemove: [SourceClip] = []
    var projectToDelete: Project?
    var searchText = ""
    var searchResults: SearchPage?
    var isSearching = false
    /// The selected search result (a Segment); its Source clip is also the browser selection.
    var selectedHit: SearchHit.ID?
    private var reloadGeneration = 0

    var trimmedQuery: String { searchText.trimmingCharacters(in: .whitespaces) }

    var visibleClips: [SourceClip] { clips.filter(filter.includes) }
    /// The one clip the inspector shows; nil when none or several are selected.
    var selectedClip: SourceClip? { selection.count == 1 ? clips.first { selection.contains($0.id) } : nil }
    var selectedClips: [SourceClip] { visibleClips.filter { selection.contains($0.id) } }

    func select(_ id: SourceClip.ID?) {
        selection = id.map { [$0] } ?? []
        selectionAnchor = id
    }
    var canAnalyze: Bool { readiness?.state == .ready || readiness?.state == .cold }

    func count(_ filter: FootageFilter) -> Int { clips.filter(filter.includes).count }

    func start() async {
        async let ready: Void = refreshReadiness()
        do {
            projects = try await worker.projects()
            if let latest = projects.last { try await open(latest) }
        } catch {
            errorMessage = error.localizedDescription
        }
        await ready
    }

    func refreshReadiness() async {
        isCheckingReadiness = true
        defer { isCheckingReadiness = false }
        guard worker.isInstalled else {
            readiness = Readiness(state: .workerUnavailable, detail: "The Clipcon worker is not set up.",
                                  guidance: worker.setupGuidance)
            return
        }
        do {
            readiness = try await worker.readiness()
        } catch {
            readiness = Readiness(state: .workerUnavailable, detail: error.localizedDescription,
                                  guidance: worker.setupGuidance)
        }
    }

    /// Runs a real MCP session with the Codex helper; it reads the saved index and loads no model.
    func checkMcp() async {
        isCheckingMcp = true
        defer { isCheckingMcp = false }
        do {
            mcpStatus = try await worker.mcpStatus()
        } catch {
            mcpStatus = nil
            errorMessage = "Codex connection check failed: \(error.localizedDescription)"
        }
    }

    func warmUp() async {
        do {
            readiness = try await worker.warmUp { [weak self] r in
                await MainActor.run { self?.readiness = r }
            }
        } catch {
            readiness = Readiness(state: .inferenceFailed, detail: error.localizedDescription, guidance: "Retry.")
        }
    }

    func open(_ project: Project) async throws {
        guard project.id != self.project?.id else { return }
        self.project = project
        clips = []
        select(nil)
        selectedHit = nil
        searchText = ""
        searchResults = nil
        try await reload()
        select(visibleClips.first?.id)
    }

    /// Removal and deletion wait while footage is being imported, so an import never re-adds what was removed.
    var canDelete: Bool { activity == nil }

    /// Forgets clips' saved context in Clipcon; the original video files stay where they are.
    func remove(_ doomed: [SourceClip]) async {
        guard let project, canDelete, !doomed.isEmpty else { return }
        let ids = Set(doomed.map(\.id))
        // Like Finder, the selection moves to the clip after the last removed one.
        let after = visibleClips.lastIndex { ids.contains($0.id) }.map { visibleClips[($0 + 1)...] } ?? []
        let next = after.first { !ids.contains($0.id) } ?? visibleClips.last { !ids.contains($0.id) }
        do {
            try await worker.removeClips(projectID: project.id, clipIDs: doomed.map(\.id))
            if !selection.isDisjoint(with: ids) { select(next?.id) }
            try await reload()
            if !trimmedQuery.isEmpty { await search() }
        } catch {
            let what = doomed.count == 1 ? doomed[0].originalFilename : "\(doomed.count) clips"
            errorMessage = "Could not remove \(what): \(error.localizedDescription)"
        }
    }

    /// Forgets a Project and its saved context in Clipcon; the original video files stay where they are.
    func delete(_ doomed: Project) async {
        guard canDelete else { return }
        do {
            try await worker.deleteProject(projectID: doomed.id)
            projects.removeAll { $0.id == doomed.id }
            if project?.id == doomed.id {
                project = nil
                clips = []
                select(nil)
                searchText = ""
                searchResults = nil
                if let latest = projects.last { try await open(latest) }
            }
        } catch {
            errorMessage = "Could not delete \(doomed.name): \(error.localizedDescription)"
        }
    }

    func reload() async throws {
        guard let project else { return }
        reloadGeneration += 1
        let generation = reloadGeneration
        let snapshot = try await worker.snapshot(projectID: project.id)
        guard generation == reloadGeneration else { return }  // a newer reload is already on its way
        clips = snapshot.clips
        // Drop clips that no longer exist; never invent a selection the creator cleared.
        let hadSelection = !selection.isEmpty
        selection.formIntersection(clips.map(\.id))
        if hadSelection && selection.isEmpty { select(visibleClips.first?.id) }
    }

    /// Searches the saved index in a separate worker process: no model starts, and it answers while
    /// another clip is still being analysed.
    func search() async {
        let query = trimmedQuery
        guard let project, !query.isEmpty else {
            searchResults = nil
            return
        }
        isSearching = true
        defer { if query == trimmedQuery { isSearching = false } }
        do {
            let page = try await worker.search(projectID: project.id, query: query)
            if page.query == trimmedQuery { searchResults = page }
        } catch is CancellationError {
            // Superseded by newer typing; its worker process was stopped.
        } catch {
            errorMessage = "Search failed: \(error.localizedDescription)"
        }
    }

    /// Creates a Project when needed, then indexes the chosen Source clips and every video in chosen folders,
    /// while the UI stays interactive. Completed clips are reviewable while the rest are still being analysed.
    func importFootage(_ urls: [URL], newProjectName: String?, context: String) async {
        guard let first = urls.first else { return }
        let accessed = urls.filter { $0.startAccessingSecurityScopedResource() }
        defer { accessed.forEach { $0.stopAccessingSecurityScopedResource() } }
        activity = ImportActivity(filename: urls.count == 1 ? first.lastPathComponent : "\(urls.count) items",
                                  stage: "Starting")
        defer { activity = nil }
        do {
            if readiness?.state == .cold {
                activity?.stage = "Loading model"
                await warmUp()
            }
            guard readiness?.state == .ready else {
                errorMessage = readiness.map { "\($0.detail) \($0.guidance)" } ?? "Local models are not ready."
                return
            }
            if let name = newProjectName {
                let created = try await worker.createProject(name: name, context: context)
                projects.append(created)
                try await open(created)
            }
            guard let project else { return }
            let isFolder = (try? first.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
            let onProgress: @Sendable (WorkerEvent) async -> Void = { [weak self] event in
                await MainActor.run { self?.track(event) }
            }
            if urls.count == 1 && !isFolder {
                let result = try await worker.importClip(projectID: project.id, source: first, onProgress: onProgress)
                try await reload()
                select(result.clipId)
            } else {
                _ = try await worker.importSources(projectID: project.id, sources: urls, onProgress: onProgress)
                try await reload()
            }
            if !trimmedQuery.isEmpty { await search() }
        } catch {
            errorMessage = error.localizedDescription
            if case WorkerError.failed(let kind, let message) = error,
               kind == "InferenceError" || kind == "ServiceUnavailable" {
                readiness = Readiness(state: kind == "ServiceUnavailable" ? .serviceUnavailable : .inferenceFailed,
                                      detail: message, guidance: "Check the Ollama log, then retry the clip.")
            }
            try? await reload()
        }
    }

    /// Follows worker progress: shows newly registered clips, the live stage of the one being analysed,
    /// and each clip's final state as soon as it is published.
    private func track(_ event: WorkerEvent) {
        if event.stage == "pending" {
            activity?.stage = "Found \(event.filename ?? "clip")"
            if !clips.contains(where: { $0.id == event.clipId }) { Task { try? await reload() } }
            return
        }
        activity?.stage = Self.describe(event)
        guard let clipID = event.clipId else { return }
        if activity?.clipID != clipID {
            if let name = clips.first(where: { $0.id == clipID })?.originalFilename { activity?.filename = name }
            activity?.clipID = clipID
            if selection.isEmpty || clips.allSatisfy({ $0.id != clipID }) { select(clipID) }
            Task { try? await reload() }
        }
        if event.stage == "ready" || event.stage == "failed" { Task { try? await reload() } }
    }

    nonisolated static func describe(_ event: WorkerEvent) -> String {
        let step = event.segment.flatMap { s in event.of.map { " \(s) of \($0)" } } ?? ""
        switch event.stage {
        case "fingerprinting": return "Checking source"
        case "probing": return "Measuring media"
        case "extracting_audio": return "Extracting audio"
        case "transcribing": return "Transcribing speech"
        case "sampling_frames": return "Sampling frames" + step
        case "describing": return "Describing segment" + step
        case "saving": return "Saving to index"
        case "ready": return event.reused == true ? "Reused saved context" : "Ready"
        case "failed": return "Failed"
        default: return event.stage ?? "Working"
        }
    }
}
