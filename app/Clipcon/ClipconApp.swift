import SwiftUI

@main
struct ClipconApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup("Clipcon") {
            ContentView()
                .environment(model)
                .frame(minWidth: 900, minHeight: 560)
                .task {
                    await model.start()
                    #if DEBUG
                    await AutomationRun.runIfRequested(model)
                    #endif
                }
        }
        .commands {
            @Bindable var model = model
            CommandGroup(after: .newItem) {
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
            }
            CommandMenu("Clip") {
                let targets = model.commandTargets
                Button("Quick Look") { Task { await model.quickLook() } }
                    .keyboardShortcut("y", modifiers: .command)
                    .disabled(model.selectedClip == nil)
                let allExcluded = !targets.isEmpty && targets.allSatisfy(\.excluded)
                Button(allExcluded ? "Include in Retrieval" : "Exclude from Retrieval") {
                    Task { await model.setExcluded(targets, !allExcluded) }
                }
                .keyboardShortcut("e", modifiers: [.command, .shift])
                .disabled(targets.isEmpty)
            }
        }
    }
}
