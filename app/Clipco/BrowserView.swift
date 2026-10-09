import AppKit
import ImageIO
import SwiftUI

struct BrowserView: View {
    @Environment(AppModel.self) private var model
    private let columns = [GridItem(.adaptive(minimum: 200, maximum: 280), spacing: 16)]

    var body: some View {
        browser
            .safeAreaInset(edge: .top, spacing: 0) {
                if model.hasScope, !model.showingLibrary, model.trimmedQuery.isEmpty {
                    HStack {
                        Text("\(model.visibleClips.count) \(model.visibleClips.count == 1 ? "clip" : "clips")")
                            .font(.caption).foregroundStyle(.secondary)
                        Spacer()
                        @Bindable var model = model
                        Picker("Filter footage", selection: $model.filter) {
                            Text("All Footage").tag(FootageFilter.all)
                            Text("A-roll").tag(FootageFilter.aRoll)
                            Text("B-roll").tag(FootageFilter.bRoll)
                            Divider()
                            Text("Needs Review").tag(FootageFilter.needsReview)
                            Text("Excluded").tag(FootageFilter.excluded)
                        }
                        .pickerStyle(.menu)
                        .labelsHidden()
                        .fixedSize()
                        .help("Filter this Project’s footage by role or review status")
                    }
                    .padding(.horizontal, 16).padding(.vertical, 8)
                    .background(.bar)
                }
            }
    }

    @ViewBuilder private var browser: some View {
        if model.isLoadingScope || model.isStarting {
            ProgressView("Opening footage…").frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if !model.trimmedQuery.isEmpty {
            SearchResultsView()
        } else if !model.hasScope {
            ContentUnavailableView {
                Label("No Project Yet", systemImage: "folder.badge.plus")
            } description: {
                Text("Create a Project for a video idea, or drop videos and folders here to start one. "
                     + "Originals stay where they are.")
            } actions: {
                Button("New Project…") { model.showNewProject = true }
            }
        } else if model.clips.isEmpty {
            ContentUnavailableView {
                Label("No Footage Yet", systemImage: "film")
            } description: {
                Text("Drop videos or folders here, or import them, to transcribe speech and describe sampled "
                     + "frames on this Mac. Analysis is queued and runs one clip at a time.")
            } actions: {
                Button("Import Footage…") { model.showImport = true }
            }
        } else if model.visibleClips.isEmpty {
            ContentUnavailableView("No \(model.filter.rawValue) Clips", systemImage: model.filter.symbol,
                                   description: Text(model.filter == .excluded
                                       ? "Excluded clips stay out of new default searches. None are excluded."
                                       : "No clips in this Project match this filter."))
        } else if model.browserMode == .list {
            ClipTable()
        } else {
            ClipGrid(columns: columns)
        }
    }
}

/// Menu items shared by the grid and the list. Like Finder, acting on a selected clip acts on the whole selection.
struct ClipActions: View {
    @Environment(AppModel.self) private var model
    let targets: [SourceClip]

    var body: some View {
        let allExcluded = !targets.isEmpty && targets.allSatisfy(\.excluded)
        if targets.count == 1 {
            Button("Play", systemImage: "play") { Task { await model.openPlayer(targets[0].id) } }
            Button("Quick Look", systemImage: "eye") {
                model.select(targets[0].id)
                Task { await model.quickLook() }
            }
        }
        if !model.showingLibrary {
        Button(allExcluded ? "Include in Retrieval" : "Exclude from Retrieval",
               systemImage: allExcluded ? "eye" : "eye.slash") {
            Task { await model.setExcluded(targets, !allExcluded) }
        }
        }
        if model.canRetry(targets) {
            Button("Re-analyse", systemImage: "arrow.clockwise") { Task { await model.retry(targets) } }
        }
        let others = model.projects.filter { $0.id != model.project?.id }
        if !others.isEmpty {
            Menu("Add to Project", systemImage: "folder.badge.plus") {
                ForEach(others) { destination in
                    Button(destination.name) { Task { await model.addToProject(targets, destination) } }
                }
            }
        }
        Divider()
        if !model.showingLibrary {
        Button(targets.count == 1 ? "Remove from Project…" : "Remove \(targets.count) Clips from Project…",
               systemImage: "trash", role: .destructive) {
            model.clipsToRemove = targets
        }
        .disabled(!model.canDelete)
        }
        Button(targets.count == 1 ? "Remove from Library…" : "Remove \(targets.count) Clips from Library…",
               systemImage: "trash.slash", role: .destructive) {
            model.clipsToRemoveFromLibrary = targets
        }
        .disabled(!model.canDelete)
    }
}

/// The list view: a native table over the same clips, filter, and selection as the grid.
struct ClipTable: View {
    @Environment(AppModel.self) private var model
    @FocusState private var focused: Bool

