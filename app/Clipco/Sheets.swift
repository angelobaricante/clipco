import SwiftUI
import UniformTypeIdentifiers

struct ImportSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var addToCurrent = true
    @State private var name = ""
    @State private var context = ""
    @State private var sources: [URL] = []
    @State private var choosing = false

    private var chosenSummary: String {
        switch sources.count {
        case 0: "No clips or folders chosen"
        case 1: sources[0].lastPathComponent
        default: "\(sources.count) items chosen"
        }
    }

    private var creatingProject: Bool { model.project == nil || !addToCurrent }

    var body: some View {
        Form {
            Section("Project") {
                if let project = model.project {
                    Picker("Destination", selection: $addToCurrent) {
                        Text(project.name).tag(true)
                        Text("New Project").tag(false)
                    }
                }
                if creatingProject {
                    TextField("Name", text: $name, prompt: Text("Water filter tutorial"))
                    TextField("Context", text: $context, prompt: Text("What is the intended video about?"),
                              axis: .vertical)
                        .lineLimit(2...4)
                } else if let project = model.project, !project.context.isEmpty {
                    LabeledContent("Context", value: project.context)
                }
            }
            Section("Footage") {
                LabeledContent(chosenSummary) {
                    Button("Choose…") { choosing = true }
                }
                if sources.count > 1 {
                    ForEach(sources, id: \.self) { url in
                        Label(url.lastPathComponent, systemImage: url.hasDirectoryPath ? "folder" : "film")
                            .font(.callout).lineLimit(1).truncationMode(.middle)
                    }
                }
                Text("Choose clips and folders — ⌘-click or ⇧-click to choose several. Every video inside a chosen "
                     + "folder is imported. Originals are only read. Analysis runs locally with whisper.cpp and Ollama.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if let r = model.readiness, !model.canAnalyze {
                Section {
                    Label(r.detail, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                    Text(r.guidance).font(.caption).textSelection(.enabled)
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 460)
        .fileImporter(isPresented: $choosing, allowedContentTypes: [.folder, .movie], allowsMultipleSelection: true) { result in
            if case .success(let urls) = result { sources = urls }
        }
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button("Analyze") {
                    guard !sources.isEmpty else { return }
                    let projectName = creatingProject ? name.trimmingCharacters(in: .whitespaces) : nil
                    let context = context
                    dismiss()
                    let chosen = sources
                    Task { await model.importFootage(chosen, newProjectName: projectName, context: context) }
                }
                .disabled(sources.isEmpty || (creatingProject && name.trimmingCharacters(in: .whitespaces).isEmpty)
                          || !model.canAnalyze || model.activity != nil)
            }
        }
        .task { await model.refreshReadiness() }
    }
}

struct SetupSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        Form {
            Section {
                Image("ClipcoLogo")
                    .resizable()
                    .scaledToFit()
                    .frame(width: 180, height: 60)
                    .foregroundStyle(.primary)
                    .accessibilityLabel("Clipco")
                    .padding(.vertical, 6)
            }
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
