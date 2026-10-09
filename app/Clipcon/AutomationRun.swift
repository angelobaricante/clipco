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
///   open Clipcon.app --args -ClipconAutomationImport /path/clip.mp4 \
///     -ClipconAutomationProject "Name" -ClipconAutomationContext "..." -ClipconAutomationOut /tmp/out
///     [-ClipconAutomationSearch "query"]   (the import path may also be a folder)
@MainActor
enum AutomationRun {
    static func runIfRequested(_ model: AppModel) async {
        let defaults = UserDefaults.standard
        // `-ClipconShowSetup YES` opens the setup sheet, e.g. to capture the Codex connection check.
        if defaults.bool(forKey: "ClipconShowSetup") { model.showSetup = true }
        // `-ClipconAutomationRemove <filename>` and/or `-ClipconAutomationDeleteProject <name>` exercise removal
        // through the same model calls as the confirmation dialogs, then write a report.
        let removing = defaults.string(forKey: "ClipconAutomationRemove")
        let deleting = defaults.string(forKey: "ClipconAutomationDeleteProject")
        if removing != nil || deleting != nil, let out = defaults.string(forKey: "ClipconAutomationOut") {
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
            if defaults.bool(forKey: "ClipconAutomationQuit") { NSApp.terminate(nil) }
            return
        }
        guard let path = defaults.string(forKey: "ClipconAutomationImport"),
              let out = defaults.string(forKey: "ClipconAutomationOut") else { return }
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
            // Search the saved index while analysis is still running (`-ClipconAutomationSearch "query"`).
            guard let query = defaults.string(forKey: "ClipconAutomationSearch") else { return }
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
                               newProjectName: defaults.string(forKey: "ClipconAutomationProject"),
                               context: defaults.string(forKey: "ClipconAutomationContext") ?? "")
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
        if defaults.bool(forKey: "ClipconAutomationQuit") { NSApp.terminate(nil) }
    }
}
#endif
