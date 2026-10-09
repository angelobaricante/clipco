import Foundation

/// Mirrors the worker's JSON-lines contract (`clipco-worker`). Keys arrive snake_case.

struct Readiness: Decodable, Equatable, Sendable {
    enum State: String, Decodable, Sendable {
        case workerUnavailable = "worker_unavailable"
        case toolsMissing = "tools_missing"
        case serviceUnavailable = "service_unavailable"
        case modelMissing = "model_missing"
        case cold, loading, ready
        case inferenceFailed = "inference_failed"
    }

    var state: State
    var detail: String
    var guidance: String
    var visionModel: String?
    var speechModel: String?
    var ollamaVersion: String?
}

struct Project: Decodable, Identifiable, Hashable, Sendable {
    var id: String
    var name: String
    var context: String
}

struct Snapshot: Decodable, Sendable {
    /// Nil for the Footage library, which no Project owns.
    var project: Project?
    var clips: [SourceClip]
}

struct SourceClip: Decodable, Identifiable, Hashable, Sendable {
    enum Status: String, Decodable, Sendable { case pending, indexing, ready, failed, stale, missing }

    var id: String
    var sourcePath: String
    var originalFilename: String
    var status: Status
    var stage: String?
    var error: String?
    var duration: Double?
    var width: Int?
    var height: Int?
    var fps: Double?
    var videoCodec: String?
    var audioCodec: String?
    var label: String?
    var role: String?
    var roleBasis: String?
    var speechLanguage: String?
    var revision: Int
    var sizeBytes: Int?
    var mtime: Double?
    /// The creator excluded this clip from new default searches (reversible; nothing is deleted).
    var excluded: Bool
    var note: CreatorNote?
    var analysis: Analysis?
    var segments: [Segment]
    /// Source-wide: may this footage be offered as B-roll outside its own Projects?
    var reuseAllowed: Bool
    /// Every Project this library source belongs to (its analysis is shared; notes are not).
    var projects: [ProjectMembership]
    var roleSummary: RoleSummary
    /// Creator role choices for Segment ranges that a later re-analysis no longer has.
    var unmatchedRoleCorrections: [UnmatchedRoleCorrection]
    /// Creator tones for Segment ranges that a later re-analysis no longer has.
    var unmatchedToneCorrections: [UnmatchedToneCorrection]

    var displayLabel: String { label ?? originalFilename }

    var relationships: [RelatedSegment] { segments.flatMap(\.relationships) }

    /// Not yet usable context, or suggested corrections/takes the creator may want to choose between.
    var needsReview: Bool {
        status != .ready || segments.contains { ["mixed", "needs_review"].contains($0.role.effective) }
            || !unmatchedRoleCorrections.isEmpty || !unmatchedToneCorrections.isEmpty
            || relationships.contains { $0.kind == "spoken_correction" || $0.kind == "repeated_take" }
    }

    func containsRole(_ role: String) -> Bool { segments.contains { $0.role.effective == role } }

    var roleLabel: String {
        let roles = Set(segments.map(\.role.effective))
        if roles.isEmpty { return "Not analyzed" }
        if roles.count == 1, let role = roles.first { return SegmentRole.name(role) }
        return "Mixed"
    }

    /// Whisper's language code as a readable name, e.g. "tl" → "Tagalog".
    var speechLanguageName: String? {
        speechLanguage.map { Locale.current.localizedString(forLanguageCode: $0) ?? $0 }
    }
    var thumbnailPath: String? { segments.first?.observations.first?.frame.path }
}

struct ProjectMembership: Decodable, Hashable, Sendable {
    var projectId: String
    var name: String
    var excluded: Bool
}

struct UnmatchedRoleCorrection: Decodable, Hashable, Sendable {
    var start: Double
    var end: Double
    var role: String
}

struct UnmatchedToneCorrection: Decodable, Hashable, Sendable {
    var start: Double
    var end: Double
    var tones: [String]
}

struct RoleSummary: Decodable, Hashable, Sendable {
    var text: String
}

/// A Segment's footage role: suggested in code from its evidence, with the creator's correction kept apart.
struct SegmentRole: Decodable, Hashable, Sendable {
    var suggested: String
    var basis: String
    var creator: String?
    var effective: String

    static let choices = ["a-roll", "b-roll", "mixed", "needs_review"]

    static func name(_ role: String) -> String {
        switch role {
        case "a-roll": "A-roll"
        case "b-roll": "B-roll"
        case "mixed": "Mixed"
        default: "Needs review"
        }
    }
}

/// Written by the creator in Clipco, about the whole Source clip; kept apart from model output.
struct CreatorNote: Decodable, Hashable, Sendable {
    var text: String
    var updatedAt: Double
}

