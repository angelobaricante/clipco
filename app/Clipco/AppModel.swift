import Foundation
import Observation

enum FootageFilter: String, CaseIterable, Identifiable, Hashable {
    case all = "All Footage", aRoll = "A-roll", bRoll = "B-roll", needsReview = "Needs Review", excluded = "Excluded"
    case reusable = "Reusable B-roll"

    var id: Self { self }

    var symbol: String {
        switch self {
        case .all: "film.stack"
        case .aRoll: "person.wave.2"
        case .bRoll: "photo.on.rectangle"
        case .needsReview: "exclamationmark.bubble"
        case .excluded: "eye.slash"
        case .reusable: "square.stack.3d.up"
        }
    }

    func includes(_ clip: SourceClip) -> Bool {
        switch self {
        case .all: true
        case .aRoll: clip.containsRole("a-roll")
        case .bRoll: clip.containsRole("b-roll")
        case .needsReview: clip.needsReview
        case .excluded: clip.excluded
        case .reusable: clip.reuseAllowed && clip.segments.contains(where: \.isReusableBRoll)
        }
    }
}

enum BrowserMode: String, CaseIterable, Identifiable {
    case grid = "Grid", list = "List"
    var id: Self { self }
    var symbol: String { self == .grid ? "square.grid.2x2" : "list.bullet" }
}

/// Whether the original file can be opened: it must be where it was indexed, with the same size and
/// modification time, or the saved context may not describe what would play.
enum SourceAccess: Equatable {
    case available(URL)
    case unverified, missing, changed

