import Foundation

/// Cached result of Anthropic's OAuth usage endpoint.
struct ApiUsage {
    let limits: [LimitInfo]
    let extraCreditsUSD: Double?
    let fetchedAt: Date

    // Persisted so restarts keep the last good data rather than immediately
    // re-hitting an endpoint that rate-limits aggressively.
    func toDict() -> [String: Any] {
        var d: [String: Any] = [
            "fetchedAt": fetchedAt.timeIntervalSince1970,
            "limits": limits.map { l -> [String: Any] in
                var e: [String: Any] = ["kind": l.kind, "group": l.group,
                                        "displayName": l.displayName, "percent": l.percent]
                if let r = l.resetsAt { e["resetsAt"] = r.timeIntervalSince1970 }
                return e
            },
        ]
        if let extraCreditsUSD { d["extraCredits"] = extraCreditsUSD }
        return d
    }

    static func fromDict(_ d: [String: Any]) -> ApiUsage? {
        guard let ts = d["fetchedAt"] as? Double,
              let raw = d["limits"] as? [[String: Any]] else { return nil }
        let limits = raw.compactMap { e -> LimitInfo? in
            guard let kind = e["kind"] as? String else { return nil }
            return LimitInfo(kind: kind,
                             group: (e["group"] as? String) ?? kind,
                             displayName: (e["displayName"] as? String) ?? kind,
                             percent: (e["percent"] as? Double) ?? 0,
                             resetsAt: (e["resetsAt"] as? Double).map { Date(timeIntervalSince1970: $0) })
        }
        return ApiUsage(limits: limits,
                        extraCreditsUSD: d["extraCredits"] as? Double,
                        fetchedAt: Date(timeIntervalSince1970: ts))
    }
}

enum UsageAPIError: Error, CustomStringConvertible {
    case http(Int)
    case rateLimited(retryAfter: Double?)
    case network(String)
    case badResponse

    var description: String {
        switch self {
        case .http(let code): return code == 401 ? "unauthorized (token expired?)" : "HTTP \(code)"
        case .rateLimited: return "rate limited — retrying soon"
        case .network(let msg): return msg
        case .badResponse: return "unexpected response"
        }
    }
}

enum ClaudeUsageAPI {
    static let endpoint = URL(string: "https://api.anthropic.com/api/oauth/usage")!

    static func fetch(token: String, completion: @escaping (Result<ApiUsage, UsageAPIError>) -> Void) {
        var req = URLRequest(url: endpoint)
        req.httpMethod = "GET"
        req.timeoutInterval = 20
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("oauth-2025-04-20", forHTTPHeaderField: "anthropic-beta")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")

        URLSession.shared.dataTask(with: req) { data, response, error in
            if let error { completion(.failure(.network(error.localizedDescription))); return }
            guard let http = response as? HTTPURLResponse else { completion(.failure(.badResponse)); return }
            guard (200..<300).contains(http.statusCode) else {
                if http.statusCode == 429 {
                    completion(.failure(.rateLimited(retryAfter: http.value(forHTTPHeaderField: "Retry-After").flatMap(Double.init))))
                } else {
                    completion(.failure(.http(http.statusCode)))
                }
                return
            }
            guard let data, let usage = parse(data: data) else { completion(.failure(.badResponse)); return }
            completion(.success(usage))
        }.resume()
    }

    static func parse(data: Data) -> ApiUsage? {
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        var limits: [LimitInfo] = []

        if let arr = obj["limits"] as? [[String: Any]] {
            for entry in arr {
                guard let kind = entry["kind"] as? String else { continue }
                let percent = (entry["percent"] as? Double) ?? Double(entry["percent"] as? Int ?? 0)
                limits.append(LimitInfo(kind: kind,
                                        group: normalizedGroup(kind: kind, raw: entry["group"] as? String),
                                        displayName: displayName(for: kind),
                                        percent: percent,
                                        resetsAt: ISODate.parse(entry["resets_at"] as? String)))
            }
        }

        // Fallback for schema drift: derive from the five_hour / seven_day objects.
        if limits.isEmpty {
            let mapping = [("five_hour", "session"), ("seven_day", "weekly_all"),
                           ("seven_day_opus", "weekly_opus"), ("seven_day_sonnet", "weekly_sonnet")]
            for (key, kind) in mapping {
                guard let entry = obj[key] as? [String: Any] else { continue }
                let percent = (entry["utilization"] as? Double) ?? Double(entry["utilization"] as? Int ?? 0)
                limits.append(LimitInfo(kind: kind,
                                        group: normalizedGroup(kind: kind, raw: nil),
                                        displayName: displayName(for: kind),
                                        percent: percent,
                                        resetsAt: ISODate.parse(entry["resets_at"] as? String)))
            }
        }

        var extraCredits: Double?
        if let extra = obj["extra_usage"] as? [String: Any],
           let used = extra["used_credits"] as? Double, used > 0 {
            let places = (extra["decimal_places"] as? Int) ?? 2
            extraCredits = used / pow(10, Double(places))
        }

        return ApiUsage(limits: limits, extraCreditsUSD: extraCredits, fetchedAt: Date())
    }

    /// Collapse Anthropic's kinds into the "session"/"weekly" groups the UI uses.
    private static func normalizedGroup(kind: String, raw: String?) -> String {
        if kind == "session" || kind.hasPrefix("five_hour") { return "session" }
        if kind == "weekly_all" || kind == "seven_day" { return "weekly" }
        if kind.hasPrefix("weekly") || kind.hasPrefix("seven_day") { return "weekly_model" }
        return raw ?? kind
    }

    private static func displayName(for kind: String) -> String {
        switch kind {
        case "session", "five_hour": return "Session (5h)"
        case "weekly_all", "seven_day": return "Weekly (all models)"
        case "weekly_opus", "seven_day_opus": return "Weekly (Opus)"
        case "weekly_sonnet", "seven_day_sonnet": return "Weekly (Sonnet)"
        default:
            return kind.split(separator: "_").map { $0.prefix(1).uppercased() + $0.dropFirst() }.joined(separator: " ")
        }
    }
}
