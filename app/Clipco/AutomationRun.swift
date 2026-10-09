#if DEBUG
import AppKit
import SwiftUI

@MainActor
final class ProbeState {
    var probing = true
    var worstStall = 0.0
    var stages: [[String: Any]] = []
}

/// Debug-only behavioral check of the real app: imports a clip through the same AppModel path
/// as the Import sheet, interacts with the window during analysis, and measures main-thread stalls.
///
///   open Clipco.app --args -ClipcoAutomationImport /path/clip.mp4 \
///     -ClipcoAutomationProject "Name" -ClipcoAutomationContext "..." -ClipcoAutomationOut /tmp/out
///     [-ClipcoAutomationSearch "query"]   (the import path may also be a folder)
@MainActor
enum AutomationRun {
    /// Review workflow on a real Project: selection across inspector/view changes, filters, verified playback
    /// access, then (optionally) a note and exclusion through the same model calls the inspector uses.
    ///
    ///   Clipco -ClipcoAutomationReview <filename> -ClipcoAutomationOut /tmp/out
    ///     [-ClipcoAutomationNote "text"] [-ClipcoAutomationExclude YES|NO] [-ClipcoAutomationSearch "query"]
    ///     [-ClipcoAutomationMode list] [-ClipcoAutomationTab context|transcript|info] [-ClipcoAutomationHold 8]
    static func review(_ model: AppModel, clipNamed name: String, out: URL, defaults: UserDefaults) async {
        var report: [String: Any] = ["project": model.project?.name ?? NSNull()]
        guard let clip = model.clips.first(where: { $0.originalFilename == name }) else {
            report["error"] = "no clip named \(name)"
            write(report, to: out)
            NSApp.terminate(nil)
            return
        }
        report["at_launch"] = ["note": clip.note?.text ?? NSNull(), "excluded": clip.excluded]
        model.select(clip.id)
        var preserved: [String: Bool] = [:]
        model.showInspector = false
        try? await Task.sleep(for: .milliseconds(400))
        preserved["inspector_hidden"] = model.selection == [clip.id]
        model.showInspector = true
        model.browserMode = .list
        try? await Task.sleep(for: .milliseconds(400))
        preserved["list_view"] = model.selection == [clip.id]
        model.browserMode = .grid
        try? await Task.sleep(for: .milliseconds(400))
        preserved["grid_view"] = model.selection == [clip.id] && model.selectedClip?.id == clip.id
        report["selection_preserved"] = preserved
        report["source_access"] = String(describing: await SourceAccess.check(clip))
        if let note = defaults.string(forKey: "ClipcoAutomationNote") { await model.saveNote(note, for: clip.id) }
        if defaults.object(forKey: "ClipcoAutomationExclude") != nil {
            let target = model.clips.filter { $0.id == clip.id }
            await model.setExcluded(target, defaults.bool(forKey: "ClipcoAutomationExclude"))
        }
        // `-ClipcoAutomationReuse YES|NO` and `-ClipcoAutomationRole <segment index>:<role|suggested>` go through
        // the same model calls as the inspector's reuse switch and Segment role menus.
        if defaults.object(forKey: "ClipcoAutomationReuse") != nil {
            await model.setReuse(clip, defaults.bool(forKey: "ClipcoAutomationReuse"))
        }
        if let change = defaults.string(forKey: "ClipcoAutomationRole"), let colon = change.firstIndex(of: ":"),
           let index = Int(change[..<colon]), let current = model.clips.first(where: { $0.id == clip.id }),
           current.segments.indices.contains(index) {
            let role = String(change[change.index(after: colon)...])
            await model.setRole(role == "suggested" ? nil : role, for: current.segments[index])
        }
        let after = model.clips.first { $0.id == clip.id }
        report["after"] = ["note": after?.note?.text ?? NSNull(), "excluded": after?.excluded ?? NSNull(),
                           "selected": model.selection == [clip.id]]
        var library: [String: Any] = ["reuse_allowed": after?.reuseAllowed ?? NSNull(),
                                       "role_summary": after?.roleSummary.text ?? NSNull()]
        library["projects"] = (after?.projects ?? []).map(\.name)
        library["segment_roles"] = (after?.segments ?? []).map { (segment: Segment) -> String in
            let range = "\(segment.start.timecode)–\(segment.end.timecode)"
            return "\(range) \(segment.role.effective) (suggested \(segment.role.suggested), "
                + "creator \(segment.role.creator ?? "none"))"
        }
        report["library"] = library
        report["counts"] = Dictionary(uniqueKeysWithValues: FootageFilter.allCases.map { ($0.rawValue, model.count($0)) })
        if let query = defaults.string(forKey: "ClipcoAutomationSearch") {
            model.searchText = query
            await model.search()
            report["search"] = model.searchResults?.results.map {
                ["file": $0.originalFilename, "basis": $0.evidenceBasis, "excluded": $0.excluded]
            } ?? []
        }
        model.browserMode = defaults.string(forKey: "ClipcoAutomationMode") == "list" ? .list : .grid
        model.inspectorTab = InspectorTab(rawValue: (defaults.string(forKey: "ClipcoAutomationTab") ?? "context")
            .capitalized) ?? .context
        // `-ClipcoAutomationPlay <seconds>` opens the player over the browser from that source time, lets it
        // play, then records the position and the transcript line the inspector highlights.
        if defaults.object(forKey: "ClipcoAutomationPlay") != nil {
            await model.openPlayer(clip.id, at: defaults.double(forKey: "ClipcoAutomationPlay"))
            try? await Task.sleep(for: .seconds(3))
            let spoken = model.spokenLineID(in: clip)
            let line = clip.segments.flatMap(\.transcript).first { $0.id == spoken }
            var playback: [String: Any] = ["overlay_open": model.playingClipID == clip.id]
            playback["access"] = model.player.access.map { String(describing: $0) } ?? "none"
            playback["position"] = model.player.currentTime ?? -1
            playback["spoken_line"] = line.map { "\($0.start)–\($0.end) \($0.text)" } ?? "none"
            playback["inspector_clip"] = model.selectedClip?.originalFilename ?? "none"
            report["playback"] = playback
        }
        var commandF: [String] = []
        for top in NSApp.mainMenu?.items ?? [] {
            for item in top.submenu?.items ?? [] {
                for candidate in [item] + (item.submenu?.items ?? [])
                where candidate.keyEquivalent == "f" && candidate.keyEquivalentModifierMask == .command {
                    commandF.append("\(top.title) ▸ \(candidate.title)")
                }
            }
        }
        report["command_f_items"] = commandF
        report["window_number"] = NSApp.windows.first { $0.isVisible }?.windowNumber ?? NSNull()
        report["error"] = model.errorMessage ?? NSNull()
        write(report, to: out)
        try? await Task.sleep(for: .seconds(defaults.double(forKey: "ClipcoAutomationHold")))
        NSApp.terminate(nil)
    }

