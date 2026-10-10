import SwiftUI

@main
struct ClipcoApp: App {
    @State private var model = AppModel()
    // App-owned state: opening another window or returning to the app never replays the splash.
    @State private var showsLaunchSplash = true

    var body: some Scene {
        WindowGroup("Clipco") {
            ContentView()
                .environment(model)
                .frame(minWidth: 900, minHeight: 560)
                .disabled(showsLaunchSplash)
                .accessibilityHidden(showsLaunchSplash)
                .overlay {
                    if showsLaunchSplash {
                        LaunchSplash { animated in
                            if animated {
                                withAnimation(.timingCurve(0.23, 1, 0.32, 1, duration: 0.18)) {
                                    showsLaunchSplash = false
                                }
                            } else {
                                showsLaunchSplash = false
                            }
                        }
                        .transition(.opacity)
                    }
                }
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
            CommandGroup(replacing: .appSettings) {
                Button("Clipco Setup…") { model.showSetup = true }
                    .keyboardShortcut(",", modifiers: .command)
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
                .disabled(targets.isEmpty || model.showingLibrary)
                Divider()
                Button("Re-analyse") { Task { await model.retry(targets) } }
                    .keyboardShortcut("r", modifiers: [.command, .shift])
                    .disabled(!model.canRetry(targets))
                Button("Check Original Files") { Task { await model.checkSources() } }
                    .disabled(!model.hasScope || model.activity != nil || model.isCheckingSources)
            }
        }
    }
}

/// A bounded visual welcome, independent of worker and model readiness.
/// The real workspace is mounted underneath, so loading proceeds during the reveal.
struct LaunchSplash: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @State private var revealed = false
    let dismiss: (_ animated: Bool) -> Void

    private var ink: Color {
        colorScheme == .dark ? .white : Color(red: 14 / 255, green: 13 / 255, blue: 12 / 255)
    }

    private var paper: Color {
        colorScheme == .dark ? Color(red: 14 / 255, green: 13 / 255, blue: 12 / 255)
            : Color(red: 247 / 255, green: 246 / 255, blue: 242 / 255)
    }

    var body: some View {
        ZStack {
            paper
            if !reduceTransparency {
                RadialGradient(colors: [ink.opacity(0.045), .clear],
                               center: .center, startRadius: 60, endRadius: 380)
                    .accessibilityHidden(true)
            }

            ZStack {
                // Three quiet frames echo the mark's facets and the footage browser.
                ForEach(0..<3) { index in
                    RoundedRectangle(cornerRadius: 28, style: .continuous)
                        .strokeBorder(ink.opacity(0.07), lineWidth: 1)
                        .frame(width: 440, height: 250)
                        .rotationEffect(.degrees(Double(index - 1) * 9))
                        .scaleEffect(reduceMotion || revealed ? 1 : 0.96)
                        .opacity(revealed ? 1 : 0)
                }
                .accessibilityHidden(true)

                VStack(spacing: 20) {
                    Image("ClipcoLogo")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 310, height: 104)
                        .foregroundStyle(ink)
                        .accessibilityLabel("Clipco")
                    Text("Your clips, in context.")
                        .font(.system(.title3, design: .default))
                        .foregroundStyle(ink.opacity(0.65))
                }
                .scaleEffect(reduceMotion || revealed ? 1 : 0.97)
                .opacity(revealed ? 1 : 0)
            }

            VStack {
                Spacer()
                Button("Open Workspace") { dismiss(false) }
                    .keyboardShortcut(.cancelAction)
                    .controlSize(.small)
                    .help("Skip the welcome and open your workspace (Escape)")
                    .padding(.bottom, 28)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .task {
            withAnimation(reduceMotion ? .linear(duration: 0.15)
                          : .timingCurve(0.23, 1, 0.32, 1, duration: 0.28)) {
                revealed = true
            }
            // Cancellation when the window closes or Skip is pressed must not dismiss a later view.
            do { try await Task.sleep(for: .milliseconds(reduceMotion ? 250 : 850)) }
            catch { return }
            guard !Task.isCancelled else { return }
            dismiss(true)
        }
    }
}
