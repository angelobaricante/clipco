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
@MainActor
enum AutomationRun {
    static func runIfRequested(_ model: AppModel) async {
        let defaults = UserDefaults.standard
        guard let path = defaults.string(forKey: "ClipconAutomationImport"),
              let out = defaults.string(forKey: "ClipconAutomationOut") else { return }
        let outDir = URL(filePath: out)
        try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
        var report: [String: Any] = ["source": path]
        let started = Date()
        let state = ProbeState()

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
        }

        await model.importClip(URL(filePath: path),
                               newProjectName: defaults.string(forKey: "ClipconAutomationProject"),
                               context: defaults.string(forKey: "ClipconAutomationContext") ?? "")
        report["import_seconds"] = Date().timeIntervalSince(started)
        state.probing = false
        _ = await (probe.value, stageWatch.value, interaction.value)
        report["worst_main_thread_stall_ms"] = (state.worstStall * 1000).rounded()
        report["stages"] = state.stages
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