    var body: some View {
        @Bindable var model = model
        Table(model.visibleClips, selection: $model.selection) {
            TableColumn("Clip") { clip in
                VStack(alignment: .leading, spacing: 1) {
                    Text(clip.displayLabel).lineLimit(1)
                    Text(clip.originalFilename).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        .truncationMode(.middle)
                }
            }
            .width(min: 180, ideal: 280)
            TableColumn("Role") { clip in Text(clip.roleLabel) }
                .width(min: 80, ideal: 110)
            TableColumn("Duration") { clip in Text(clip.duration?.timecode ?? "—").monospacedDigit() }
                .width(70)
            TableColumn("Status") { clip in
                let stage = clip.id == model.activity?.clipID ? model.activity?.stage : nil
                Text(stage ?? model.analysisStatus(clip))
                    .foregroundStyle([.failed, .stale, .missing].contains(clip.status) ? .orange : .primary)
            }
            .width(min: 80, ideal: 120)
            TableColumn("Retrieval") { clip in
                HStack(spacing: 4) {
                    if clip.excluded { Label("Excluded", systemImage: "eye.slash") }
                    if clip.note != nil { Label("Note", systemImage: "note.text").labelStyle(.iconOnly) }
                }
                .foregroundStyle(.secondary)
            }
            .width(min: 80, ideal: 100)
        }
        .contextMenu(forSelectionType: SourceClip.ID.self) { ids in
            ClipActions(targets: model.visibleClips.filter { ids.contains($0.id) })
        } primaryAction: { ids in
            guard ids.count == 1, let id = ids.first else { return }
            Task { await model.openPlayer(id) }
        }
        .focused($focused)
        .onChange(of: model.browserFocusRequest) { focused = true }
        .onKeyPress(.space) { model.playSelectedClip() ? .handled : .ignored }
        .onChange(of: model.selection) { _, new in
            if new.count == 1 { model.selectionAnchor = new.first }
        }
        .onDeleteCommand {
            if model.canDelete, !model.selectedClips.isEmpty {
                if model.showingLibrary { model.clipsToRemoveFromLibrary = model.selectedClips }
                else { model.clipsToRemove = model.selectedClips }
            }
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
    @State private var viewportWidth: CGFloat = 0
    @State private var scrollTarget: SourceClip.ID?
    @State private var keyboardRangeAnchor: SourceClip.ID?
    @State private var marquee: Marquee?
    @FocusState private var focused: Bool  // like Finder, clicking the browser makes it take keyboard input

    private struct Marquee {
        var start: CGPoint
        var rect: CGRect
        var base: Set<SourceClip.ID>
        var modifiers: NSEvent.ModifierFlags
    }

    var body: some View {
        ScrollViewReader { proxy in
        ScrollView {
            LazyVGrid(columns: columns, spacing: 16) {
                ForEach(model.visibleClips) { clip in
                    ClipCard(clip: clip, isSelected: model.selection.contains(clip.id),
                             liveStage: clip.id == model.activity?.clipID ? model.activity?.stage : nil)
                        .onGeometryChange(for: CGRect.self) { $0.frame(in: .named(Self.space)) } action: {
                            frames[clip.id] = $0
                        }
                        .onTapGesture(count: 2) { Task { await model.openPlayer(clip.id) } }
                        // Recognize selection independently of the double-click timeout.
                        .simultaneousGesture(TapGesture().onEnded { click(clip.id) })
                        .id(clip.id)
                        .accessibilityAction { click(clip.id) }
                        .accessibilityAction(named: "Play") { Task { await model.openPlayer(clip.id) } }
                        .contextMenu {
                            ClipActions(targets: model.selection.contains(clip.id) ? model.selectedClips : [clip])
                        }
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
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { viewportWidth = $0 }
        .focusable(interactions: .edit)
        .focused($focused)
        .focusEffectDisabled()
        .onAppear { focused = true }
        .onChange(of: model.browserFocusRequest) { focused = true }
        .onChange(of: scrollTarget) { _, id in
            if let id { proxy.scrollTo(id) }
        }
        .onKeyPress(keys: [.leftArrow, .rightArrow, .upArrow, .downArrow]) { press in
            let direction: MoveCommandDirection
            switch press.key {
            case .leftArrow: direction = .left
            case .rightArrow: direction = .right
            case .upArrow: direction = .up
            case .downArrow: direction = .down
            default: return .ignored
            }
            move(direction, extending: press.modifiers.contains(.shift))
            return .handled
        }
        .onCommand(#selector(NSResponder.selectAll(_:))) {  // ⌘A
            model.selection = Set(model.visibleClips.map(\.id))
        }
        .onDeleteCommand {  // the Delete key and Edit ▸ Delete
            if model.canDelete, !model.selectedClips.isEmpty {
                if model.showingLibrary { model.clipsToRemoveFromLibrary = model.selectedClips }
                else { model.clipsToRemove = model.selectedClips }
            }
        }
        .onKeyPress(.space) { model.playSelectedClip() ? .handled : .ignored }
        }
    }

    private nonisolated static let space = "clip-grid"

    private func click(_ id: SourceClip.ID) {
        focused = true
        keyboardRangeAnchor = nil
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

    private func move(_ direction: MoveCommandDirection, extending: Bool) {
        let ids = model.visibleClips.map(\.id)
        guard !ids.isEmpty else { return }
        guard let current = model.selectionAnchor.flatMap(ids.firstIndex(of:)) else {
            model.select(ids.first)
            return
        }
        let columnCount = max(1, Int((viewportWidth - 32 + 16) / (200 + 16)))
        let next: Int
        switch direction {
        case .left: next = max(current - 1, 0)
        case .right: next = min(current + 1, ids.count - 1)
        case .up: next = max(current - columnCount, 0)
        case .down: next = min(current + columnCount, ids.count - 1)
        @unknown default: return
        }
        if extending {
            if keyboardRangeAnchor == nil { keyboardRangeAnchor = ids[current] }
            let anchor = keyboardRangeAnchor.flatMap(ids.firstIndex(of:)) ?? current
            model.selection = Set(ids[min(anchor, next)...max(anchor, next)])
            model.selectionAnchor = ids[next]
        } else {
            keyboardRangeAnchor = nil
            model.select(ids[next])
        }
        scrollTarget = ids[next]
    }
}

struct ClipCard: View {
    @Environment(AppModel.self) private var model
    let clip: SourceClip
    let isSelected: Bool
    let liveStage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Rectangle().fill(.quaternary)
                .aspectRatio(16 / 9, contentMode: .fit)
                .overlay { FrameImage(path: clip.thumbnailPath) }
                .clipShape(.rect(cornerRadius: 6))
                .overlay(alignment: .bottomLeading) { statusOverlay.padding(6) }
                .overlay {
                    RoundedRectangle(cornerRadius: 6)
                        .strokeBorder(isSelected ? Color.accentColor : .clear, lineWidth: 3)
                }
            HStack(spacing: 4) {
                Text(clip.displayLabel).font(.headline).lineLimit(1)
                if clip.note != nil {
                    Image(systemName: "note.text").foregroundStyle(.secondary).accessibilityLabel("Has creator note")
                }
            }
            Text(clip.originalFilename).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                .truncationMode(.middle)
            HStack(spacing: 6) {
                if let duration = clip.duration { Text(duration.timecode) }
                Text(clip.roleLabel)
                if clip.excluded { Label("Excluded", systemImage: "eye.slash").foregroundStyle(.secondary) }
            }
            .font(.caption).foregroundStyle(.secondary)
        }
        .padding(6)
        .opacity(clip.excluded ? 0.6 : 1)
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
            Label(model.analysisStatus(clip), systemImage: "clock")
                .font(.caption).padding(8)
                .background(.regularMaterial, in: .rect(cornerRadius: 8))
        case .failed, .stale, .missing:
            Label(clip.status == .failed ? "Failed" : clip.status == .stale ? "Out of date" : "Original not found",
                  systemImage: clip.status == .failed ? "exclamationmark.triangle.fill"
                      : clip.status == .stale ? "clock.badge.exclamationmark" : "questionmark.folder")
                .font(.caption).padding(8)
                .background(.regularMaterial, in: .rect(cornerRadius: 8))
                .foregroundStyle(.orange)
        case .ready:
            EmptyView()
        }
    }
}

/// Saved-index search results: compact excerpts with source ranges and suggested relationships.
struct SearchResultsView: View {
    @Environment(AppModel.self) private var model
    @FocusState private var focused: Bool

    var body: some View {
        if let page = model.searchResults, !page.results.isEmpty {
            List(page.results, selection: Binding(
                get: { model.selectedHit },
                set: { id in
                    model.selectedHit = id
                    if let hit = page.results.first(where: { $0.id == id }) { model.select(hit.clipId) }
                    else { model.select(nil) }
                })
            ) { hit in
                SearchHitRow(hit: hit).tag(hit.id)
            }
            .focused($focused)
            .disabled(page.query != model.trimmedQuery)
            .onChange(of: model.browserFocusRequest) { focused = true }
            .onKeyPress(.space) { model.playSelectedClip() ? .handled : .ignored }
            .contextMenu(forSelectionType: SearchHit.ID.self) { ids in
                Button("Play Matching Segment", systemImage: "play") {
                    if let hit = page.results.first(where: { ids.contains($0.id) }) {
                        model.selectedHit = hit.id
                        Task { await model.openPlayer(hit.clipId, at: hit.start) }
                    }
                }.disabled(ids.count != 1)
            } primaryAction: { ids in
                if let hit = page.results.first(where: { ids.contains($0.id) }), ids.count == 1 {
                    model.selectedHit = hit.id
                    Task { await model.openPlayer(hit.clipId, at: hit.start) }
                }
            }
            .safeAreaInset(edge: .bottom) {
                HStack {
                Text(page.truncated ? "Top \(page.results.count) of \(page.totalMatches) matching segments"
                                    : "\(page.totalMatches) matching segments")
                Spacer()
                if model.isSearching || page.query != model.trimmedQuery {
                    ProgressView("Updating…").controlSize(.small)
                } else if page.nextOffset != nil {
                    Button("Show More") { Task { await model.search(loadMore: true) } }
                }
                }.font(.caption).foregroundStyle(.secondary).padding(8).background(.bar)
            }
        } else if model.isSearching || model.searchResults == nil {
            ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            ContentUnavailableView.search(text: model.searchText)
        }
    }
}

struct SearchHitRow: View {
    @Environment(AppModel.self) private var model
    let hit: SearchHit

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(hit.label).font(.headline).lineLimit(1)
                Spacer()
                Text("\(hit.start.timecode)–\(hit.end.timecode)").font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
            if hit.fit == nil { Text("“\(hit.excerpt)”").lineLimit(3) }  // a library fit explanation quotes it
            HStack(spacing: 6) {
                Text(hit.originalFilename).lineLimit(1).truncationMode(.middle)
                Text("· from \(hit.evidenceName)")
                if hit.excluded { Text("· excluded").foregroundStyle(.orange) }
                if hit.status != .ready { Text("· \(hit.status.rawValue)").foregroundStyle(.orange) }
            }
            .font(.caption).foregroundStyle(.secondary)
            if let fit = hit.fit {  // library results: how it supports the request, and where it comes from
                Label(fit.explanation, systemImage: fit.kind == "metaphorical" ? "sparkle"
                                                    : fit.kind == "emotional" ? "heart" : "eye")
                    .font(.caption).lineLimit(3)
                HStack(spacing: 6) {
                    Text(fit.kind.capitalized + " fit")
                    if let origins = hit.origins {
                        Text("· " + (origins.isEmpty ? "Library only" : origins.map(\.name).joined(separator: ", ")))
                    }
                    if fit.currentProject && !model.showingLibrary { Text("· this Project") }
                }
                .font(.caption).foregroundStyle(.secondary)
                if let caution = fit.caution { Text(caution).font(.caption).foregroundStyle(.orange).lineLimit(2) }
            }
            if let tone = hit.tone {
                Text("Tone: " + SegmentTone.summary(state: tone.state, tones: tone.tones))
                    .font(.caption).foregroundStyle(.secondary)
            }
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
        Rectangle().fill(.quaternary).overlay {
            GeometryReader { geometry in
            if let image {
                Image(decorative: image, scale: 1).resizable().scaledToFit()
                    .frame(width: geometry.size.width, height: geometry.size.height)
            } else {
                Image(systemName: "film").font(.title).foregroundStyle(.tertiary)
                    .frame(width: geometry.size.width, height: geometry.size.height)
            }
            }
        }
        .clipped()
        .task(id: path) {
            image = nil
            let loaded = await Self.load(path)
            guard !Task.isCancelled else { return }
            image = loaded
        }
    }

    @concurrent
    static func load(_ path: String?) async -> CGImage? {
        guard let path, let source = CGImageSourceCreateWithURL(URL(filePath: path) as CFURL, nil) else {
            return nil
        }
        return CGImageSourceCreateThumbnailAtIndex(source, 0, [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceThumbnailMaxPixelSize: 640,
            kCGImageSourceCreateThumbnailWithTransform: true
        ] as CFDictionary)
    }
}
