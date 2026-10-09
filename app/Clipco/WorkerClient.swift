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

/// Lets a cancellation handler stop a worker process; `Process` is thread-safe for `terminate()`.
private final class RunningProcess: @unchecked Sendable {
    private let process: Process
    init(_ process: Process) { self.process = process }
    func terminate() { if process.isRunning { process.terminate() } }
}

/// Resumes a waiter once the worker process has exited. `Process.waitUntilExit()` blocks a cooperative thread
/// and can hang there after the process is gone; awaiting the termination handler does neither.
private final class ExitSignal: @unchecked Sendable {
    private let lock = NSLock()
    private var exited = false
    private var waiter: CheckedContinuation<Void, Never>?

    func fire() {
        lock.lock()
        exited = true
        let waiting = waiter
        waiter = nil
        lock.unlock()
        waiting?.resume()
    }

    func wait() async {
        await withCheckedContinuation { continuation in
            lock.lock()
            if exited {
                lock.unlock()
                continuation.resume()
            } else {
                waiter = continuation
                lock.unlock()
            }
        }
    }
}

/// A worker's stdout as lines, read by its own readability handler. (`FileHandle.bytes` reads were observed to
/// wait behind the long-running queue runner's quiet pipe, delaying unrelated calls by many seconds.)
private final class LineReader: @unchecked Sendable {
    private var buffer = Data()

    static func lines(of handle: FileHandle) -> AsyncStream<String> {
        let reader = LineReader()
        return AsyncStream { continuation in
            handle.readabilityHandler = { h in  // calls for one handle are serialized
                let chunk = h.availableData
                guard !chunk.isEmpty else {  // end of output
                    if !reader.buffer.isEmpty { continuation.yield(String(decoding: reader.buffer, as: UTF8.self)) }
                    h.readabilityHandler = nil
                    continuation.finish()
                    return
                }
                reader.buffer.append(chunk)
                while let newline = reader.buffer.firstIndex(of: 0x0A) {
                    continuation.yield(String(decoding: reader.buffer[..<newline], as: UTF8.self))
                    reader.buffer.removeSubrange(...newline)
                }
            }
        }
    }
}

