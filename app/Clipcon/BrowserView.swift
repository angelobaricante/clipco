import AppKit
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
            ClipGrid(columns: columns)
        }
    }
}

/// The footage grid with Finder-style selection: click, ⌘-click, ⇧-click, ⌘A, arrow keys, and dragging a
/// selection rectangle from empty space (⇧ adds to the selection, ⌘ toggles).
struct ClipGrid: View {
    @Environment(AppModel.self) private var model
    let columns: [GridItem]

    @State private var frames: [SourceClip.ID: CGRect] = [:]
    @State private var viewportHeight: CGFloat = 0
    @State private var marquee: Marquee?
    @FocusState private var focused: Bool  // like Finder, clicking the browser makes it take keyboard input

    private struct Marquee {
        var start: CGPoint
        var rect: CGRect
        var base: Set<SourceClip.ID>
        var modifiers: NSEvent.ModifierFlags
    }

    var body: some View {
        ScrollView {
            LazyVGrid(columns: columns, spacing: 16) {
                ForEach(model.visibleClips) { clip in
                    ClipCard(clip: clip, isSelected: model.selection.contains(clip.id),
                             liveStage: clip.id == model.activity?.clipID ? model.activity?.stage : nil)
                        .onGeometryChange(for: CGRect.self) { $0.frame(in: .named(Self.space)) } action: {
                            frames[clip.id] = $0
                        }
                        .onTapGesture { click(clip.id) }
                        .contextMenu { contextMenu(for: clip) }
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, minHeight: viewportHeight, alignment: .top)
            .background {  // empty space: a click clears the selection, a drag draws the selection rectangle
                Color.clear.contentShape(.rect)
                    .onTapGesture {
                        focused = true
                        model.select(nil)
                    }
                    .gesture(DragGesture(minimumDistance: 3, coordinateSpace: .named(Self.space))
                        .onChanged(drag).onEnded { _ in marquee = nil })
            }
            .overlay(alignment: .topLeading) {
                if let rect = marquee?.rect {
                    Rectangle()
                        .fill(Color.accentColor.opacity(0.15))
                        .strokeBorder(Color.accentColor.opacity(0.7), lineWidth: 1)
                        .frame(width: rect.width, height: rect.height)
                        .offset(x: rect.minX, y: rect.minY)
                        .allowsHitTesting(false)
                }
            }
            .coordinateSpace(.named(Self.space))
        }
        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { viewportHeight = $0 }
        .focusable()
        .focused($focused)
        .focusEffectDisabled()
        .onAppear { focused = true }
        .onMoveCommand(perform: move)
        .onCommand(#selector(NSResponder.selectAll(_:))) {  // ⌘A
            model.selection = Set(model.visibleClips.map(\.id))
        }
        .onDeleteCommand {  // the Delete key and Edit ▸ Delete
            if model.canDelete, !model.selectedClips.isEmpty { model.clipsToRemove = model.selectedClips }
        }
    }

    private nonisolated static let space = "clip-grid"

    private func click(_ id: SourceClip.ID) {
        focused = true
        let modifiers = NSEvent.modifierFlags
        if modifiers.contains(.command) {
            model.selection.formSymmetricDifference([id])
            model.selectionAnchor = id
        } else if modifiers.contains(.shift), let anchor = model.selectionAnchor,
                  let from = model.visibleClips.firstIndex(where: { $0.id == anchor }),
                  let to = model.visibleClips.firstIndex(where: { $0.id == id }) {
            model.selection = Set(model.visibleClips[min(from, to)...max(from, to)].map(\.id))
        } else {
            model.select(id)
        }
    }

    private func drag(_ value: DragGesture.Value) {
        if marquee == nil {
            focused = true
            let modifiers = NSEvent.modifierFlags
            let keep = modifiers.contains(.shift) || modifiers.contains(.command)
            marquee = Marquee(start: value.startLocation, rect: .zero, base: keep ? model.selection : [],
                              modifiers: modifiers)
        }
        guard var current = marquee else { return }
        current.rect = CGRect(x: min(current.start.x, value.location.x), y: min(current.start.y, value.location.y),
                              width: abs(value.location.x - current.start.x),
                              height: abs(value.location.y - current.start.y))
        marquee = current
        let visible = Set(model.visibleClips.map(\.id))
        let touched = Set(frames.filter { visible.contains($0.key) && $0.value.intersects(current.rect) }.keys)
        model.selection = current.modifiers.contains(.command) ? current.base.symmetricDifference(touched)
                                                               : current.base.union(touched)
        if let first = model.visibleClips.first(where: { touched.contains($0.id) }) { model.selectionAnchor = first.id }
    }

    @ViewBuilder private func contextMenu(for clip: SourceClip) -> some View {
        // Like Finder: acting on a selected clip acts on the whole selection.
        let targets = model.selection.contains(clip.id) ? model.selectedClips : [clip]
        Button(targets.count == 1 ? "Remove from Project…" : "Remove \(targets.count) Clips from Project…",
               systemImage: "trash", role: .destructive) {
            model.clipsToRemove = targets
        }
        .disabled(!model.canDelete)
    }

    private func move(_ direction: MoveCommandDirection) {
        let ids = model.visibleClips.map(\.id)
        guard let current = model.selectionAnchor.flatMap(ids.firstIndex(of:)) else {
            model.select(ids.first)
            return
        }
        switch direction {
        case .left, .up: model.select(ids[max(current - 1, 0)])
        case .right, .down: model.select(ids[min(current + 1, ids.count - 1)])
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
                    if let hit = page.results.first(where: { $0.id == id }) { model.select(hit.clipId) }
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