    /// Recovery workflow on a real Project, through the same model calls as the inspector's recovery banner and
    /// the Clip menu. Sources were already checked when the Project opened; the report records what the creator
    /// sees, then optionally locates the original and/or re-analyses, recording the stages shown meanwhile.
    ///
    ///   Clipco -ClipcoAutomationRecover <filename> -ClipcoAutomationOut /tmp/out
    ///     [-ClipcoAutomationLocate /path/to/moved.mov] [-ClipcoAutomationRetry YES] [-ClipcoAutomationHold 8]
    static func recover(_ model: AppModel, clipNamed name: String, out: URL, defaults: UserDefaults) async {
        var report: [String: Any] = ["project": model.project?.name ?? NSNull()]
        func state(_ step: String) {
            let clip = model.clips.first { $0.originalFilename == name }
            var seen: [String: Any] = ["status": clip?.status.rawValue ?? "absent"]
            seen["guidance"] = clip?.error ?? NSNull()
            seen["can_reanalyse"] = clip.map { model.canRetry([$0]) } ?? false
            seen["note"] = clip?.note?.text ?? NSNull()
            seen["excluded"] = clip?.excluded ?? NSNull()
            seen["segments"] = clip?.segments.count ?? 0
            seen["error"] = model.errorMessage ?? NSNull()
            report[step] = seen
        }
        guard let clip = model.clips.first(where: { $0.originalFilename == name }) else {
            report["error"] = "no clip named \(name)"
            write(report, to: out)
            NSApp.terminate(nil)
            return
        }
        report["clip_id"] = clip.id
        model.select(clip.id)
        model.inspectorTab = .context
        try? await Task.sleep(for: .milliseconds(600))
        state("on_open")
        if let path = defaults.string(forKey: "ClipcoAutomationLocate") {
            await model.locate(clip, at: URL(filePath: path))
            try? await Task.sleep(for: .milliseconds(600))
            state("after_locate")
            model.errorMessage = nil
        }
        if defaults.bool(forKey: "ClipcoAutomationRetry"), let current = model.clips.first(where: { $0.id == clip.id }) {
            let started = Date()
            let probe = ProbeState()
            let stageWatch = Task { @MainActor in
                var last = ""
                while probe.probing {
                    let t = Date()
                    if let stage = model.activity?.stage, stage != last {
                        last = stage
                        probe.stages.append(["t": Date().timeIntervalSince(started), "stage": stage])
                    }
                    try? await Task.sleep(for: .milliseconds(50))
                    probe.worstStall = max(probe.worstStall, Date().timeIntervalSince(t) - 0.05)
                }
            }
            await model.retry([current])
            probe.probing = false
            await stageWatch.value
            report["retry_seconds"] = Date().timeIntervalSince(started)
            report["retry_stages"] = probe.stages
            report["worst_main_thread_stall_ms"] = (probe.worstStall * 1000).rounded()
            try? await Task.sleep(for: .milliseconds(600))
            state("after_retry")
        }
        report["statuses"] = Dictionary(uniqueKeysWithValues: model.clips.map { ($0.originalFilename, $0.status.rawValue) })
        report["window_number"] = NSApp.windows.first { $0.isVisible }?.windowNumber ?? NSNull()
        write(report, to: out)
        // `-ClipcoAutomationHold <seconds>` keeps the window up, e.g. for `screencapture -l <window_number>`.
        try? await Task.sleep(for: .seconds(defaults.double(forKey: "ClipcoAutomationHold")))
        NSApp.terminate(nil)
    }

