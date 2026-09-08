import Foundation

/// Codex: everything comes from ~/.codex. The rollout logs carry both the token
/// counts and the rate-limit snapshot the CLI last received, so there is no
/// network call and nothing to rate-limit.
final class CodexProvider: UsageProvider {
    let kind: ProviderKind = .codex

    private let scanner = CodexSessionScanner()

    private var home: URL { CodexAuth.home(override: onMain { Settings.shared.codexHome }) }

    func isInstalled() -> Bool {
        FileManager.default.fileExists(atPath: home.path)
    }

    func scanLocal() -> ProviderSnapshot {
        var snap = ProviderSnapshot(kind: kind)
        let home = self.home

        guard isInstalled() else {
            snap.status = .notInstalled
            return snap
        }

        if let account = CodexAuth.load(home: home) {
            snap.status = .ok
            snap.accountLabel = account.email
            snap.planName = account.planType
        } else {
            snap.status = .missing
        }

        let result = scanner.scan(home: home)
        snap.local = result.stats

        if let rl = result.rateLimits {
            snap.limits = rl.limits
            snap.limitsFetchedAt = rl.observedAt
            if let plan = rl.planType { snap.planName = plan }
            if rl.hasCredits, let balance = rl.creditBalance {
                snap.planDetail = "credits \(balance)"
            }
            // The snapshot only advances when Codex runs; say so once it is stale.
            if Date().timeIntervalSince(rl.observedAt) > 6 * 3600 {
                snap.limitsError = "limits as of the last Codex run"
            }
        } else if snap.status == .ok {
            snap.limitsError = "no rate-limit data yet — run `codex` once"
        }
        return snap
    }
}
