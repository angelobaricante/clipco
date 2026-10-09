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