/// Runs the local Python worker as a subprocess and streams its JSON-lines events.
/// All process and pipe work happens off the main actor.
struct WorkerClient: Sendable {
    /// Dev demo layout: the worker lives beside the app sources unless CLIPCO_WORKER_DIR overrides it.
    let workerDirectory: URL = {
        if let dir = ProcessInfo.processInfo.environment["CLIPCO_WORKER_DIR"] {
            return URL(filePath: dir)
        }
        return URL(filePath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().appending(path: "worker")
    }()

    var executable: URL { workerDirectory.appending(path: ".venv/bin/clipco-worker") }

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
        // Reads and creator actions answer at once; the long-running queue runner yields to them.
        process.qualityOfService = arguments.first == "run-queue" ? .utility : .userInitiated
        let stdout = Pipe()
        process.standardOutput = stdout
        process.standardError = Self.logHandle() ?? FileHandle.nullDevice
        let exit = ExitSignal()
        process.terminationHandler = { _ in exit.fire() }
        do {
            try process.run()
        } catch {
            throw WorkerError.unavailable("Could not start the worker: \(error.localizedDescription)")
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        var last: WorkerEvent?
        // A cancelled caller (e.g. a superseded search) stops its worker instead of leaving it running.
        let running = RunningProcess(process)
        try await withTaskCancellationHandler {
            for await line in LineReader.lines(of: stdout.fileHandleForReading) {
                guard let event = try? decoder.decode(WorkerEvent.self, from: Data(line.utf8)) else { continue }
                last = event
                if event.event == "progress" || event.event == "readiness" {
                    await onEvent(event)
                }
            }
        } onCancel: {
            running.terminate()
        }
        await exit.wait()
        try Task.checkCancellation()
        guard let last else { throw WorkerError.noResult }
        if last.event == "error" {
            throw WorkerError.failed(kind: last.kind ?? "Error", message: last.message ?? "Unknown worker error")
        }
        return last
    }

    /// Worker diagnostics (stderr) are appended to ~/.clipco/logs/worker.log.
    private static func logHandle() -> FileHandle? {
        let dir = URL(filePath: NSHomeDirectory()).appending(path: ".clipco/logs")
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

    func connectAgent(_ client: String) async throws -> McpStatus {
        guard let status = try await run(["connect-agent", "--client", client]).mcp else {
            throw WorkerError.noResult
        }
        return status
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

    /// A Project, or the whole Footage library when projectID is nil.
    private static func destination(_ projectID: String?) -> [String] {
        projectID.map { ["--project", $0] } ?? ["--library"]
    }

    /// One Project's clips, or every library source (with its Projects but no Project notes) when nil.
    func snapshot(projectID: String?) async throws -> Snapshot {
        guard let s = try await run(["snapshot"] + Self.destination(projectID)).snapshot else {
            throw WorkerError.noResult
        }
        return s
    }

    /// Reads the saved index only, so it answers while another worker process is analysing footage.
    /// The creator's own Project search also matches excluded clips (marked), so they can be found and restored.
    /// Library scope searches reusable B-roll everywhere, as Codex does, preferring projectID's own footage.
    func search(projectID: String?, query: String, library: Bool = false, offset: Int = 0) async throws -> SearchPage {
        let args = library ? ["search", "--scope", "library", "--query", query] + (projectID.map { ["--project", $0] } ?? [])
                           : ["search", "--project", projectID ?? "", "--query", query, "--include-excluded"]
        guard let page = try await run(args + ["--offset", String(offset)]).search else {
            throw WorkerError.noResult
        }
        return page
    }

    /// Saves the creator's note for a clip through the worker, the index's only writer. Empty text clears it.
    func setNote(projectID: String, clipID: String, text: String) async throws {
        _ = try await run(["set-note", "--project", projectID, "--clip", clipID, "--text", text])
    }

    /// Adds library sources to another Project, reusing their analysis (no inference).
    func addToProject(projectID: String, clipIDs: [String]) async throws {
        _ = try await run(["add-to-project", "--project", projectID] + clipIDs)
    }

    /// Allows or prevents reuse of sources as B-roll outside their own Projects. Reversible.
    func setReuse(clipIDs: [String], allowed: Bool) async throws {
        _ = try await run(["set-reuse", "--allowed", allowed ? "yes" : "no"] + clipIDs)
    }

    /// Records the creator's role for a Segment; nil clears it so the suggested role applies again.
    func setSegmentRole(segmentID: String, role: String?) async throws {
        _ = try await run(["set-segment-role", "--segment", segmentID, "--role", role ?? "suggested"])
    }

    /// Records the creator's emotional tones for a Segment (an empty list says it has none); nil clears them so
    /// the suggestions apply again. The model's suggestions and evidence are never rewritten.
    func setSegmentTones(segmentID: String, tones: [String]?) async throws {
        let choice = tones.map { ["--tones", $0.joined(separator: ",")] } ?? ["--suggested"]
        _ = try await run(["set-segment-tones", "--segment", segmentID] + choice)
    }

    /// Reads emotional tone, one clip after another, for Segments that have none yet. Only saved evidence is
    /// used: nothing is re-transcribed or re-described.
    func enrichTone(projectID: String?, clipIDs: [String],
                    onProgress: @escaping @Sendable (WorkerEvent) async -> Void) async throws -> WorkerEvent {
        try await run(["enrich-tone"] + Self.destination(projectID) + clipIDs, onEvent: onProgress)
    }

    /// Forgets sources everywhere: saved context, every Project membership, and the frame cache. Originals stay.
    func removeFromLibrary(clipIDs: [String]) async throws {
        _ = try await run(["remove-from-library"] + clipIDs)
    }

    /// Excludes clips from, or restores them to, new default search results. No context is deleted.
    func setExcluded(projectID: String, clipIDs: [String], excluded: Bool) async throws {
        _ = try await run(["set-excluded", "--project", projectID, "--excluded", excluded ? "yes" : "no"] + clipIDs)
    }

    /// Removes clips from one Project (its note and exclusion for them). Their library context is kept.
    func removeClips(projectID: String, clipIDs: [String]) async throws {
        _ = try await run(["remove-clips", "--project", projectID] + clipIDs)
    }

    /// Forgets a Project, its notes and exclusions. Its footage stays in the library; originals are never touched.
    func deleteProject(projectID: String) async throws {
        _ = try await run(["delete-project", "--project", projectID])
    }

    /// Imports chosen video files and every video inside chosen folders into one Project.
    func importSources(projectID: String, sources: [URL],
                       onProgress: @escaping @Sendable (WorkerEvent) async -> Void) async throws -> WorkerEvent {
        try await run(["import-sources", "--project", projectID] + sources.map(\.path), onEvent: onProgress)
    }

    /// Re-verifies analysed clips' originals: missing ones become missing, changed content or analysis settings
    /// make them stale, and originals that are back and unchanged make them ready again. Context is kept.
    func checkSources(projectID: String?,
                      onProgress: @escaping @Sendable (WorkerEvent) async -> Void = { _ in }) async throws {
        _ = try await run(["check-sources"] + Self.destination(projectID), onEvent: onProgress)
    }

    /// Re-analyses clips from their originals, keeping each clip's ID, note, and exclusion.
    func retry(projectID: String?, clipIDs: [String],
               onProgress: @escaping @Sendable (WorkerEvent) async -> Void) async throws -> WorkerEvent {
        try await run(["retry"] + Self.destination(projectID) + clipIDs, onEvent: onProgress)
    }

    /// Points a clip at its original in a new location. The worker accepts only the same content.
    func relink(projectID: String?, clipID: String, source: URL) async throws {
        _ = try await run(["relink"] + Self.destination(projectID) + ["--clip", clipID, source.path])
    }

    // The recoverable analysis queue

    /// Registers videos (and every video in folders) in the destination at once and queues their analysis.
    /// Needs no model or service; unsupported and inaccessible items come back as skipped.
    func enqueue(projectID: String?, sources: [URL]) async throws -> WorkerEvent {
        try await run(["enqueue"] + Self.destination(projectID) + sources.map(\.path))
    }

    /// Queues re-analysis or emotional-tone reading of clips the destination already has.
    func enqueue(operation: String, projectID: String?, clipIDs: [String]) async throws -> WorkerEvent {
        try await run(["enqueue-clips", "--operation", operation] + Self.destination(projectID) + clipIDs)
    }

    /// Runs queued jobs one at a time until none is left, the queue is paused, or setup is missing.
    /// Returns at once when another runner already owns the queue.
    func runQueue(onProgress: @escaping @Sendable (WorkerEvent) async -> Void) async throws -> WorkerEvent {
        try await run(["run-queue"], onEvent: onProgress)
    }

    /// One of: jobs, reconcile, pause, resume, clear-jobs. Each returns the queue.
    func queue(_ command: String) async throws -> QueueState {
        guard let q = try await run([command]).queue else { throw WorkerError.noResult }
        return q
    }

    /// cancel or retry-jobs for chosen jobs; returns the queue.
    func queue(_ command: String, jobIDs: [String]) async throws -> QueueState {
        guard let q = try await run([command] + jobIDs).queue else { throw WorkerError.noResult }
        return q
    }

    func importClip(projectID: String, source: URL,
                    onProgress: @escaping @Sendable (WorkerEvent) async -> Void) async throws -> WorkerEvent {
        try await run(["import", "--project", projectID, source.path], onEvent: onProgress)
    }
}
