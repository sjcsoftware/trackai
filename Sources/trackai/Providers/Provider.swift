import Foundation

// MARK: - Token accounting

/// One billable request's worth of tokens, from any provider's local logs.
struct UsageEntry {
    let key: String          // stable dedup key
    let model: String
    let date: Date
    let input: Int           // uncached input
    let output: Int          // includes reasoning tokens
    let cacheCreate: Int     // cache writes
    let cacheRead: Int       // cached input reads
    let costUSD: Double      // priced by the owning provider
}

struct TokenTotals {
    var input = 0
    var output = 0
    var cacheCreate = 0
    var cacheRead = 0
    var messages = 0
    var cost = 0.0

    var total: Int { input + output + cacheCreate + cacheRead }

    mutating func add(_ e: UsageEntry) {
        input += e.input
        output += e.output
        cacheCreate += e.cacheCreate
        cacheRead += e.cacheRead
        messages += 1
        cost += e.costUSD
    }
}

struct ModelStats: Identifiable {
    let model: String
    var totals = TokenTotals()
    var id: String { model }
}

struct LocalStats {
    var today = TokenTotals()
    var last5h = TokenTotals()
    var last7d = TokenTotals()
    var last30d = TokenTotals()
    var allTime = TokenTotals()
    var perModel: [ModelStats] = []       // all time, busiest first
    var perModel30d: [ModelStats] = []    // last 30 days, busiest first
    var weeklyPeak12 = 0                  // busiest rolling week proxy: peak 7-day block in 90 days
    var scannedAt = Date()

    /// Last 7 days relative to the busiest 7-day block seen (0-100).
    var weeklyRelativePercent: Double {
        guard weeklyPeak12 > 0 else { return 0 }
        return min(100, Double(last7d.total) / Double(weeklyPeak12) * 100)
    }
}

/// Aggregates de-duplicated usage entries into the windows the UI shows.
enum UsageAggregator {
    static func aggregate(_ entries: [UsageEntry]) -> LocalStats {
        var stats = LocalStats()
        let now = Date()
        let cal = Calendar.current
        let startOfToday = cal.startOfDay(for: now)
        let cutoff5h = now.addingTimeInterval(-5 * 3600)
        let cutoff7d = now.addingTimeInterval(-7 * 86400)
        let cutoff30d = now.addingTimeInterval(-30 * 86400)
        let cutoff90d = now.addingTimeInterval(-90 * 86400)

        var perModel: [String: ModelStats] = [:]
        var perModel30d: [String: ModelStats] = [:]
        var dailyTotals: [Date: Int] = [:]

        for e in entries {
            stats.allTime.add(e)
            var m = perModel[e.model] ?? ModelStats(model: e.model)
            m.totals.add(e)
            perModel[e.model] = m

            if e.date >= startOfToday { stats.today.add(e) }
            if e.date >= cutoff5h { stats.last5h.add(e) }
            if e.date >= cutoff7d { stats.last7d.add(e) }
            if e.date >= cutoff30d {
                stats.last30d.add(e)
                var m30 = perModel30d[e.model] ?? ModelStats(model: e.model)
                m30.totals.add(e)
                perModel30d[e.model] = m30
            }
            if e.date >= cutoff90d {
                let day = cal.startOfDay(for: e.date)
                dailyTotals[day, default: 0] += e.input + e.output + e.cacheCreate + e.cacheRead
            }
        }

        stats.perModel = perModel.values.sorted { $0.totals.total > $1.totals.total }
        stats.perModel30d = perModel30d.values.sorted { $0.totals.total > $1.totals.total }
        stats.weeklyPeak12 = peakSevenDayBlock(dailyTotals, calendar: cal)
        stats.scannedAt = now
        return stats
    }

    /// Largest sum over any 7 consecutive calendar days in the sample.
    private static func peakSevenDayBlock(_ daily: [Date: Int], calendar: Calendar) -> Int {
        guard let first = daily.keys.min(), let last = daily.keys.max() else { return 0 }
        var best = 0
        var cursor = first
        while cursor <= last {
            var sum = 0
            for offset in 0..<7 {
                guard let day = calendar.date(byAdding: .day, value: offset, to: cursor) else { continue }
                sum += daily[calendar.startOfDay(for: day)] ?? 0
            }
            best = max(best, sum)
            guard let next = calendar.date(byAdding: .day, value: 1, to: cursor) else { break }
            cursor = next
        }
        return best
    }
}

// MARK: - Plan limits

