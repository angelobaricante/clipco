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
            CommandGroup(after: .newItem) {
                Button("Import Source Clip…") { model.showImport = true }
                    .keyboardShortcut("i", modifiers: [.command, .shift])
            }
            CommandGroup(after: .sidebar) {
                Button(model.showInspector ? "Hide Inspector" : "Show Inspector") { model.showInspector.toggle() }
                    .keyboardShortcut("i", modifiers: .command)
            }
        }
    }
}
