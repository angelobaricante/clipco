import SwiftUI
import UniformTypeIdentifiers

enum ImportDestination: Hashable {
    case library, project(String), newProject
}

struct ImportSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var destination: ImportDestination = .library
    @State private var name = ""
    @State private var context = ""
    @State private var sources: [URL] = []
    @State private var choosing = false
    @State private var submitting = false
    @State private var createdProjectID: String?

    private var chosenSummary: String {
        switch sources.count {
        case 0: "No clips or folders chosen"
        case 1: sources[0].lastPathComponent
        default: "\(sources.count) items chosen"
        }
    }

    var body: some View {
        Form {
            Section("Destination") {
                Picker("Add footage to", selection: $destination) {
                    Text("Footage Library").tag(ImportDestination.library)
                    ForEach(model.projects) { project in
                        Text(project.name).tag(ImportDestination.project(project.id))
                    }
                    Divider()
                    Text("New Project…").tag(ImportDestination.newProject)
                }
                if destination == .newProject {
                    TextField("Name", text: $name, prompt: Text("Water filter tutorial"))
                    TextField("Context", text: $context, prompt: Text("Optional: what is the intended video about?"),
                              axis: .vertical).lineLimit(2...4)
                }
            }
            .disabled(createdProjectID != nil)
            Section("Footage") {
                LabeledContent(chosenSummary) { Button("Choose…") { choosing = true } }
                if sources.count > 1 {
                    ForEach(sources, id: \.self) { url in
                        Label(url.lastPathComponent, systemImage: AppModel.isFolder(url) ? "folder" : "film")
                            .font(.callout).lineLimit(1).truncationMode(.middle)
                    }
                }
                Text("Add videos or folders. Originals stay where they are. Analysis runs locally, one clip at a time.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if let r = model.readiness, !model.canAnalyze {
                Section {
                    Label("Footage can be added now. Analysis waits for setup.",
                          systemImage: "clock").foregroundStyle(.secondary)
                    DisclosureGroup("Setup details") {
                        Text(r.detail).font(.caption)
                        Text(r.guidance).font(.caption).textSelection(.enabled)
                    }
                }
            }
            if submitting { ProgressView("Adding footage…").controlSize(.small) }
        }
        .formStyle(.grouped)
        .frame(width: 460)
        .disabled(submitting)
        .fileImporter(isPresented: $choosing, allowedContentTypes: [.folder, .movie], allowsMultipleSelection: true) {
            switch $0 {
            case .success(let urls): sources = urls
            case .failure(let error): model.errorMessage = error.localizedDescription
            }
        }
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel") { dismiss() }.disabled(submitting)
            }
            ToolbarItem(placement: .confirmationAction) {
                Button(createdProjectID == nil ? "Add Footage" : "Retry Adding Footage") {
                    let chosen = sources, target = destination
                    let projectName = name.trimmingCharacters(in: .whitespacesAndNewlines), projectContext = context
                    submitting = true
                    Task {
                        let projectID: String?
                        switch target {
                        case .library: projectID = nil
                        case .project(let id): projectID = id
                        case .newProject:
                            if let createdProjectID { projectID = createdProjectID }
                            else {
                            guard let created = await model.createProject(name: projectName, context: projectContext) else {
                                submitting = false
                                return
                            }
                            projectID = created.id
                            createdProjectID = created.id
                            }
                        }
                        if await model.enqueue(chosen, into: projectID) { dismiss() }
                        submitting = false
                    }
                }
                .disabled(submitting || sources.isEmpty || (destination == .newProject
                    && name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty))
            }
        }
        .onAppear {
            destination = model.scopeProjectID.map(ImportDestination.project) ?? .library
            if !model.hasScope { destination = .newProject }
        }
        .task { await model.refreshReadiness() }
    }
}

