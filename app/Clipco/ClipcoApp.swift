import SwiftUI

@main
struct ClipcoApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup("Clipco") {
            ContentView()
                .environment(model)
                .frame(minWidth: 900, minHeight: 560)
                .onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in
                    model.stopRunner()
                }
                .task {
                    await model.start()
                    #if DEBUG
                    await AutomationRun.runIfRequested(model)
                    #endif
                }
        }
        .commands {
            @Bindable var model = model
            CommandGroup(replacing: .newItem) {
                Button("New Project…") { model.showNewProject = true }
                    .keyboardShortcut("n", modifiers: .command)
                Button("Import Footage…") { model.showImport = true }
                    .keyboardShortcut("i", modifiers: [.command, .shift])
            }
            CommandGroup(after: .textEditing) {
                Button("Find in Footage Context") { model.searchFocusRequest += 1 }
                    .keyboardShortcut("f", modifiers: .command)
            }
            CommandGroup(after: .sidebar) {
                Picker("View", selection: $model.browserMode) {
                    Text("as Grid").tag(BrowserMode.grid).keyboardShortcut("1", modifiers: .command)
                    Text("as List").tag(BrowserMode.list).keyboardShortcut("2", modifiers: .command)
                }
                .pickerStyle(.inline)
                Divider()
                Button(model.showInspector ? "Hide Inspector" : "Show Inspector") { model.showInspector.toggle() }
                    .keyboardShortcut("i", modifiers: .command)
                Button("Show Analysis Queue") { model.showActivity = true }
                    .keyboardShortcut("a", modifiers: [.command, .option])
            }
            CommandMenu("Clip") {
                let targets = model.commandTargets
                Button("Play") { _ = model.playSelectedClip() }
                    .keyboardShortcut(.downArrow, modifiers: .command)
                    .disabled(model.selectedClip == nil)
                Button("Quick Look") { Task { await model.quickLook() } }
                    .keyboardShortcut("y", modifiers: .command)
                    .disabled(model.selectedClip == nil)
                let allExcluded = !targets.isEmpty && targets.allSatisfy(\.excluded)
                Button(allExcluded ? "Include in Retrieval" : "Exclude from Retrieval") {
                    Task { await model.setExcluded(targets, !allExcluded) }
                }
                .keyboardShortcut("e", modifiers: [.command, .shift])
                .disabled(targets.isEmpty)
                Divider()
                Button("Re-analyse") { Task { await model.retry(targets) } }
                    .keyboardShortcut("r", modifiers: [.command, .shift])
                    .disabled(!model.canRetry(targets))
                Button("Check Original Files") { Task { await model.checkSources() } }
                    .disabled(model.project == nil || model.activity != nil || model.isCheckingSources)
            }
        }
    }
}
