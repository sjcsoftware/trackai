import AppKit
import SwiftUI
import Combine

/// Blurred backdrop for the panel; intensity follows the appearance settings.
struct GlassBackground: NSViewRepresentable {
    @ObservedObject var settings = Settings.shared

    func makeNSView(context: Context) -> NSVisualEffectView {
        let v = NSVisualEffectView()
        v.blendingMode = .behindWindow
        v.state = .active
        v.wantsLayer = true
        v.layer?.cornerRadius = 18
        v.layer?.cornerCurve = .continuous
        v.layer?.masksToBounds = true
        return v
    }

    func updateNSView(_ v: NSVisualEffectView, context: Context) {
        if settings.opaqueBackground {
            v.material = .windowBackground
        } else if settings.transparency > 0.66 {
            v.material = .hudWindow
        } else if settings.transparency > 0.33 {
            v.material = .popover
        } else {
            v.material = .underWindowBackground
        }
    }
}

struct PanelRootView: View {
    @ObservedObject var state: AppState
    var openSettings: () -> Void

    var body: some View {
        PanelView(state: state, openSettings: openSettings)
            .background(GlassBackground())
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .strokeBorder(Color.primary.opacity(0.12), lineWidth: 0.5)
            )
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    let state = AppState()
    private var statusItem: NSStatusItem!
    private var panel: NSPanel?
    private var hosting: NSHostingView<PanelRootView>?
    private var settingsWindow: NSWindow?
    private var clickMonitor: Any?
    private var cancellables = Set<AnyCancellable>()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.image = StatusIcon.gauge(percent: nil, color: .systemGray)
            button.imagePosition = .imageLeft
            button.action = #selector(togglePanel)
            button.target = self
        }

        // Re-render the icon whenever data or settings change.
        for publisher in [state.objectWillChange.eraseToAnyPublisher(),
                          Settings.shared.objectWillChange.eraseToAnyPublisher()] {
            publisher
                .receive(on: DispatchQueue.main)
                .sink { [weak self] _ in
                    DispatchQueue.main.async { self?.updateIcon() }
                }
                .store(in: &cancellables)
        }

        state.start()
    }

    private func updateIcon() {
        guard let button = statusItem?.button else { return }
        let settings = Settings.shared
        let percent = state.menuBarPercent
        let color = percent.map { settings.usageNSColor(percent: $0) } ?? .systemGray
        button.image = StatusIcon.image(percent: percent, color: color, glyph: state.menuBarProviderGlyph)
        if settings.showPercentInMenuBar, let percent {
            button.title = String(format: " %.0f%%", percent)
            button.font = NSFont.monospacedDigitSystemFont(ofSize: 11, weight: .medium)
        } else {
            button.title = ""
        }
        resizePanel()
    }

    // MARK: - Panel

    @objc private func togglePanel() {
        if let panel, panel.isVisible {
            closePanel()
        } else {
            showPanel()
        }
    }

    private func showPanel() {
        state.refresh()

        let root = PanelRootView(state: state) { [weak self] in self?.openSettings() }
        let hosting = NSHostingView(rootView: root)
        hosting.frame.size = hosting.fittingSize
        self.hosting = hosting

        let panel = NSPanel(
            contentRect: NSRect(origin: .zero, size: hosting.fittingSize),
            styleMask: [.nonactivatingPanel, .borderless, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.level = .popUpMenu
        panel.collectionBehavior = [.canJoinAllSpaces, .transient]
        panel.isMovableByWindowBackground = false
        panel.contentView = hosting

        positionPanel(panel)
        panel.orderFrontRegardless()
        self.panel = panel

        clickMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            self?.closePanel()
        }
    }

    /// The Overview and Detailed pages are different heights, so re-fit and
    /// re-anchor the panel whenever its content changes.
    private func resizePanel() {
        guard let panel, panel.isVisible, let hosting else { return }
        hosting.layoutSubtreeIfNeeded()
        let size = hosting.fittingSize
        guard size.height > 0, abs(size.height - panel.frame.height) > 0.5 || abs(size.width - panel.frame.width) > 0.5 else { return }
        hosting.frame.size = size
        panel.setContentSize(size)
        positionPanel(panel)
    }

    private func positionPanel(_ panel: NSPanel) {
        guard let button = statusItem.button, let buttonWindow = button.window else { return }
        let buttonFrame = buttonWindow.frame
        let size = panel.frame.size
        var x = buttonFrame.midX - size.width / 2
        let y = buttonFrame.minY - size.height - 6
        if let screen = buttonWindow.screen {
            x = min(max(screen.visibleFrame.minX + 8, x), screen.visibleFrame.maxX - size.width - 8)
        }
        panel.setFrameOrigin(NSPoint(x: x, y: y))
    }

    private func closePanel() {
        if let clickMonitor {
            NSEvent.removeMonitor(clickMonitor)
            self.clickMonitor = nil
        }
        panel?.orderOut(nil)
        panel = nil
        hosting = nil
    }

    // MARK: - Settings

    func openSettings() {
        closePanel()
        if settingsWindow == nil {
            let hosting = NSHostingController(rootView: SettingsView(state: state))
            let window = NSWindow(contentViewController: hosting)
            window.title = "trackai Settings"
            window.styleMask = [.titled, .closable]
            window.isReleasedWhenClosed = false
            settingsWindow = window
        }
        NSApp.activate(ignoringOtherApps: true)
        settingsWindow?.center()
        settingsWindow?.makeKeyAndOrderFront(nil)
    }
}
