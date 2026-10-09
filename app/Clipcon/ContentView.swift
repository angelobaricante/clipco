import SwiftUI

struct ContentView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        NavigationSplitView {
            SidebarView()
                .navigationSplitViewColumnWidth(min: 190, ideal: 220)
        } detail: {
            BrowserView()
                .navigationTitle(model.project?.name ?? "Clipcon")
                .navigationSubtitle(model.trimmedQuery.isEmpty ? model.filter.rawValue : "Search")
                .searchable(text: $model.searchText, placement: .toolbar, prompt: "Search footage context")
                .task(id: model.searchText) {
                    try? await Task.sleep(for: .milliseconds(250))  // debounce typing
                    guard !Task.isCancelled else { return }
                    await model.search()
                }
        }
        .inspector(isPresented: $model.showInspector) {
            InspectorView()
                .inspectorColumnWidth(min: 280, ideal: 340, max: 520)
        }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button("Import", systemImage: "square.and.arrow.down") { model.showImport = true }
                    .help("Import a footage folder or source clip (⇧⌘I)")
            }
            ToolbarItem(placement: .primaryAction) {
                Button("Inspector", systemImage: "sidebar.trailing") { model.showInspector.toggle() }
                    .help("Show or hide the inspector (⌘I)")
            }
        }
        .sheet(isPresented: $model.showImport) { ImportSheet() }
        .sheet(isPresented: $model.showSetup) { SetupSheet() }
        .alert("Something went wrong", isPresented: Binding(
            get: { model.errorMessage != nil }, set: { if !$0 { model.errorMessage = nil } })
        ) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(model.errorMessage ?? "")
        }
    }
}

struct SidebarView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        List(selection: $model.filter) {
            Section(model.project?.name ?? "No Project") {
                ForEach(FootageFilter.allCases) { filter in
                    Label(filter.rawValue, systemImage: filter.symbol)
                        .badge(model.count(filter))
                        .tag(filter)
                }
            }
        }
        .safeAreaInset(edge: .bottom) {
            VStack(alignment: .leading, spacing: 8) {
                if let activity = model.activity {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        VStack(alignment: .leading) {
                            Text(activity.filename).lineLimit(1).truncationMode(.middle)
                            Text(activity.stage).foregroundStyle(.secondary)
                        }
                        .font(.caption)
                    }
                    .accessibilityElement(children: .combine)
                }
                ReadinessBadge()
            }
            .padding(12)
        }
    }
}

struct ReadinessBadge: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Button {
            model.showSetup = true
        } label: {
            HStack(spacing: 6) {
                Image(systemName: symbol).foregroundStyle(tint)
                Text(title).font(.caption)
                Spacer(minLength: 0)
            }
        }
        .buttonStyle(.plain)
        .help(model.readiness?.detail ?? "Checking local models")
        .accessibilityLabel("Analysis readiness: \(title)")
    }

    private var title: String {
        guard let r = model.readiness else { return "Checking…" }
        return switch r.state {
        case .ready: "Local models ready"
        case .cold: "Models installed"
        case .loading: "Loading model…"
        case .modelMissing: "Model missing"
        case .serviceUnavailable: "Ollama not running"
        case .toolsMissing: "Media tools missing"
        case .workerUnavailable: "Worker unavailable"
        case .inferenceFailed: "Inference failed"
        }
    }

    private var symbol: String {
        switch model.readiness?.state {
        case .ready, .cold: "checkmark.circle.fill"
        case .loading, nil: "hourglass"
        default: "exclamationmark.triangle.fill"
        }
    }

    private var tint: Color {
        switch model.readiness?.state {
        case .ready, .cold: .green
        case .loading, nil: .secondary
        default: .orange
        }
    }
}
