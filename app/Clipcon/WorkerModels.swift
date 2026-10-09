import Foundation

/// Mirrors the worker's JSON-lines contract (`clipcon-worker`). Keys arrive snake_case.

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
    var project: Project
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
    var revision: Int
    var analysis: Analysis?
    var segments: [Segment]

    var displayLabel: String { label ?? originalFilename }
    var thumbnailPath: String? { segments.first?.observations.first?.frame.path }
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
    var clipId: String?
    var reused: Bool?
    var elapsed: Double?
    var kind: String?
    var message: String?
}

extension Double {
    /// Source-relative timecode, e.g. 1:05.3
    var timecode: String {
        let minutes = Int(self) / 60
        return String(format: "%d:%04.1f", minutes, self - Double(minutes * 60))
    }
}