    @concurrent
    static func check(_ clip: SourceClip) async -> SourceAccess {
        guard let size = clip.sizeBytes, let mtime = clip.mtime else { return .unverified }
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: clip.sourcePath) else {
            return .missing
        }
        let modified = (attributes[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0
        guard (attributes[.size] as? Int) == size, abs(modified - mtime) <= 1e-3 else { return .changed }
        return .available(URL(filePath: clip.sourcePath))
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
    /// The browser shows reusable B-roll from the whole Footage library; `project` stays the Project being
    /// edited, whose own footage library search prefers.
    var showingLibrary = false
    /// The worker destination of the shown clips: the open Project, or the library (nil).
    var scopeProjectID: String? { showingLibrary ? nil : project?.id }
    /// Something is open to browse: a Project, or the library.
    var hasScope: Bool { project != nil || showingLibrary }
    var clips: [SourceClip] = []
    var filter: FootageFilter = .all {
        didSet { if filter != oldValue { reconcileSelection() } }
    }
    /// Selected Source clips in the browser (Finder-style multiple selection).
    var selection: Set<SourceClip.ID> = []
    /// The clip a ⇧-click range or arrow key starts from: the last one clicked or moved to.
    var selectionAnchor: SourceClip.ID?
    var showInspector = UserDefaults.standard.object(forKey: "showInspector") as? Bool ?? true {
        didSet { UserDefaults.standard.set(showInspector, forKey: "showInspector") }
    }
    var browserMode = BrowserMode(rawValue: UserDefaults.standard.string(forKey: "browserMode") ?? "") ?? .grid {
        didSet { UserDefaults.standard.set(browserMode.rawValue, forKey: "browserMode") }
    }
    /// The original shown in the system Quick Look panel (Space, or double-click), once its source is verified.
    var quickLookURL: URL?
    let player = PreviewPlayer()
    /// The clip playing over the browser (double-click or Space); nil when the player is closed.
    var playingClipID: SourceClip.ID?
    /// Incremented to move keyboard focus to the toolbar search field (⌘F).
    var searchFocusRequest = 0
    var browserFocusRequest = 0
    var followPlayback = true
    var isLoadingScope = false
    var isStarting = true
    var inspectorTab: InspectorTab = .context
    var showImport = false
    var showSetup = false
    var mcpStatus: McpStatus?
    var isCheckingMcp = false
    var agentConnection: EditingAgent?
    var connectingClient: String?
    var agentConnectionError: String?
    /// The queue's active job as the sidebar and browser show it; nil when nothing is running.
    var activity: ImportActivity?
    /// The recoverable analysis queue: every job with its state, and whether it is paused or running.
    var queue: QueueState?
    var showActivity = false
    /// New Project sheet; footage dropped on an empty workspace arrives prefilled with a suggested name.
    var showNewProject = false
    var newProjectFootage: [URL] = []
    /// What the last drop or import registered and skipped, shown until dismissed.
    var importNotice: String?
    private var runner: Task<Void, Never>?
    /// A run was asked for while the runner was finishing (e.g. Resume right after a pause took effect).
    private var runRequested = false
    var isCheckingSources = false
    var errorMessage: String?
    /// Awaiting confirmation in a destructive dialog.
    var clipsToRemove: [SourceClip] = []
    var clipsToRemoveFromLibrary: [SourceClip] = []
    var projectToDelete: Project?
    var searchText = "" {
        didSet {
            if trimmedQuery.isEmpty {
                searchGeneration += 1
                searchResults = nil
                selectedHit = nil
                isSearching = false
                reconcileSelection()
            }
        }
    }
    var searchResults: SearchPage?
    var isSearching = false
    /// The selected search result (a Segment); its Source clip is also the browser selection.
    var selectedHit: SearchHit.ID?
    private var reloadGeneration = 0
    private var scopeGeneration = 0
    private var searchGeneration = 0
    var pendingUpdates: Set<String> = []
    var updateErrors: [String: String] = [:]
    var noteDrafts: [String: String] = [:]

    var trimmedQuery: String { searchText.trimmingCharacters(in: .whitespaces) }

    var visibleClips: [SourceClip] { clips.filter(filter.includes) }
    /// The one clip the inspector shows; nil when none or several are selected.
    var selectedClip: SourceClip? {
        selection.count == 1 ? selectionClips.first { selection.contains($0.id) } : nil
    }
    private var selectionClips: [SourceClip] {
        trimmedQuery.isEmpty ? visibleClips : clips.filter { clip in
            searchResults?.results.contains { $0.clipId == clip.id } == true
        }
    }
    var selectedClips: [SourceClip] { visibleClips.filter { selection.contains($0.id) } }

    func select(_ id: SourceClip.ID?) {
        selection = id.map { [$0] } ?? []
        selectionAnchor = id
    }

    func reconcileSelection() {
        selection.formIntersection(selectionClips.map(\.id))
        if !selection.contains(selectionAnchor ?? "") { selectionAnchor = selection.first }
        if let playingClipID, !selection.contains(playingClipID) { closePlayer() }
    }
    var canAnalyze: Bool { readiness?.state == .ready || readiness?.state == .cold }

    func count(_ filter: FootageFilter) -> Int { clips.filter(filter.includes).count }

    func analysisStatus(_ clip: SourceClip) -> String {
        if let job = queue?.jobs.last(where: {
            $0.clipId == clip.id && ["import", "reanalyse"].contains($0.operation)
                && [.queued, .active, .waiting, .interrupted].contains($0.state)
        }) {
            switch job.state {
            case .queued: return queue?.paused == true ? "Paused" : "Queued"
            case .active: return activity?.clipID == clip.id ? activity?.stage ?? "Analyzing" : "Analyzing"
            case .waiting: return "Waiting for setup or resources"
            case .interrupted: return "Interrupted · resume to continue"
            default: break
            }
        }
        switch clip.status {
        case .pending: return "Not analyzed"
        case .stale: return "Out of date"
        case .missing: return "Original not found"
        case .failed: return clip.error?.localizedCaseInsensitiveContains("cancelled") == true ? "Cancelled" : "Failed"
        case .indexing: return "Analyzing"
        case .ready: return "Ready"
        }
    }

    func start() async {
        defer { isStarting = false }
        async let ready: Void = refreshReadiness()
        do {
            // Work a previous session left unfinished is marked interrupted, to resume only when asked.
            queue = try await worker.queue("reconcile")
            if queue?.running == true { runQueue() }  // follow it; this runner returns at once
            projects = try await worker.projects()
            let lastScope = UserDefaults.standard.string(forKey: "lastScope")
            if lastScope == "library" { await openLibrary() }
            else if let latest = projects.first(where: { $0.id == lastScope }) ?? projects.last {
                try await open(latest)
            }
        } catch {
            errorMessage = error.localizedDescription
        }
        await ready
    }

    func refreshReadiness() async {
        isCheckingReadiness = true
        defer { isCheckingReadiness = false }
        guard worker.isInstalled else {
            readiness = Readiness(state: .workerUnavailable, detail: "The Clipco worker is not set up.",
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
        guard !isCheckingMcp, connectingClient == nil else { return }
        isCheckingMcp = true
        agentConnectionError = nil
        defer { isCheckingMcp = false }
        do {
            mcpStatus = try await worker.mcpStatus()
        } catch {
            mcpStatus = nil
            agentConnectionError = "Couldn’t check agent setup: \(error.localizedDescription)"
        }
    }

    func connectAgent(_ client: String, disconnect: Bool = false) async {
        guard connectingClient == nil, !isCheckingMcp else { return }
        connectingClient = client
        agentConnectionError = nil
        defer { connectingClient = nil }
        do {
            mcpStatus = try await worker.connectAgent(client, disconnect: disconnect)
        } catch {
            agentConnectionError = error.localizedDescription
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

    /// Saves the creator's note through the worker; Codex sees it in the next retrieval.
    @discardableResult
    func saveNote(_ text: String, for clipID: SourceClip.ID, projectID: String? = nil) async -> Bool {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let destination = projectID ?? scopeProjectID else { return false }
        let key = "note:\(destination):\(clipID)"
        guard pendingUpdates.insert(key).inserted else { return false }
        defer { pendingUpdates.remove(key) }
        updateErrors[key] = nil
        noteDrafts[key] = text
        do {
            try await worker.setNote(projectID: destination, clipID: clipID, text: trimmed)
            if noteDrafts[key] == text { noteDrafts[key] = nil }
            if scopeProjectID == destination {
                try await reload()
                if !trimmedQuery.isEmpty { await search() }
            }
            return true
        } catch {
            updateErrors[key] = "Could not save. \(error.localizedDescription)"
            return false
        }
    }

    /// Excludes clips from (or restores them to) new default search results. Reversible; nothing is deleted.
    func setExcluded(_ targets: [SourceClip], _ excluded: Bool, projectID: String? = nil) async {
        guard let destination = projectID ?? scopeProjectID, !targets.isEmpty else { return }
        let keys = targets.map { "exclude:\(destination):\($0.id)" }
        guard keys.allSatisfy({ !pendingUpdates.contains($0) }) else { return }
        pendingUpdates.formUnion(keys)
        defer { pendingUpdates.subtract(keys) }
        do {
            try await worker.setExcluded(projectID: destination, clipIDs: targets.map(\.id), excluded: excluded)
            guard scopeProjectID == destination else { return }
            try await reload()
            // Under the Excluded filter, an included clip leaves the browser, so it leaves the selection too.
            let shown = Set(visibleClips.map(\.id))
            if !selection.isSubset(of: shown) {
                selection.formIntersection(shown)
                if selection.isEmpty { select(visibleClips.first?.id) }
            }
            if !trimmedQuery.isEmpty { await search() }
        } catch {
            errorMessage = "Could not \(excluded ? "exclude" : "include") the clip: \(error.localizedDescription)"
        }
    }

    /// Allows or prevents reuse of a clip's footage outside its own Projects (source-wide, reversible).
    func setReuse(_ clip: SourceClip, _ allowed: Bool) async {
        let key = "reuse:\(clip.id)"
        guard pendingUpdates.insert(key).inserted else { return }
        defer { pendingUpdates.remove(key) }
        do {
            try await worker.setReuse(clipIDs: [clip.id], allowed: allowed)
            try await reload()
        } catch {
            errorMessage = "Could not change reuse for \(clip.originalFilename): \(error.localizedDescription)"
        }
    }

    /// Adds clips to another Project: one shared analysis, a new membership with its own note and exclusion.
    func addToProject(_ targets: [SourceClip], _ destination: Project) async {
        do {
            try await worker.addToProject(projectID: destination.id, clipIDs: targets.map(\.id))
            try await reload()
        } catch {
            errorMessage = "Could not add to \(destination.name): \(error.localizedDescription)"
        }
    }

    /// Records the creator's emotional tones for one Segment (nil returns it to the suggestions).
    func setTones(_ tones: [String]?, for segment: Segment) async {
        let key = "tone:\(segment.id)"
        guard pendingUpdates.insert(key).inserted else { return }
        defer { pendingUpdates.remove(key) }
        do {
            try await worker.setSegmentTones(segmentID: segment.id, tones: tones)
            try await reload()
            if !trimmedQuery.isEmpty { await search() }
        } catch {
            errorMessage = "Could not change the segment's tone: \(error.localizedDescription)"
        }
    }

    /// Ready clips with Segments not yet read for emotional tone, and no tone job already waiting for them.
    func canEnrichTone(_ targets: [SourceClip]) -> Bool {
        targets.contains { clip in
            clip.status == .ready && clip.segments.contains { $0.tone.state == "not_analyzed" }
                && !hasUnfinishedJob(clip.id, operations: ["enrich_tone"])
        }
    }

    /// Queues emotional-tone reading of the chosen clips from their saved evidence. Only what the creator asks
    /// for is enriched; nothing else in the library is upgraded.
    func enrichTone(_ targets: [SourceClip]) async {
        guard canEnrichTone(targets) else { return }
        await enqueue(operation: "enrich_tone", targets)
    }

    func hasUnfinishedJob(_ clipID: SourceClip.ID, operations: Set<String>) -> Bool {
        queue?.jobs.contains {
            $0.clipId == clipID && operations.contains($0.operation)
                && [.queued, .active, .waiting, .interrupted].contains($0.state)
        } ?? false
    }

    /// Records the creator's role for one Segment (nil returns it to the suggested role).
    func setRole(_ role: String?, for segment: Segment) async {
        let key = "role:\(segment.id)"
        guard pendingUpdates.insert(key).inserted else { return }
        defer { pendingUpdates.remove(key) }
        do {
            try await worker.setSegmentRole(segmentID: segment.id, role: role)
            try await reload()
        } catch {
            errorMessage = "Could not change the segment's role: \(error.localizedDescription)"
        }
    }

    /// The clips menu commands act on: the browser selection.
    var commandTargets: [SourceClip] { selectionClips.filter { selection.contains($0.id) } }

    /// Opens the selected clip's original in Quick Look after checking it is the file that was indexed.
    func quickLook() async {
        guard let clip = selectedClip else { return }
        let access = await SourceAccess.check(clip)
        if case .available(let url) = access { quickLookURL = url } else {
            errorMessage = "\(clip.originalFilename): \(access.detail)"
        }
    }

    /// Opens the player over the browser for one clip (optionally from a source-relative time). The inspector
    /// stays beside it showing that clip.
    func openPlayer(_ id: SourceClip.ID, at seconds: Double? = nil) async {
        guard let clip = clips.first(where: { $0.id == id }) else { return }
        if selection != [id] { select(id) }
        playingClipID = id
        await player.show(clip)
        guard playingClipID == id, case .available? = player.access else { return }
        player.play(from: seconds ?? player.currentTime ?? 0)
    }

    /// Space in the browser: plays the one selected clip. Returns false when there is nothing to play.
    func playSelectedClip() -> Bool {
        guard let id = selectedClip?.id else { return false }
        let start = searchResults?.results.first { $0.id == selectedHit && $0.clipId == id }?.start
        Task { await openPlayer(id, at: start) }
        return true
    }

    func closePlayer() {
        player.pause()
        playingClipID = nil
        browserFocusRequest += 1
    }

    /// The transcript line spoken at the player's position, while the player shows this clip.
    func spokenLineID(in clip: SourceClip) -> Segment.Line.ID? {
        guard playingClipID == clip.id, player.clipID == clip.id, let t = player.currentTime else { return nil }
        return clip.segments.lazy.flatMap(\.transcript).first { $0.start <= t && t < $0.end }?.id
    }

    func open(_ project: Project) async throws {
        guard project.id != self.project?.id || showingLibrary else { return }
        scopeGeneration += 1
        let generation = scopeGeneration
        isLoadingScope = true
        defer { if scopeGeneration == generation { isLoadingScope = false } }
        closePlayer()
        showingLibrary = false
        if filter == .reusable { filter = .all }
        self.project = project
        clips = []
        select(nil)
        selectedHit = nil
        searchText = ""
        searchResults = nil
        isSearching = false
        try await reload()
        guard generation == scopeGeneration else { return }
        select(visibleClips.first?.id)
        UserDefaults.standard.set(project.id, forKey: "lastScope")
        await checkSources()
    }

    /// Shows reusable B-roll from every Project and standalone library footage.
    func openLibrary() async {
        guard !showingLibrary else { return }
        scopeGeneration += 1
        let generation = scopeGeneration
        isLoadingScope = true
        defer { if scopeGeneration == generation { isLoadingScope = false } }
        closePlayer()
        showingLibrary = true
        filter = .reusable
        clips = []
        select(nil)
        selectedHit = nil
        searchText = ""
        searchResults = nil
        isSearching = false
        do {
            try await reload()
            guard generation == scopeGeneration else { return }
            select(visibleClips.first?.id)
            UserDefaults.standard.set("library", forKey: "lastScope")
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Re-verifies every analysed clip's original (moved, deleted, edited, or restored) and the analysis
    /// settings, then shows the result. Skipped while an import or retry is writing the index.
    func checkSources() async {
        guard hasScope, queue?.active == nil else { return }
        isCheckingSources = true
        defer { isCheckingSources = false }
        do {
            try await worker.checkSources(projectID: scopeProjectID)
            try await reload()
        } catch {
            errorMessage = "Could not check the original files: \(error.localizedDescription)"
        }
    }

    /// Clips whose context is not current and that a re-analysis could refresh.
    func canRetry(_ targets: [SourceClip]) -> Bool {
        !targets.isEmpty && targets.allSatisfy {
            [.failed, .stale, .missing].contains($0.status)
                && !hasUnfinishedJob($0.id, operations: ["import", "reanalyse"])
        }
    }

    /// Queues re-analysis of clips from their originals. Each keeps its ID, note, and exclusion; unchanged
    /// content is reused without inference, and a missing original is reported, not analysed.
    func retry(_ targets: [SourceClip]) async {
        guard hasScope, canRetry(targets) else { return }
        await enqueue(operation: "reanalyse", targets)
    }

    private func enqueue(operation: String, _ targets: [SourceClip]) async {
        do {
            let result = try await worker.enqueue(operation: operation, projectID: scopeProjectID,
                                                  clipIDs: targets.map(\.id))
            queue = result.queue ?? queue
            runQueue()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Points a missing clip at the same original in its new place; a different file is refused by the worker.
    func locate(_ clip: SourceClip, at url: URL) async {
        guard hasScope else { return }
        let destination = scopeProjectID
        let accessed = url.startAccessingSecurityScopedResource()
        defer { if accessed { url.stopAccessingSecurityScopedResource() } }
        do {
            try await worker.relink(projectID: destination, clipID: clip.id, source: url)
            try await reload()
            if !trimmedQuery.isEmpty { await search() }
        } catch {
            errorMessage = "Could not use \(url.lastPathComponent) for \(clip.originalFilename): "
                + error.localizedDescription
        }
    }

    /// Removal and deletion are safe while jobs run: the worker resolves a removed source's jobs, and an
    /// in-flight analysis cannot publish it again.
    var canDelete: Bool { true }

    /// Forgets clips' saved context in Clipco; the original video files stay where they are.
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

    /// Forgets clips' saved context everywhere (every Project and the library); the originals stay where they are.
    func removeFromLibrary(_ doomed: [SourceClip]) async {
        guard canDelete, !doomed.isEmpty else { return }
        let ids = Set(doomed.map(\.id))
        do {
            try await worker.removeFromLibrary(clipIDs: doomed.map(\.id))
            if !selection.isDisjoint(with: ids) { select(visibleClips.first { !ids.contains($0.id) }?.id) }
            try await reload()
            if !trimmedQuery.isEmpty { await search() }
        } catch {
            let what = doomed.count == 1 ? doomed[0].originalFilename : "\(doomed.count) clips"
            errorMessage = "Could not remove \(what) from the library: \(error.localizedDescription)"
        }
    }

    /// Forgets a Project, its notes and exclusions; its footage stays in the library and originals are untouched.
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
        guard hasScope else { return }
        reloadGeneration += 1
        let generation = reloadGeneration
        let snapshot = try await worker.snapshot(projectID: scopeProjectID)
        guard generation == reloadGeneration else { return }  // a newer reload is already on its way
        clips = snapshot.clips
        // Drop clips that no longer exist; never invent a selection the creator cleared.
        let hadSelection = !selection.isEmpty
        reconcileSelection()
        if hadSelection && selection.isEmpty { select(visibleClips.first?.id) }
    }

    /// Searches the saved index in a separate worker process: no model starts, and it answers while
    /// another clip is still being analysed.
    func search(loadMore: Bool = false) async {
        let query = trimmedQuery
        searchGeneration += 1
        let generation = searchGeneration
        let scope = scopeGeneration
        guard hasScope, !query.isEmpty else {
            searchResults = nil
            isSearching = false
            selectedHit = nil
            reconcileSelection()
            return
        }
        let previous = loadMore ? searchResults : nil
        let offset = previous?.nextOffset ?? 0
        isSearching = true
        defer { if generation == searchGeneration { isSearching = false } }
        do {
            var page = try await worker.search(projectID: showingLibrary ? nil : project?.id,
                                              query: query, library: showingLibrary, offset: offset)
            guard generation == searchGeneration, scope == scopeGeneration, query == trimmedQuery else { return }
            if let previous, previous.query == page.query {
                let seen = Set(previous.results.map(\.id))
                page.results = previous.results + page.results.filter { !seen.contains($0.id) }
            }
            searchResults = page
            if !page.results.contains(where: { $0.id == selectedHit }) { selectedHit = nil }
            reconcileSelection()
        } catch is CancellationError {
            // Superseded by newer typing; its worker process was stopped.
        } catch {
            if generation == searchGeneration, scope == scopeGeneration {
                errorMessage = "Search failed: \(error.localizedDescription)"
            }
        }
    }

    /// Creates a Project. Only a name is needed: no model is loaded and no inference service is required.
    @discardableResult
    func createProject(name: String, context: String) async -> Project? {
        do {
            let created = try await worker.createProject(name: name, context: context)
            projects.append(created)
            try await open(created)
            return created
        } catch {
            errorMessage = "Could not create \(name): \(error.localizedDescription)"
            return nil
        }
    }

    /// A Project name suggested from dropped footage: a dropped folder's name, the one file's name, or the
    /// folder the files share.
    nonisolated static func suggestedName(for urls: [URL]) -> String {
        if let folder = urls.first(where: isFolder) { return folder.lastPathComponent }
        guard let first = urls.first else { return "" }
        if urls.count == 1 { return first.deletingPathExtension().lastPathComponent }
        return first.deletingLastPathComponent().lastPathComponent
    }

    /// Whether a dropped or chosen item is a folder (a dropped folder's URL may lack the trailing slash).
    nonisolated static func isFolder(_ url: URL) -> Bool {
        (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
    }

    /// Footage dropped on the window: into the open Project, into the library while it is shown, or, with
    /// nothing open, through New Project with a suggested name.
    func drop(_ urls: [URL]) {
        guard !urls.isEmpty else { return }
        guard hasScope else {
            newProjectFootage = urls
            showNewProject = true
            return
        }
        let destination = scopeProjectID
        Task { await enqueue(urls, into: destination) }
    }

    /// Registers the chosen videos and folders in the destination now and queues their analysis. The
    /// destination is fixed here, so opening another Project later cannot move this work.
    @discardableResult
    func enqueue(_ urls: [URL], into projectID: String?) async -> Bool {
        guard !urls.isEmpty else { return false }
        let accessed = urls.filter { $0.startAccessingSecurityScopedResource() }
        defer { accessed.forEach { $0.stopAccessingSecurityScopedResource() } }
        do {
            let result = try await worker.enqueue(projectID: projectID, sources: urls)
            queue = result.queue ?? queue
            let added = result.jobs?.count ?? 0, already = result.alreadyQueued?.count ?? 0
            let skipped = result.skipped ?? []
            var parts = ["\(added) \(added == 1 ? "clip" : "clips") queued"]
            if already > 0 { parts.append("\(already) already queued") }
            if !skipped.isEmpty {
                let names = skipped.prefix(3).map { URL(filePath: $0.path).lastPathComponent }.joined(separator: ", ")
                let reasons = Set(skipped.map(\.reason)).sorted().joined(separator: " or ")
                parts.append("\(skipped.count) skipped (\(reasons)): \(names)\(skipped.count > 3 ? ", …" : "")")
            }
            importNotice = parts.joined(separator: " · ")
            if projectID == scopeProjectID { try await reload() }
            runQueue()
            return true
        } catch {
            errorMessage = "Could not import: \(error.localizedDescription)"
            return false
        }
    }

    /// Picker import: creates a Project first when asked, then queues the footage.
    func importFootage(_ urls: [URL], newProjectName: String?, context: String) async {
        var destination = scopeProjectID
        if let name = newProjectName {
            guard let created = await createProject(name: name, context: context) else { return }
            destination = created.id
        }
        await enqueue(urls, into: destination)
    }

    /// Starts the queue runner unless it is running. It works through queued jobs one at a time in its own
    /// worker process, so browsing, search and review stay responsive meanwhile.
    func runQueue() {
        guard runner == nil else {
            runRequested = true
            return
        }
        runRequested = false
        runner = Task { [weak self] in
            guard let self else { return }
            let onProgress: @Sendable (WorkerEvent) async -> Void = { [weak self] event in
                await MainActor.run { self?.track(event) }
            }
            do {
                let result = try await worker.runQueue(onProgress: onProgress)
                queue = result.queue ?? queue
                if result.alreadyRunning == true {  // e.g. a runner a previous session left working
                    await followOtherRunner()
                }
            } catch is CancellationError {
                return  // the app is quitting; the runner leaves its job interrupted for resume
            } catch {
                errorMessage = "Analysis queue stopped: \(error.localizedDescription)"
            }
            activity = nil
            await refreshQueue()
            runner = nil
            // Work added or resumed while the runner was finishing starts now; waiting or paused work does not.
            if let q = queue, !q.paused, !q.running, runRequested || q.count(.queued) > 0 { runQueue() }
            try? await reload()
            if !trimmedQuery.isEmpty { await search() }
        }
    }

    /// Shows the progress of a runner this app did not start, until it finishes.
    private func followOtherRunner() async {
        while queue?.running == true, !Task.isCancelled {
            try? await Task.sleep(for: .seconds(2))
            await refreshQueue()
            try? await reload()
        }
    }

    /// The app is quitting: the runner stops its active job safely (child processes and the inference request
    /// included) and leaves it interrupted, to resume after the next launch.
    func stopRunner() {
        runner?.cancel()
    }

    func refreshQueue() async {
        if let q = try? await worker.queue("jobs") { queue = q }
    }

    /// Pause stops new jobs from starting; the active clip finishes.
    func pauseQueue() async {
        do { queue = try await worker.queue("pause") } catch { errorMessage = error.localizedDescription }
    }

    /// Un-pauses, and runs interrupted and waiting jobs again (after a restart, or once setup is complete).
    func resumeQueue() async {
        do {
            queue = try await worker.queue("resume")
            await refreshReadiness()
            runQueue()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Queued work is removed; the active job stops safely. Footage and saved context are never deleted.
    func cancel(_ jobs: [AnalysisJob]) async {
        do {
            queue = try await worker.queue("cancel", jobIDs: jobs.map(\.id))
            try await reload()
        } catch {
            errorMessage = "Could not cancel: \(error.localizedDescription)"
        }
    }

    func retry(_ jobs: [AnalysisJob]) async {
        do {
            queue = try await worker.queue("retry-jobs", jobIDs: jobs.map(\.id))
            runQueue()
        } catch {
            errorMessage = "Could not retry: \(error.localizedDescription)"
        }
    }

    func clearFinishedJobs() async {
        do { queue = try await worker.queue("clear-jobs") } catch { errorMessage = error.localizedDescription }
    }

    /// The Project (or library) a job's footage goes to, by name.
    func destinationName(_ job: AnalysisJob) -> String {
        guard let id = job.projectId else { return "Footage library" }
        return projects.first { $0.id == id }?.name ?? "Deleted Project"
    }

    /// Follows the runner: the active job's live stage, newly started jobs, and each job's outcome as soon as
    /// it is saved.
    private func track(_ event: WorkerEvent) {
        switch event.stage {
        case "job_started":
            let name = queue?.jobs.first { $0.id == event.jobId }?.originalFilename
                ?? clips.first { $0.id == event.clipId }?.originalFilename ?? "Clip"
            activity = ImportActivity(filename: name, stage: "Starting", clipID: event.clipId)
            Task { await refreshQueue(); try? await reload() }
        case "job_completed", "job_failed", "job_cancelled", "job_interrupted":
            activity = nil
            Task {
                await refreshQueue()
                try? await reload()
                if !trimmedQuery.isEmpty { await search() }
            }
        case "waiting":
            activity = nil
            Task { await refreshQueue(); await refreshReadiness() }
        default:
            activity?.stage = Self.describe(event)
            if let id = event.jobId, let i = queue?.jobs.firstIndex(where: { $0.id == id }) {
                queue?.jobs[i].stage = event.stage
            }
            if ["ready", "failed", "missing"].contains(event.stage) { Task { try? await reload() } }
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
        case "missing": return "Original not found"
        case "reading_tone": return "Reading emotional tone" + step
        case "tone_skipped": return "Skipped: not ready"
        case "tone_failed": return "Tone not read"
        default: return event.stage ?? "Working"
        }
    }
}
