import Foundation

/// Claude Code: local transcripts for token counts, Anthropic's OAuth usage
/// endpoint for the plan windows.
final class ClaudeProvider: UsageProvider {
    let kind: ProviderKind = .claude

    private let scanner = ClaudeTranscriptScanner()
    private var token: String?

    // Anthropic rate-limits the usage endpoint per token, so polling goes
    // through LimitCache's freshness floors and back-off.
    private let cache = LimitCache(persistKey: "claude.apiCache")
    private let lock = NSLock()

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
        let skipPrompt = onMain { Settings.shared.claudeSkipKeychainPrompt }
        if let creds = ClaudeAuth.load(configDir: primary, isDefault: true, skipKeychainPrompt: skipPrompt) {
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

        applied(cache.current(), to: &snap)
        return snap
    }

    func fetchLimits(into snapshot: ProviderSnapshot, force: Bool,
                     completion: @escaping (ProviderSnapshot) -> Void) {
        var snap = snapshot
        lock.lock(); let token = self.token; lock.unlock()

        cache.refresh(token: token, force: force, fetch: ClaudeUsageAPI.fetch) { [weak self] outcome in
            guard let self else { completion(snap); return }
            switch outcome {
            case .notDue:
                break
            case .backingOff:
                if self.cache.current() == nil { snap.limitsError = "rate limited — retrying soon" }
            case .fetched(let fresh):
                snap.limitsError = nil
                self.applied(fresh, to: &snap)
            case .failed(let err):
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
}
