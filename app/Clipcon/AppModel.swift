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
    var selection: SourceClip.ID?
    var showInspector = true
    var inspectorTab: InspectorTab = .context
    var showImport = false
    var showSetup = false
    var mcpStatus: McpStatus?
    var isCheckingMcp = false
    var activity: ImportActivity?
    var errorMessage: String?
    var searchText = ""
    var searchResults: SearchPage?
    var isSearching = false
    /// The selected search result (a Segment); its Source clip is also the browser selection.
    var selectedHit: SearchHit.ID?
    private var reloadGeneration = 0

    var trimmedQuery: String { searchText.trimmingCharacters(in: .whitespaces) }

    var visibleClips: [SourceClip] { clips.filter(filter.includes) }
    var selectedClip: SourceClip? { clips.first { $0.id == selection } }
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
        self.project = project
        try await reload()
    }

    func reload() async throws {
        guard let project else { return }
        reloadGeneration += 1
        let generation = reloadGeneration
        let snapshot = try await worker.snapshot(projectID: project.id)
        guard generation == reloadGeneration else { return }  // a newer reload is already on its way
        clips = snapshot.clips
        if selection == nil || selectedClip == nil { selection = clips.first?.id }
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

    /// Creates a Project when needed, then indexes one Source clip, or every video in a folder, while the
    /// UI stays interactive. Completed clips are reviewable while the rest are still being analysed.
    func importClip(_ url: URL, newProjectName: String?, context: String) async {
        let accessing = url.startAccessingSecurityScopedResource()
        defer { if accessing { url.stopAccessingSecurityScopedResource() } }
        activity = ImportActivity(filename: url.lastPathComponent, stage: "Starting")
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
            let isFolder = (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
            let onProgress: @Sendable (WorkerEvent) async -> Void = { [weak self] event in
                await MainActor.run { self?.track(event) }
            }
            if isFolder {
                _ = try await worker.importFolder(projectID: project.id, folder: url, onProgress: onProgress)
                try await reload()
            } else {
                let result = try await worker.importClip(projectID: project.id, source: url, onProgress: onProgress)
                try await reload()
                selection = result.clipId
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
            if selection == nil || clips.allSatisfy({ $0.id != clipID }) { selection = clipID }
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
