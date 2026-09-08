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
    var dailyPeak30 = 0                   // busiest single day (tokens) in last 30 days
    var weeklyPeak12 = 0                  // busiest rolling week proxy: peak 7-day block in 90 days
    var activeDays30 = 0                  // days with any usage in the last 30
    var scannedAt = Date()

    /// Comparing today against a peak only means something once there are a few
    /// days to compare with; a single day of history always reads as 100%.
    var hasDailyBaseline: Bool { activeDays30 >= 3 && dailyPeak30 > 0 }

    /// Today's tokens relative to the busiest day of the last 30 days (0-100).
    var dailyRelativePercent: Double {
        guard dailyPeak30 > 0 else { return 0 }
        return min(100, Double(today.total) / Double(dailyPeak30) * 100)
    }

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
        let within30 = dailyTotals.filter { $0.key >= cal.startOfDay(for: cutoff30d) }
        stats.dailyPeak30 = within30.values.max() ?? 0
        stats.activeDays30 = within30.filter { $0.value > 0 }.count
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

/// A server-reported quota window (Claude's 5h/weekly limits, Codex's rate limits).
struct LimitInfo: Identifiable, Equatable {
    let kind: String        // stable id, e.g. "session", "weekly_all"
    let group: String       // "session" | "weekly" | other
    let displayName: String
    let percent: Double     // 0-100 used
    let resetsAt: Date?

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

    /// Server-reported session (5h) window, if the provider has one.
    var sessionLimit: LimitInfo? { limits.first { $0.group == "session" } }
    /// Server-reported weekly window, if the provider has one.
    var weeklyLimit: LimitInfo? { limits.first { $0.group == "weekly" } }

    /// Headline "daily" number: today's tokens against the busiest recent day.
    /// Nil until there is enough history for that comparison to mean anything,
    /// so a first-day provider cannot drag a menu bar average to 100%.
    var dailyPercent: Double? {
        guard let local, local.hasDailyBaseline else { return nil }
        return local.dailyRelativePercent
    }

    /// Headline "weekly" number: the plan's weekly window when known, else local.
    var weeklyPercent: Double? {
        if let weeklyLimit { return weeklyLimit.percent }
        return local.map(\.weeklyRelativePercent)
    }

    var weeklyIsFromPlan: Bool { weeklyLimit != nil }

    func percent(for metric: UsageMetric) -> Double? {
        switch metric {
        case .daily: return dailyPercent
        case .weekly: return weeklyPercent
        case .session: return sessionLimit?.percent
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

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .claude: return "Claude Code"
        case .codex: return "Codex"
        }
    }

    /// Order the boxes appear in before the user reorders them.
    static var defaultOrder: [ProviderKind] { [.claude, .codex] }
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
    static let all: [UsageProvider] = [ClaudeProvider(), CodexProvider()]

    static func provider(for kind: ProviderKind) -> UsageProvider? {
        all.first { $0.kind == kind }
    }
}