    private static func write(_ report: [String: Any], to out: URL) {
        try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
        let data = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
        try? data?.write(to: out.appending(path: "report.json"))
    }

    static func runIfRequested(_ model: AppModel) async {
        let defaults = UserDefaults.standard
        if let name = defaults.string(forKey: "ClipcoAutomationReview"),
           let out = defaults.string(forKey: "ClipcoAutomationOut") {
            await review(model, clipNamed: name, out: URL(filePath: out), defaults: defaults)
            return
        }
        if let name = defaults.string(forKey: "ClipcoAutomationRecover"),
           let out = defaults.string(forKey: "ClipcoAutomationOut") {
            await recover(model, clipNamed: name, out: URL(filePath: out), defaults: defaults)
            return
        }
        // `-ClipcoShowSetup YES` opens the setup sheet, e.g. to capture the Codex connection check.
        if defaults.bool(forKey: "ClipcoShowSetup") { model.showSetup = true }
        // `-ClipcoAutomationRemove <filename>` and/or `-ClipcoAutomationDeleteProject <name>` exercise removal
        // through the same model calls as the confirmation dialogs, then write a report.
        let removing = defaults.string(forKey: "ClipcoAutomationRemove")
        let deleting = defaults.string(forKey: "ClipcoAutomationDeleteProject")
        if removing != nil || deleting != nil, let out = defaults.string(forKey: "ClipcoAutomationOut") {
            var report: [String: Any] = [:]
            if let name = removing, let clip = model.clips.first(where: { $0.originalFilename == name }) {
                await model.remove([clip])
                report["clips_after_remove"] = model.clips.map(\.originalFilename)
            }
            if let name = deleting, let project = model.projects.first(where: { $0.name == name }) {
                await model.delete(project)
                report["projects_after_delete"] = model.projects.map(\.name)
                report["open_project"] = model.project?.name
            }
            report["error"] = model.errorMessage
            let data = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
            try? FileManager.default.createDirectory(at: URL(filePath: out), withIntermediateDirectories: true)
            try? data?.write(to: URL(filePath: out).appending(path: "report.json"))
            if defaults.bool(forKey: "ClipcoAutomationQuit") { NSApp.terminate(nil) }
            return
        }
        guard let path = defaults.string(forKey: "ClipcoAutomationImport"),
              let out = defaults.string(forKey: "ClipcoAutomationOut") else { return }
        let outDir = URL(filePath: out)
        try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
        var report: [String: Any] = ["source": path]
        let started = Date()
        let state = ProbeState()
        var searchReport: [String: Any] = [:]

        // Main-thread responsiveness probe: a 50 ms tick that records its worst lateness.
        let probe = Task { @MainActor in
            while state.probing {
                let t = Date()
                try? await Task.sleep(for: .milliseconds(50))
                state.worstStall = max(state.worstStall, Date().timeIntervalSince(t) - 0.05)
            }
        }
        let stageWatch = Task { @MainActor in
            var last = ""
            while state.probing {
                if let stage = model.activity?.stage, stage != last {
                    last = stage
                    state.stages.append(["t": Date().timeIntervalSince(started), "stage": stage])
                }
                try? await Task.sleep(for: .milliseconds(100))
            }
        }
        let interaction = Task { @MainActor in
            try? await Task.sleep(for: .seconds(4))
            // Interact while analysis runs: toggle the inspector and change the sidebar filter.
            model.showInspector.toggle()
            model.filter = .aRoll
            try? await Task.sleep(for: .milliseconds(300))
            model.showInspector.toggle()
            model.filter = .all
            // Search the saved index while analysis is still running (`-ClipcoAutomationSearch "query"`).
            guard let query = defaults.string(forKey: "ClipcoAutomationSearch") else { return }
            while model.activity != nil && !model.clips.contains(where: { $0.status == .ready }) {
                try? await Task.sleep(for: .milliseconds(500))
            }
            let asked = Date()
            model.searchText = query
            await model.search()
            searchReport = ["query": query, "seconds": Date().timeIntervalSince(asked),
                            "while_importing": model.activity != nil,
                            "results": model.searchResults?.results.map { "\($0.originalFilename) \($0.start)–\($0.end)" }
                                ?? []]
        }

        await model.importFootage([URL(filePath: path)],
                               newProjectName: defaults.string(forKey: "ClipcoAutomationProject"),
                               context: defaults.string(forKey: "ClipcoAutomationContext") ?? "")
        report["import_seconds"] = Date().timeIntervalSince(started)
        state.probing = false
        _ = await (probe.value, stageWatch.value, interaction.value)
        report["worst_main_thread_stall_ms"] = (state.worstStall * 1000).rounded()
        report["stages"] = state.stages
        report["search_during_import"] = searchReport
        report["error"] = model.errorMessage
        if let clip = model.selectedClip {
            report["clip_id"] = clip.id
            report["status"] = clip.status.rawValue
            report["segments"] = clip.segments.count
            report["label"] = clip.label
        }
        for tab in InspectorTab.allCases {
            model.inspectorTab = tab
            try? await Task.sleep(for: .milliseconds(500))
        }
        let data = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
        try? data?.write(to: outDir.appending(path: "report.json"))
        if defaults.bool(forKey: "ClipcoAutomationQuit") { NSApp.terminate(nil) }
    }
}
#endif