struct Analysis: Decodable, Hashable, Sendable {
    struct Engine: Decodable, Hashable, Sendable {
        var engine: String
        var model: String
        var digest: String?
    }

    var revision: Int
    var elapsed: Double
    var speech: Engine
    var vision: Engine
    var finishedAt: Double
}

struct Segment: Decodable, Identifiable, Hashable, Sendable {
    struct Line: Decodable, Identifiable, Hashable, Sendable {
        var id: String
        var start: Double
        var end: Double
        var text: String
    }

    struct Frame: Decodable, Hashable, Sendable {
        var id: String
        var time: Double
        var path: String
    }

    struct Observation: Decodable, Hashable, Sendable {
        var frame: Frame
        var text: String
    }

    struct Interpretation: Decodable, Hashable, Sendable {
        var text: String
        var evidenceIds: [String]
        var rejectedRefs: [String]
        var model: String?
    }

    var id: String
    var start: Double
    var end: Double
    var label: String
    var transcript: [Line]
    var observations: [Observation]
    var interpretation: Interpretation
    var role: SegmentRole
    var tone: SegmentTone
    var relationships: [RelatedSegment]

    /// Offered as B-roll outside its own Projects (when the clip also allows reuse).
    var isReusableBRoll: Bool { role.effective == "b-roll" }
}

/// Suggested emotional tone: an interpretation of sampled evidence, never an observation or a guarantee. The
/// creator's tones are kept apart from the model's suggestions.
struct SegmentTone: Decodable, Hashable, Sendable {
    struct Suggestion: Decodable, Hashable, Sendable {
        var tone: String
        var explanation: String
        var evidenceIds: [String]
    }

    struct Connotation: Decodable, Hashable, Sendable {
        var idea: String
        var explanation: String
        var evidenceIds: [String]
    }

    /// not_analyzed, none_supported, suggested, or creator.
    var state: String
    /// What counts for discovery: the creator's tones when set, otherwise the suggestions.
    var tones: [String]
    var suggested: [Suggestion]
    var connotations: [Connotation]
    var depictedEmotion: String?
    var creator: [String]?
    var model: String?
    var limitations: String

    static let vocabulary = ["calm", "hopeful", "joyful", "playful", "warm", "nostalgic", "melancholic", "tense",
                             "energetic", "awe", "satisfying", "curious"]

    var summary: String { Self.summary(state: state, tones: tones) }

    static func summary(state: String, tones: [String]) -> String {
        switch state {
        case "not_analyzed": "Not analyzed"
        case "none_supported": "No supported tone"
        default: tones.isEmpty ? "None (set by you)" : tones.map(\.capitalized).joined(separator: ", ")
        }
    }
}

enum EditingAgent: String, Identifiable {
    case codex = "Codex", claude = "Claude"
    var id: Self { self }
}

struct AgentRegistration: Decodable, Equatable, Sendable, Identifiable {
    var id: String
    var name: String
    var installed: Bool
    var configured: Bool
    var state: String
    var error: String?
    var configPath: String?
    var setupCommand: String?
    var setupJson: String?
    var guidance: String

    var title: String {
        switch state {
        case "configured": "Configured"
        case "not_installed": "Not installed"
        case "conflict": "Needs attention"
        case "error": "Couldn’t check setup"
        default: "Not configured"
        }
    }
}

/// Result of the app's Codex connection check: a real MCP session with clipco-mcp.
struct McpStatus: Decodable, Equatable, Sendable {
    struct Codex: Decodable, Equatable, Sendable {
        var path: String?
        var version: String?
        var registered: Bool
        var registeredCommand: [String]?
        var error: String?
    }

    var ok: Bool
    var error: String?
    var serverCommand: [String]
    var addCommand: String
    var sdkVersion: String
    var serverVersion: String?
    var protocolVersion: String?
    var tools: [String]
    var projectCount: Int?
    var connectMs: Int?
    var overviewMs: Int?
    var codex: Codex
    var agents: [AgentRegistration]?

    /// Codex has a `clipco` server, but it launches something other than this installation.
    var codexRegistrationDiffers: Bool { codex.registered && codex.registeredCommand != serverCommand }
}

/// One page of saved-index search results; the same payload Codex receives from `search_footage`.
struct SearchPage: Decodable, Sendable {
    var query: String
    var totalMatches: Int
    var truncated: Bool
    var results: [SearchHit]
    var nextOffset: Int?
}

struct SearchHit: Decodable, Identifiable, Hashable, Sendable {
    /// How a library result supports the request, and a caution when it comes from elsewhere.
    struct Fit: Decodable, Hashable, Sendable {
        var kind: String
        var explanation: String
        var tonesMatched: [String]
        var currentProject: Bool
        var caution: String?
    }

