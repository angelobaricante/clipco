import AVKit
import SwiftUI

/// The one AVPlayer in the window, pointed at a verified original. It publishes the playback position so the
/// inspector can highlight the transcript line being spoken.
@MainActor
@Observable
final class PreviewPlayer {
    let player = AVPlayer()
    private(set) var clipID: SourceClip.ID?
    private var revision: Int?
    private(set) var access: SourceAccess?
    /// Seconds into the shown Source clip, updated a few times a second while it plays.
    private(set) var currentTime: Double?

    init() {
        player.addPeriodicTimeObserver(forInterval: CMTime(seconds: 0.2, preferredTimescale: 600),
                                       queue: .main) { [weak self] time in
            MainActor.assumeIsolated { self?.currentTime = time.seconds.isFinite ? time.seconds : nil }
        }
    }

    /// Checks the original again whenever the clip or its analysed revision changes.
    func show(_ clip: SourceClip) async {
        guard clip.id != clipID || clip.revision != revision || access == nil else { return }
        clipID = clip.id
        revision = clip.revision
        access = nil
        currentTime = nil
        player.pause()
        let checked = await SourceAccess.check(clip)
        guard clipID == clip.id else { return }  // the selection moved on meanwhile
        access = checked
        if case .available(let url) = checked {
            player.replaceCurrentItem(with: AVPlayerItem(url: url))
        } else {
            player.replaceCurrentItem(with: nil)
        }
    }

    /// Plays from a source-relative time of the shown clip.
    func play(from seconds: Double) {
        player.seek(to: CMTime(seconds: seconds, preferredTimescale: 600), toleranceBefore: .zero,
                    toleranceAfter: .zero)
        player.play()
    }

    func pause() { player.pause() }
}

/// AppKit's standard AVKit player view. (SwiftUI's `VideoPlayer` aborts while loading its type metadata on
/// macOS 26.5 in this build, so the AppKit view is hosted directly.)
struct SystemPlayerView: NSViewRepresentable {
    let player: AVPlayer

    func makeNSView(context: Context) -> AVPlayerView {
        let view = AVPlayerView()
        view.controlsStyle = .floating
        view.player = player
        DispatchQueue.main.async { view.window?.makeFirstResponder(view) }  // Space plays and pauses
        return view
    }

    func updateNSView(_ view: AVPlayerView, context: Context) {
        if view.player !== player { view.player = player }
    }
}

/// Plays the selected clip's original over the footage browser, leaving the inspector beside it so its
/// transcript and context can be followed during playback.
struct PlayerOverlay: View {
    @Environment(AppModel.self) private var model
    let clip: SourceClip

    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(clip.displayLabel).font(.headline).lineLimit(1)
                    Text(clip.originalFilename).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        .truncationMode(.middle)
                }
                Spacer()
                Button("Close", systemImage: "xmark.circle.fill") { model.closePlayer() }
                    .labelStyle(.iconOnly)
                    .buttonStyle(.borderless)
                    .font(.title2)
                    .keyboardShortcut(.cancelAction)
                    .help("Close the player (Esc)")
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            Divider()
            Group {
                switch model.player.access {
                case .available?:
                    SystemPlayerView(player: model.player.player)
                        .accessibilityLabel("Original \(clip.originalFilename)")
                case nil:
                    ProgressView()
                case let state?:
                    ContentUnavailableView {
                        Label(state.title, systemImage: "film.slash")
                    } description: {
                        Text(state.detail)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(.black)
        }
        .background(.background)
        .onChange(of: model.selectedClip?.id) { _, id in
            if id != clip.id { model.closePlayer() }  // the inspector no longer shows what is playing
        }
    }
}

extension SourceAccess {
    var title: String {
        switch self {
        case .available: "Original Available"
        case .missing: "Original Not Found"
        case .changed: "Original Changed"
        case .unverified: "Not Yet Verified"
        }
    }

    var detail: String {
        switch self {
        case .available: "The original matches the indexed file."
        case .missing: "The file is not at its indexed location."
        case .changed: "The file changed since it was indexed, so it is not played."
        case .unverified: "Playback is available once analysis has checked the source."
        }
    }
}
