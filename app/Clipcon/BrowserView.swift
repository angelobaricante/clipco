import ImageIO
import SwiftUI

struct BrowserView: View {
    @Environment(AppModel.self) private var model
    private let columns = [GridItem(.adaptive(minimum: 200, maximum: 280), spacing: 16)]

    var body: some View {
        if !model.trimmedQuery.isEmpty {
            SearchResultsView()
        } else if model.clips.isEmpty {
            ContentUnavailableView {
                Label("No Footage Yet", systemImage: "film")
            } description: {
                Text("Import a folder of A-roll and B-roll, or a single clip, to transcribe speech and describe "
                     + "sampled frames on this Mac.")
            } actions: {
                Button("Import Footage…") { model.showImport = true }
            }
        } else {
            ScrollView {
                LazyVGrid(columns: columns, spacing: 16) {
                    ForEach(model.visibleClips) { clip in
                        ClipCard(clip: clip, isSelected: model.selection == clip.id,
                                 liveStage: clip.id == model.activity?.clipID ? model.activity?.stage : nil)
                            .onTapGesture { model.selection = clip.id }
                            .contextMenu {
                                Button("Remove from Project…", systemImage: "trash", role: .destructive) {
                                    model.clipToRemove = clip
                                }
                                .disabled(!model.canDelete)
                            }
                    }
                }
                .padding(16)
            }
            .focusable()
            .focusEffectDisabled()
            .onMoveCommand(perform: move)
            .onDeleteCommand {  // the Delete key and Edit ▸ Delete
                if model.canDelete, let clip = model.selectedClip { model.clipToRemove = clip }
            }
        }
    }

    private func move(_ direction: MoveCommandDirection) {
        let ids = model.visibleClips.map(\.id)
        guard let current = model.selection.flatMap(ids.firstIndex(of:)) else {
            model.selection = ids.first
            return
        }
        switch direction {
        case .left, .up: model.selection = ids[max(current - 1, 0)]
        case .right, .down: model.selection = ids[min(current + 1, ids.count - 1)]
        @unknown default: break
        }
    }
}

struct ClipCard: View {
    let clip: SourceClip
    let isSelected: Bool
    let liveStage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            FrameImage(path: clip.thumbnailPath)
                .aspectRatio(16 / 9, contentMode: .fit)
                .clipShape(.rect(cornerRadius: 6))
                .overlay(alignment: .center) { statusOverlay }
                .overlay {
                    RoundedRectangle(cornerRadius: 6)
                        .strokeBorder(isSelected ? Color.accentColor : .clear, lineWidth: 3)
                }
            Text(clip.displayLabel).font(.headline).lineLimit(1)
            Text(clip.originalFilename).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                .truncationMode(.middle)
            HStack(spacing: 6) {
                if let duration = clip.duration { Text(duration.timecode) }
                if let role = clip.role { Text(role == "a-roll" ? "A-roll" : "B-roll") }
            }
            .font(.caption2).foregroundStyle(.tertiary)
        }
        .padding(6)
        .contentShape(.rect)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(isSelected ? [.isSelected, .isButton] : .isButton)
    }

    @ViewBuilder private var statusOverlay: some View {
        switch clip.status {
        case .indexing:
            VStack(spacing: 6) {
                ProgressView().controlSize(.small)
                Text(liveStage ?? "Indexing").font(.caption)
            }
            .padding(10)
            .background(.regularMaterial, in: .rect(cornerRadius: 8))
        case .pending:
            Label("Waiting", systemImage: "clock")
                .font(.caption).padding(8)
                .background(.regularMaterial, in: .rect(cornerRadius: 8))
        case .failed:
            Label("Failed", systemImage: "exclamationmark.triangle.fill")
                .font(.caption).padding(8)
                .background(.regularMaterial, in: .rect(cornerRadius: 8))
                .foregroundStyle(.orange)
        default:
            EmptyView()
        }
    }
}

/// Saved-index search results: compact excerpts with source ranges and suggested relationships.
struct SearchResultsView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if let page = model.searchResults, !page.results.isEmpty {
            List(page.results, selection: Binding(
                get: { model.selectedHit },
                set: { id in
                    model.selectedHit = id
                    if let hit = page.results.first(where: { $0.id == id }) { model.selection = hit.clipId }
                })
            ) { hit in
                SearchHitRow(hit: hit).tag(hit.id)
            }
            .safeAreaInset(edge: .bottom) {
                Text(page.truncated ? "Top \(page.results.count) of \(page.totalMatches) matching segments"
                                    : "\(page.totalMatches) matching segments")
                    .font(.caption).foregroundStyle(.secondary).padding(8)
            }
        } else if model.isSearching || model.searchResults == nil {
            ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            ContentUnavailableView.search(text: model.searchText)
        }
    }
}

struct SearchHitRow: View {
    let hit: SearchHit

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(hit.label).font(.headline).lineLimit(1)
                Spacer()
                Text("\(hit.start.timecode)–\(hit.end.timecode)").font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
            Text("“\(hit.excerpt)”").lineLimit(3)
            HStack(spacing: 6) {
                Text(hit.originalFilename).lineLimit(1).truncationMode(.middle)
                Text("· from \(hit.evidenceBasis)")
                if hit.status != .ready { Text("· \(hit.status.rawValue)").foregroundStyle(.orange) }
            }
            .font(.caption).foregroundStyle(.secondary)
            ForEach(hit.relationships) { related in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Image(systemName: related.symbol).foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 1) {
                        Text("\(related.title) · suggested").font(.caption.weight(.semibold))
                        Text("\(related.originalFilename) \(related.start.timecode)–\(related.end.timecode): "
                             + "“\(related.excerpt)”")
                            .font(.caption).lineLimit(2)
                    }
                }
                .help(related.basis)
                .accessibilityElement(children: .combine)
            }
            .padding(.leading, 4)
        }
        .padding(.vertical, 4)
    }
}

/// A sampled frame saved by the worker, decoded off the main thread.
struct FrameImage: View {
    let path: String?
    @State private var image: CGImage?

    var body: some View {
        ZStack {
            Rectangle().fill(.quaternary)
            if let image {
                Image(decorative: image, scale: 1).resizable().scaledToFill()
            } else {
                Image(systemName: "film").font(.title).foregroundStyle(.tertiary)
            }
        }
        .task(id: path) { image = await Self.load(path) }
    }

    @concurrent
    static func load(_ path: String?) async -> CGImage? {
        guard let path, let source = CGImageSourceCreateWithURL(URL(filePath: path) as CFURL, nil) else {
            return nil
        }
        return CGImageSourceCreateImageAtIndex(source, 0, nil)
    }
}
