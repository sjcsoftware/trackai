import Foundation

/// GitHub Copilot CLI: local session logs for token counts and AI credits,
/// GitHub's `copilot_internal/user` for the monthly allowance. Copilot's own
/// cached copy of that response is a labelled fallback, never presented as live.
final class CopilotProvider: UsageProvider {
    let kind: ProviderKind = .copilot

    private struct Session {
        var login: CopilotLogin?
        var token: String?
        var stale: ApiUsage?
        var cache: LimitCache?
    }

    private let scanner = CopilotSessionScanner()
    private let lock = NSLock()
    private var session = Session()
    private var caches: [String: LimitCache] = [:]

    private var home: URL { CopilotAuth.home }

    func isInstalled() -> Bool {
        FileManager.default.fileExists(atPath: home.path)
    }

    func scanLocal() -> ProviderSnapshot {
        var snap = ProviderSnapshot(kind: kind)
        let home = self.home

        guard isInstalled() else {
            snap.status = .notInstalled
            lock.lock(); session = Session(); lock.unlock()
            return snap
        }

        let login = CopilotAuth.readLogin(home: home)
        let token = CopilotAuth.findToken(home: home, login: login)
        let stale = CopilotUsageAPI.readCLICache(login: login)
        snap.accountLabel = login?.login
        snap.local = scanner.scan(home: home)
        // A known login with cached limits is still signed in, even when macOS
        // will not hand its Keychain token to this app without a dialog.
        snap.status = token != nil || (login != nil && stale != nil) ? .ok : .missing

        lock.lock()
        let current = Session(login: login, token: token, stale: stale,
                              cache: token == nil ? nil : limitCache(for: login))
        session = current
        lock.unlock()

        apply(current, to: &snap)
        return snap
    }

    func fetchLimits(into snapshot: ProviderSnapshot, force: Bool,
                     completion: @escaping (ProviderSnapshot) -> Void) {
        lock.lock(); let current = session; lock.unlock()
        guard let cache = current.cache else { completion(snapshot); return }

        var snap = snapshot
        let host = current.login?.host ?? CopilotAuth.defaultHost
        cache.refresh(token: current.token, force: force, fetch: { token, done in
            CopilotUsageAPI.fetch(token: token, host: host, completion: done)
        }) { [weak self] _ in
            self?.apply(current, to: &snap)
            completion(snap)
        }
    }

    private func limitCache(for login: CopilotLogin?) -> LimitCache {
        let key = login.map { "copilot.apiCache.\($0.host):\($0.login)" } ?? "copilot.apiCache"
        if let existing = caches[key] { return existing }
        let cache = LimitCache(persistKey: key)
        caches[key] = cache
        return cache
    }

    private func apply(_ s: Session, to snap: inout ProviderSnapshot) {
        let live = s.cache?.current()
        var usage = live
        var error = s.token != nil
            ? s.cache?.lastError
            : s.login != nil ? "Can't read Copilot's Keychain login — run `gh auth login`" : nil

        if let stale = s.stale, live.map({ stale.fetchedAt > $0.fetchedAt }) ?? true {
            usage = stale
            error = "Limits as of Copilot's last start"
        }

        snap.limits = []
        snap.limitsFetchedAt = nil
        snap.limitsError = error
        if let usage {
            snap.planName = usage.plan
            // Token-based (AI credit) plans have only a monthly allowance.
            snap.hasWeekly = !usage.tokenBased
            if usage.limits.isEmpty {
                snap.limitsError = "No usage limits on this Copilot plan"
            } else {
                snap.limits = usage.limits
                snap.limitsFetchedAt = usage.fetchedAt
            }
        } else if error == nil && s.token == nil {
            snap.limitsError = "Not signed in — run `copilot login`"
        }
    }
}
