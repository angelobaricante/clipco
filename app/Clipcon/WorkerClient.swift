import Foundation

enum WorkerError: LocalizedError {
    case unavailable(String)
    case failed(kind: String, message: String)
    case noResult

    var errorDescription: String? {
        switch self {
        case .unavailable(let detail): detail
        case .failed(_, let message): message
        case .noResult: "The worker exited without a result."
        }
    }
}

/// Runs the local Python worker as a subprocess and streams its JSON-lines events.
/// All process and pipe work happens off the main actor.
struct WorkerClient: Sendable {
    /// Dev demo layout: the worker lives beside the app sources unless CLIPCON_WORKER_DIR overrides it.
    let workerDirectory: URL = {
        if let dir = ProcessInfo.processInfo.environment["CLIPCON_WORKER_DIR"] {
            return URL(filePath: dir)
        }
        return URL(filePath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().appending(path: "worker")
    }()

    var executable: URL { workerDirectory.appending(path: ".venv/bin/clipcon-worker") }

    var isInstalled: Bool { FileManager.default.isExecutableFile(atPath: executable.path) }

    var setupGuidance: String { "Set up the worker: cd \(workerDirectory.path) && uv sync" }

    @concurrent
    func run(_ arguments: [String], onEvent: @escaping @Sendable (WorkerEvent) async -> Void = { _ in })
        async throws -> WorkerEvent
    {
        guard isInstalled else {
            throw WorkerError.unavailable("Worker not found at \(executable.path). \(setupGuidance)")
        }
        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        var environment = ProcessInfo.processInfo.environment
        // GUI apps start with a minimal PATH; FFmpeg and whisper.cpp come from Homebrew.
        environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + (environment["PATH"] ?? "/usr/bin:/bin")
        process.environment = environment
        let stdout = Pipe()
        process.standardOutput = stdout
        process.standardError = Self.logHandle() ?? FileHandle.nullDevice
        do {
            try process.run()
        } catch {
            throw WorkerError.unavailable("Could not start the worker: \(error.localizedDescription)")
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        var last: WorkerEvent?
        for try await line in stdout.fileHandleForReading.bytes.lines {
            guard let event = try? decoder.decode(WorkerEvent.self, from: Data(line.utf8)) else { continue }
            last = event
            if event.event == "progress" || event.event == "readiness" {
                await onEvent(event)
            }
        }
        process.waitUntilExit()
        guard let last else { throw WorkerError.noResult }
        if last.event == "error" {
            throw WorkerError.failed(kind: last.kind ?? "Error", message: last.message ?? "Unknown worker error")
        }
        return last
    }

    /// Worker diagnostics (stderr) are appended to ~/.clipcon/logs/worker.log.
    private static func logHandle() -> FileHandle? {
        let dir = URL(filePath: NSHomeDirectory()).appending(path: ".clipcon/logs")
        let log = dir.appending(path: "worker.log")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: log.path) {
            FileManager.default.createFile(atPath: log.path, contents: nil)
        }
        let handle = try? FileHandle(forWritingTo: log)
        _ = try? handle?.seekToEnd()
        return handle
    }

    func readiness() async throws -> Readiness {
        guard let r = try await run(["readiness"]).readiness else { throw WorkerError.noResult }
        return r
    }

    func warmUp(onReadiness: @escaping @Sendable (Readiness) async -> Void) async throws -> Readiness {
        let result = try await run(["warmup"]) { event in
            if let r = event.readiness { await onReadiness(r) }
        }
        guard let r = result.readiness else { throw WorkerError.noResult }
        return r
    }

    func mcpStatus() async throws -> McpStatus {
        guard let s = try await run(["mcp-status"]).mcp else { throw WorkerError.noResult }
        return s
    }

    func projects() async throws -> [Project] {
        try await run(["projects"]).projects ?? []
    }

    func createProject(name: String, context: String) async throws -> Project {
        guard let p = try await run(["create-project", "--name", name, "--context", context]).project else {
            throw WorkerError.noResult
        }
        return p
    }

    func snapshot(projectID: String) async throws -> Snapshot {
        guard let s = try await run(["snapshot", "--project", projectID]).snapshot else { throw WorkerError.noResult }
        return s
    }

    func importClip(projectID: String, source: URL,
                    onProgress: @escaping @Sendable (WorkerEvent) async -> Void) async throws -> WorkerEvent {
        try await run(["import", "--project", projectID, source.path], onEvent: onProgress)
    }
}
