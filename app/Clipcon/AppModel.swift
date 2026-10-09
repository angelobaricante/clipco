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
    var showImport = false
    var showSetup = false
    var activity: ImportActivity?
    var errorMessage: String?

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
        let snapshot = try await worker.snapshot(projectID: project.id)
        clips = snapshot.clips
        if selection == nil || selectedClip == nil { selection = clips.first?.id }
    }

    /// Creates a Project when needed, then indexes one source clip while the UI stays interactive.
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
            if let name = newProjectName {
                let created = try await worker.createProject(name: name, context: context)
                projects.append(created)
                try await open(created)
            }
            guard let project else { return }
            let result = try await worker.importClip(projectID: project.id, source: url) { [weak self] event in
                await MainActor.run {
                    guard let self else { return }
                    self.activity?.stage = Self.describe(event)
                    // Show the clip (status: indexing) as soon as the worker has registered it.
                    if let clipID = event.clipId, self.selection != clipID {
                        self.selection = clipID
                        Task { try? await self.reload() }
                    }
                }
            }
            try await reload()
            selection = result.clipId
        } catch {
            errorMessage = error.localizedDescription
            try? await reload()
        }
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
