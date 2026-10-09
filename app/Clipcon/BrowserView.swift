import ImageIO
import SwiftUI

struct BrowserView: View {
    @Environment(AppModel.self) private var model
    private let columns = [GridItem(.adaptive(minimum: 200, maximum: 280), spacing: 16)]

    var body: some View {
        if model.clips.isEmpty {
            ContentUnavailableView {
                Label("No Footage Yet", systemImage: "film")
            } description: {
                Text("Import a source clip to transcribe its speech and describe sampled frames on this Mac.")
            } actions: {
                Button("Import Source Clip…") { model.showImport = true }
            }
        } else {
            ScrollView {
                LazyVGrid(columns: columns, spacing: 16) {
                    ForEach(model.visibleClips) { clip in
                        ClipCard(clip: clip, isSelected: model.selection == clip.id,
                                 liveStage: clip.status == .indexing ? model.activity?.stage : nil)
                            .onTapGesture { model.selection = clip.id }
                    }
                }
                .padding(16)
            }
            .focusable()
            .focusEffectDisabled()
            .onMoveCommand(perform: move)
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
        case .indexing, .pending:
            VStack(spacing: 6) {
                ProgressView().controlSize(.small)
                Text(liveStage ?? "Indexing").font(.caption)
            }
            .padding(10)
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
