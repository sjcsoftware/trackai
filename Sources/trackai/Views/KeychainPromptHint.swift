import AppKit
import SwiftUI

/// The Keychain dialog belongs to macOS and cannot carry extra text, so while
/// it is up trackai floats a note under the menu bar pointing at the setting
/// that makes it go away for good.
enum KeychainPromptHint {
    private static var panel: NSPanel?

    /// Called from the thread about to block on the dialog.
    static func show() {
        // A read on the main thread is a CLI mode: nothing can draw until it
        // returns, so say it on stderr instead.
        guard !Thread.isMainThread else {
            FileHandle.standardError.write(Data(("trackai: macOS is asking for your password to read Claude Code's login. "
                + "To stop this for good, turn on \"Skip the Keychain password prompt\" in trackai Settings → Providers.\n").utf8))
            return
        }
        DispatchQueue.main.async(execute: present)
    }

    static func hide() {
        guard !Thread.isMainThread else { return }
        DispatchQueue.main.async {
            panel?.orderOut(nil)
            panel = nil
        }
    }

    private static func present() {
        guard panel == nil, let screen = NSScreen.main else { return }
        let hosting = NSHostingView(rootView: KeychainHintView())
        let size = hosting.fittingSize
        let p = NSPanel(contentRect: NSRect(origin: .zero, size: size),
                        styleMask: [.nonactivatingPanel, .borderless],
                        backing: .buffered, defer: false)
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = true
        p.level = .statusBar
        p.collectionBehavior = [.canJoinAllSpaces, .stationary]
        p.contentView = hosting
        let frame = screen.visibleFrame
        p.setFrameOrigin(NSPoint(x: frame.midX - size.width / 2, y: frame.maxY - size.height - 10))
        p.orderFrontRegardless()
        panel = p
    }
}

struct KeychainHintView: View {
    @ObservedObject var settings = Settings.shared

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            ProviderMarkView(kind: .claude, size: 18)
            VStack(alignment: .leading, spacing: 2) {
                Text("trackai is reading your Claude Code login")
                    .font(.system(size: 12, weight: .semibold))
                Text(settings.claudeSkipKeychainPrompt
                     ? "Turned on. Answer this prompt once; it will not come back."
                     : "Skip this prompt for good in Settings → Providers.")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            if !settings.claudeSkipKeychainPrompt {
                Button("Turn on") { settings.claudeSkipKeychainPrompt = true }
                    .controlSize(.small)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .frame(width: 400)
        .background(GlassBackground())
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.12), lineWidth: 0.5)
        )
    }
}