/// A server-reported quota window (Claude's 5h/weekly limits, Codex's rate
/// limits, Copilot's monthly allowance).
struct LimitInfo: Identifiable, Equatable {
    let kind: String        // stable id, e.g. "session", "weekly_all"
    let group: String       // "session" | "weekly" | "monthly" | other
    let displayName: String
    let percent: Double     // 0-100 used
    let resetsAt: Date?
    var detail: String?     // optional figure such as "525 / 11,000"

    var id: String { kind }
}

/// Everything a provider knows about one configured account.
struct ProviderSnapshot {
    var kind: ProviderKind
    var accountLabel: String?          // usually an email
    var planName: String?              // "max", "plus", …
    var planDetail: String?            // rate limit tier, credits, …
    var status: ConfigStatus = .missing
    var limits: [LimitInfo] = []
    var limitsFetchedAt: Date?
    var limitsError: String?
    var local: LocalStats?
    /// False when the plan has no weekly window at all: no Weekly row, and the
    /// "weekly" metric reads the primary limit.
    var hasWeekly = true

    /// The limit the overview leads with and the "session" metric reads.
    var primaryLimit: LimitInfo? { limits.first { $0.group == kind.primaryLimitGroup } }
    /// Server-reported weekly window, if the provider has one.
    var weeklyLimit: LimitInfo? { limits.first { $0.group == "weekly" } }

    /// Headline "weekly" number: the plan's weekly window when known, else local.
    var weeklyPercent: Double? {
        if let weeklyLimit { return weeklyLimit.percent }
        return local.map(\.weeklyRelativePercent)
    }

    var weeklyIsFromPlan: Bool { weeklyLimit != nil }

    func percent(for metric: UsageMetric) -> Double? {
        switch metric {
        case .weekly where hasWeekly: return weeklyPercent
        case .weekly, .session: return primaryLimit?.percent
        }
    }
}

enum ConfigStatus: Equatable {
    case ok
    case expired
    case missing        // provider installed but no readable login
    case notInstalled   // no config directory at all

    var summary: String {
        switch self {
        case .ok: return "connected"
        case .expired: return "login expired"
        case .missing: return "not logged in"
        case .notInstalled: return "not installed"
        }
    }
}

// MARK: - Provider identity

enum ProviderKind: String, CaseIterable, Identifiable, Codable {
    case claude
    case codex
    case copilot

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .claude: return "Claude Code"
        case .codex: return "Codex"
        case .copilot: return "Copilot"
        }
    }

    /// The terminal command that signs in to this tool.
    var command: String { rawValue }

    /// Codex costs are notional for subscription users, so they are marked "est.".
    var costIsEstimate: Bool { self == .codex }

    /// The limit group the overview leads with and the "session" metric reads.
    var primaryLimitGroup: String { self == .copilot ? "monthly" : "session" }
    var primaryName: String { self == .copilot ? "Monthly" : "Session (5h)" }

    func prettyModelName(_ model: String) -> String {
        switch self {
        case .claude: return ClaudePricing.prettyModelName(model)
        case .codex: return CodexPricing.prettyModelName(model)
        case .copilot:
            return model.hasPrefix("gpt-") ? CodexPricing.prettyModelName(model)
                                           : ClaudePricing.prettyModelName(model)
        }
    }

    /// Order the boxes appear in before the user reorders them.
    static var defaultOrder: [ProviderKind] { [.claude, .codex, .copilot] }

    /// "`claude`, `codex` or `copilot`" for setup and empty-state copy.
    static func commandsHint(_ joiner: String = "or") -> String {
        let names = allCases.map { "`\($0.command)`" }
        return names.dropLast().joined(separator: ", ") + " \(joiner) " + names[names.count - 1]
    }
}

/// A source of usage for one CLI agent. Scanning happens off the main thread.
protocol UsageProvider: AnyObject {
    var kind: ProviderKind { get }
    /// True when the tool looks installed on this machine.
    func isInstalled() -> Bool
    /// Read local logs and credentials. Never touches the network.
    func scanLocal() -> ProviderSnapshot
    /// Optionally refresh server-reported plan limits, merging into `snapshot`.
    func fetchLimits(into snapshot: ProviderSnapshot,
                     force: Bool,
                     completion: @escaping (ProviderSnapshot) -> Void)
}

extension UsageProvider {
    func fetchLimits(into snapshot: ProviderSnapshot,
                     force: Bool,
                     completion: @escaping (ProviderSnapshot) -> Void) {
        completion(snapshot)
    }
}

enum ProviderRegistry {
    static let all: [UsageProvider] = [ClaudeProvider(), CodexProvider(), CopilotProvider()]

    static func provider(for kind: ProviderKind) -> UsageProvider? {
        all.first { $0.kind == kind }
    }
}
