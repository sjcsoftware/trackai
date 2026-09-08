import Foundation

/// Claude Code: local transcripts for token counts, Anthropic's OAuth usage
/// endpoint for the plan windows.
final class ClaudeProvider: UsageProvider {
    let kind: ProviderKind = .claude

    private let scanner = ClaudeTranscriptScanner()
    private var token: String?

    // Anthropic rate-limits the usage endpoint per token, so polling stays
    // conservative: at most every 5 minutes, last good result persisted across
    // restarts, exponential back-off on HTTP 429.
    private var cached: ApiUsage?
    private var backoffUntil = Date.distantPast
    private var consecutive429 = 0
    private var lastAttempt = Date.distantPast
    private let freshness: TimeInterval = 300
    private let forceFloor: TimeInterval = 60
    private let lock = NSLock()
    private let persistKey = "claude.apiCache"

    func isInstalled() -> Bool {
        FileManager.default.fileExists(atPath: ClaudeAuth.defaultConfigDir.path)
    }

    func scanLocal() -> ProviderSnapshot {
        var snap = ProviderSnapshot(kind: kind)
        let extra = onMain { Settings.shared.claudeExtraConfigDirs }
        let dirs = ClaudeAuth.configDirs(extra: extra)
        let primary = dirs[0]

        guard isInstalled() || dirs.count > 1 else {
            snap.status = .notInstalled
            return snap
        }

        let info = ClaudeAuth.accountInfo(configDir: primary)
        snap.accountLabel = info.email
        if let creds = ClaudeAuth.load(configDir: primary, isDefault: true) {
            snap.status = creds.isExpired ? .expired : .ok
            snap.planName = creds.subscriptionType
            // "default_claude_ai" is noise; only surface a distinctive tier.
            snap.planDetail = creds.rateLimitTier.flatMap { $0.hasPrefix("default") ? nil : $0 }
            lock.lock(); token = creds.isExpired ? nil : creds.accessToken; lock.unlock()
        } else {
            snap.status = .missing
            lock.lock(); token = nil; lock.unlock()
        }

        snap.local = scanner.scan(configDirs: dirs)

        lock.lock()
        loadPersistedIfNeeded()
        let usage = cached
        lock.unlock()
        applied(usage, to: &snap)
        return snap
    }

    func fetchLimits(into snapshot: ProviderSnapshot, force: Bool,
                     completion: @escaping (ProviderSnapshot) -> Void) {
        var snap = snapshot
        let now = Date()

        lock.lock()
        let token = self.token
        let usage = cached
        let inBackoff = backoffUntil > now
        let isFresh = usage.map { now.timeIntervalSince($0.fetchedAt) < freshness } ?? false
        // Even a manual refresh will not hammer the endpoint more than once a minute.
        let forceAllowed = now.timeIntervalSince(lastAttempt) > forceFloor
        let wantsFetch = force ? forceAllowed : !isFresh
        if wantsFetch && !inBackoff && token != nil { lastAttempt = now }
        lock.unlock()

        if inBackoff && usage == nil { snap.limitsError = "rate limited — retrying soon" }

        guard let token, !inBackoff, wantsFetch else { completion(snap); return }

        ClaudeUsageAPI.fetch(token: token) { [weak self] result in
            guard let self else { completion(snap); return }
            switch result {
            case .success(let fresh):
                self.lock.lock()
                self.cached = fresh
                self.backoffUntil = .distantPast
                self.consecutive429 = 0
                self.persist(fresh)
                self.lock.unlock()
                snap.limitsError = nil
                self.applied(fresh, to: &snap)
            case .failure(let err):
                if case .rateLimited(let retryAfter) = err {
                    self.lock.lock()
                    self.consecutive429 += 1
                    // 5 → 10 → 20 → 40 → 60 min, or Retry-After when it is longer.
                    var delay = min(3600, 300 * pow(2, Double(self.consecutive429 - 1)))
                    if let retryAfter, retryAfter > delay { delay = retryAfter }
                    self.backoffUntil = Date().addingTimeInterval(delay)
                    self.lock.unlock()
                }
                if snap.limits.isEmpty { snap.limitsError = err.description }
            }
            completion(snap)
        }
    }

    private func applied(_ usage: ApiUsage?, to snap: inout ProviderSnapshot) {
        guard let usage else { return }
        snap.limits = usage.limits
        snap.limitsFetchedAt = usage.fetchedAt
        if let credits = usage.extraCreditsUSD {
            snap.planDetail = [snap.planDetail, "extra credits \(Formatting.usd(credits))"]
                .compactMap { $0 }.joined(separator: " · ")
        }
    }

    private func loadPersistedIfNeeded() {
        guard cached == nil,
              let data = UserDefaults.standard.data(forKey: persistKey),
              let dict = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let usage = ApiUsage.fromDict(dict) else { return }
        cached = usage
    }

    private func persist(_ usage: ApiUsage) {
        if let data = try? JSONSerialization.data(withJSONObject: usage.toDict()) {
            UserDefaults.standard.set(data, forKey: persistKey)
        }
    }
}
