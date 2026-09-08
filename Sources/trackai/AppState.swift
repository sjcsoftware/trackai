import Foundation
import Combine

final class AppState: ObservableObject {
    @Published var snapshots: [ProviderKind: ProviderSnapshot] = [:]
    @Published var lastRefresh: Date?
    @Published var isRefreshing = false
    @Published var page: PanelPage = .overview

    enum PanelPage: String { case overview, detailed }

    private let queue = DispatchQueue(label: "trackai.refresh", qos: .utility)
    private var timer: Timer?

    func start() {
        refresh()
        rescheduleTimer()
    }

    func rescheduleTimer() {
        timer?.invalidate()
        let interval = max(30, Settings.shared.refreshInterval)
        timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { [weak self] _ in
            self?.refresh()
        }
    }

    /// Snapshots for the providers the user wants shown, in their order.
    var visibleSnapshots: [ProviderSnapshot] {
        Settings.shared.visibleProviders.compactMap { snapshots[$0] }
    }

    /// The percentage the menu bar icon reports, per the configured source.
    var menuBarPercent: Double? {
        let settings = Settings.shared
        let metric = settings.menuBarMetric
        switch settings.menuBarMode {
        case .single:
            return snapshots[settings.menuBarSingleProvider]?.percent(for: metric)
        case .average, .highest:
            let values = settings.visibleProviders
                .filter { settings.menuBarProviders.contains($0) }
                .compactMap { snapshots[$0]?.percent(for: metric) }
            guard !values.isEmpty else { return nil }
            if settings.menuBarMode == .highest { return values.max() }
            return values.reduce(0, +) / Double(values.count)
        }
    }

    /// The provider glyph to draw in the menu bar, when a single one drives it.
    var menuBarProviderGlyph: ProviderKind? {
        let settings = Settings.shared
        if settings.menuBarMode == .single { return settings.menuBarSingleProvider }
        let sources = settings.visibleProviders.filter { settings.menuBarProviders.contains($0) }
        return sources.count == 1 ? sources[0] : nil
    }

    func refresh(force: Bool = false, completion: (() -> Void)? = nil) {
        DispatchQueue.main.async { self.isRefreshing = true }
        queue.async { [weak self] in
            guard let self else { return }
            let group = DispatchGroup()
            let lock = NSLock()
            var results: [ProviderKind: ProviderSnapshot] = [:]

            for provider in ProviderRegistry.all {
                let local = provider.scanLocal()
                lock.lock(); results[provider.kind] = local; lock.unlock()

                group.enter()
                provider.fetchLimits(into: local, force: force) { updated in
                    lock.lock(); results[provider.kind] = updated; lock.unlock()
                    group.leave()
                }
            }

            // Bounded wait so a hung network call cannot wedge the refresh loop.
            _ = group.wait(timeout: .now() + 30)
            lock.lock(); let final = results; lock.unlock()

            DispatchQueue.main.async {
                self.snapshots = final
                self.lastRefresh = Date()
                self.isRefreshing = false
                completion?()
            }
        }
    }
}