    struct Origin: Decodable, Hashable, Sendable {
        var projectId: String
        var name: String
    }

    struct Tone: Decodable, Hashable, Sendable {
        var state: String
        var tones: [String]
    }

    var segmentId: String
    var clipId: String
    var originalFilename: String
    var label: String
    var start: Double
    var end: Double
    var excerpt: String
    var evidenceBasis: String
    var status: SourceClip.Status
    var excluded: Bool
    var hasCreatorNote: Bool
    var relationships: [RelatedSegment]
    var tone: Tone?
    var fit: Fit?
    var origins: [Origin]?

    var id: String { segmentId }

    var evidenceName: String { evidenceBasis == "creator_note" ? "creator note" : evidenceBasis }
}

/// A suggested relationship to another Segment. Suggestions never mark one side as preferred.
struct RelatedSegment: Decodable, Identifiable, Hashable, Sendable {
    var relationshipId: String
    var kind: String
    var relatedAs: String
    var segmentId: String
    var clipId: String
    var originalFilename: String
    var start: Double
    var end: Double
    var label: String
    var excerpt: String
    var basis: String
    var excluded: Bool

    var id: String { relationshipId + segmentId }

    var title: String {
        switch relatedAs {
        case "earlier_statement": "Earlier statement"
        case "correction": "Spoken correction"
        case "other_take": "Repeated take"
        case "suggested_broll": "Suggested B-roll"
        case "a_roll_explanation": "Explained in A-roll"
        case "within_segment": kind == "repeated_take" ? "Repeated take in this segment"
                                                       : "Spoken correction in this segment"
        default: relatedAs
        }
    }

    var symbol: String {
        switch kind {
        case "spoken_correction": "arrow.uturn.backward.circle"
        case "repeated_take": "repeat.circle"
        default: "photo.on.rectangle"
        }
    }
}

/// One stdout line from the worker.
struct WorkerEvent: Decodable, Sendable {
    var event: String
    var stage: String?
    var segment: Int?
    var of: Int?
    var readiness: Readiness?
    var project: Project?
    var projects: [Project]?
    var snapshot: Snapshot?
    var mcp: McpStatus?
    var clipId: String?
    var filename: String?
    var search: SearchPage?
    var reused: Bool?
    var elapsed: Double?
    var kind: String?
    var message: String?
    var detail: String?
    var jobId: String?
    // Queue results
    var jobs: [AnalysisJob]?
    var counts: [String: Int]?
    var paused: Bool?
    var running: Bool?
    var alreadyRunning: Bool?
    var alreadyQueued: [AnalysisJob]?
    var skipped: [SkippedItem]?

    /// The queue as a result reported it (every queue command returns it).
    var queue: QueueState? {
        guard let jobs else { return nil }
        return QueueState(jobs: jobs, paused: paused ?? false, running: running ?? false)
    }
}

/// Queued work to prepare or enrich one Source clip, bound to its destination when it was requested.
struct AnalysisJob: Decodable, Identifiable, Hashable, Sendable {
    enum State: String, Decodable, Sendable {
        case queued, active, waiting, completed, failed, cancelled, interrupted
    }

    var id: String
    var operation: String
    var clipId: String
    var projectId: String?
    var sourcePath: String
    var originalFilename: String
    var state: State
    var stage: String?
    var error: String?
    var attempts: Int
    var cancelRequested: Bool

    var operationTitle: String {
        switch operation {
        case "import": "Analyze"
        case "reanalyse": "Re-analyse"
        case "enrich_tone": "Read emotional tone"
        default: operation
        }
    }

    var canCancel: Bool { [.queued, .active, .waiting, .interrupted].contains(state) && !cancelRequested }
    var canRetry: Bool { [.failed, .cancelled, .interrupted].contains(state) }
}

struct QueueState: Equatable, Sendable {
    var jobs: [AnalysisJob]
    var paused: Bool
    var running: Bool

    func count(_ state: AnalysisJob.State) -> Int { jobs.filter { $0.state == state }.count }
    var active: AnalysisJob? { jobs.first { $0.state == .active } }
    /// Work that has not finished: it runs, waits, or awaits the creator's resume.
    var unfinished: Int { jobs.filter { [.queued, .active, .waiting, .interrupted].contains($0.state) }.count }
    var finished: Int { jobs.filter { [.completed, .cancelled].contains($0.state) }.count }
}

/// A dropped or chosen item that was not registered, and why.
struct SkippedItem: Decodable, Hashable, Sendable {
    var path: String
    var reason: String
}

extension Double {
    /// Source-relative timecode, e.g. 1:05.3
    var timecode: String {
        let minutes = Int(self) / 60
        return String(format: "%d:%04.1f", minutes, self - Double(minutes * 60))
    }
}
