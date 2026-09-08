import Foundation

enum Formatting {
    static func tokens(_ n: Int) -> String {
        let d = Double(n)
        switch n {
        case ..<1000: return "\(n)"
        case ..<1_000_000: return String(format: "%.1fK", d / 1000)
        case ..<1_000_000_000: return String(format: "%.1fM", d / 1_000_000)
        default: return String(format: "%.2fB", d / 1_000_000_000)
        }
    }

    static func usd(_ v: Double) -> String {
        v < 10 ? String(format: "$%.2f", v) : String(format: "$%.0f", v)
    }

    static func percent(_ v: Double) -> String {
        String(format: "%.0f%%", v)
    }

    static func resetsIn(_ date: Date?) -> String? {
        guard let date else { return nil }
        let secs = date.timeIntervalSinceNow
        guard secs > 0 else { return nil }
        let hours = Int(secs) / 3600
        let mins = (Int(secs) % 3600) / 60
        if hours >= 24 {
            let days = hours / 24
            return "resets in \(days)d \(hours % 24)h"
        }
        if hours > 0 { return "resets in \(hours)h \(mins)m" }
        return "resets in \(mins)m"
    }

    static func agoShort(_ date: Date?) -> String? {
        guard let date else { return nil }
        let secs = -date.timeIntervalSinceNow
        guard secs > 0 else { return "just now" }
        if secs < 90 { return "just now" }
        if secs < 3600 { return "\(Int(secs / 60))m ago" }
        if secs < 86400 { return "\(Int(secs / 3600))h ago" }
        return "\(Int(secs / 86400))d ago"
    }
}

/// Shared ISO-8601 parsing (transcripts mix fractional and whole-second stamps).
enum ISODate {
    private static let withFraction: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let plain: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    static func parse(_ s: String?) -> Date? {
        guard let s else { return nil }
        return withFraction.date(from: s) ?? plain.date(from: s)
    }

    static func string(_ d: Date) -> String { plain.string(from: d) }
}