struct SetupSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        Form {
            Section("Local analysis") {
                if let r = model.readiness {
                    LabeledContent("State", value: r.state.rawValue.replacingOccurrences(of: "_", with: " "))
                    Text(r.detail).textSelection(.enabled)
                    if !r.guidance.isEmpty {
                        Text(r.guidance).font(.callout.monospaced()).textSelection(.enabled)
                    }
                    if let v = r.visionModel { LabeledContent("Vision model", value: v) }
                    if let s = r.speechModel { LabeledContent("Speech model", value: URL(filePath: s).lastPathComponent) }
                    if let o = r.ollamaVersion { LabeledContent("Ollama", value: o) }
                } else {
                    ProgressView()
                }
            }
            Section {
                Text("Clipco talks to Ollama on 127.0.0.1 only and never falls back to cloud inference.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            CodexSection()
        }
        .formStyle(.grouped)
        .frame(width: 560)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } }
            ToolbarItem {
                Button("Recheck") { Task { await model.refreshReadiness() } }
                    .disabled(model.isCheckingReadiness)
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("Load Model") { Task { await model.warmUp() } }
                    .disabled(model.readiness?.state != .cold && model.readiness?.state != .inferenceFailed)
            }
        }
    }
}

/// Codex MCP setup: the installed helper, the command that registers it, and a live connection test.
struct CodexSection: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Section("Codex connection (MCP)") {
            if let s = model.mcpStatus {
                LabeledContent("Test") {
                    if s.ok {
                        Label("Connected · \(s.tools.count) tools · \(s.projectCount ?? 0) Projects",
                              systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                    } else {
                        Label("Failed", systemImage: "xmark.octagon.fill").foregroundStyle(.red)
                    }
                }
                if let error = s.error { Text(error).font(.caption).textSelection(.enabled) }
                if s.ok, let connect = s.connectMs, let overview = s.overviewMs {
                    LabeledContent("Response", value: "start \(connect) ms · overview \(overview) ms")
                }
                LabeledContent("Helper") {
                    Text(s.serverCommand.first ?? "").font(.caption.monospaced()).textSelection(.enabled)
                        .lineLimit(2).truncationMode(.middle)
                }
                LabeledContent("Codex") {
                    Text(codexState(s)).foregroundStyle(s.codex.registered && !s.codexRegistrationDiffers
                                                        ? Color.primary : Color.orange)
                }
                VStack(alignment: .leading, spacing: 6) {
                    Text("Register Clipco with Codex in Terminal:").font(.callout)
                    Text(s.addCommand).font(.caption.monospaced()).textSelection(.enabled)
                        .padding(8).frame(maxWidth: .infinity, alignment: .leading)
                        .background(.quaternary.opacity(0.5), in: .rect(cornerRadius: 6))
                    HStack {
                        Button("Copy Command", systemImage: "doc.on.doc") {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(s.addCommand, forType: .string)
                        }
                        Spacer()
                        Text("MCP SDK \(s.sdkVersion) · protocol \(s.protocolVersion ?? "–")")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                Text("The helper reads the saved index only, so Codex can search while Clipco is closed. "
                     + "File paths it returns are locators, not new file permissions.")
                    .font(.caption).foregroundStyle(.secondary)
            } else if model.isCheckingMcp {
                ProgressView("Testing connection…").controlSize(.small)
            }
            Button("Test Connection") { Task { await model.checkMcp() } }
                .disabled(model.isCheckingMcp)
        }
        .task { if model.mcpStatus == nil { await model.checkMcp() } }
    }

    private func codexState(_ s: McpStatus) -> String {
        guard s.codex.path != nil else { return "Codex CLI not found" }
        if let error = s.codex.error { return "Could not query Codex: \(error)" }
        let version = s.codex.version ?? "unknown version"
        if s.codexRegistrationDiffers { return "\(version) · registered with a different command" }
        return s.codex.registered ? "\(version) · Clipco registered" : "\(version) · not registered yet"
    }
}
