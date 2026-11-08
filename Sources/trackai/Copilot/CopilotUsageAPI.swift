import Foundation

/// The read-only quota endpoint Copilot CLI itself calls, authenticated with the
/// token the CLI already stores.
enum CopilotUsageAPI {
    /// A real number: JSON booleans bridge to NSNumber too, and do not count.
    static func number(_ any: Any?) -> Double? {
        guard let n = any as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID() else { return nil }
        let value = n.doubleValue
        return value.isFinite ? value : nil
    }

    static func fetch(token: String, host: String,
                      completion: @escaping (Result<ApiUsage, UsageAPIError>) -> Void) {
        guard let url = URL(string: CopilotAuth.apiBase(host: host) + "/copilot_internal/user") else {
            completion(.failure(.badResponse))
            return
        }
        var req = URLRequest(url: url)
        req.httpMethod = "GET"
        req.timeoutInterval = 20
        req.setValue("token \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.setValue("trackai-macos", forHTTPHeaderField: "User-Agent")

        URLSession.shared.dataTask(with: req) { data, response, error in
            if let error { completion(.failure(.network(error.localizedDescription))); return }
            guard let http = response as? HTTPURLResponse else { completion(.failure(.badResponse)); return }
            guard (200..<300).contains(http.statusCode) else {
                let retryAfter = http.value(forHTTPHeaderField: "Retry-After")
                if http.statusCode == 429 || (http.statusCode == 403 && retryAfter != nil) {
                    completion(.failure(.rateLimited(retryAfter: retryAfter.flatMap(Double.init))))
                } else {
                    completion(.failure(.http(http.statusCode)))
                }
                return
            }
            guard let data,
                  let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
                  let usage = parseUser(obj, fetchedAt: Date()) else {
                completion(.failure(.badResponse))
                return
            }
            completion(.success(usage))
        }.resume()
    }

    /// ApiUsage from a `copilot_internal/user` response; unlimited quotas are skipped.
    static func parseUser(_ obj: [String: Any], fetchedAt: Date) -> ApiUsage? {
        guard let snapshots = obj["quota_snapshots"] as? [String: Any] else { return nil }
        let credits = (obj["token_based_billing"] as? Bool) ?? false
        let reset = resetDate(obj)
        var limits: [LimitInfo] = []

        let quotas = [("premium_interactions", "monthly", credits ? "AI credits" : "Premium requests"),
                      ("chat", "chat", "Chat"),
                      ("completions", "completions", "Completions")]
        for (key, group, name) in quotas {
            guard let quota = snapshots[key] as? [String: Any],
                  (quota["unlimited"] as? Bool) != true else { continue }
            let entitlement = number(quota["entitlement"]) ?? 0
            let remaining = number(quota["percent_remaining"])
            var used = credits && key == "premium_interactions" ? number(quota["credits_used"]) : nil
            if used == nil && entitlement > 0,
               let left = number(quota["quota_remaining"]) ?? number(quota["remaining"]) {
                used = max(0, entitlement - left)
            }

            let percent: Double
            if let remaining {
                percent = max(0, 100 - remaining)
            } else if let used, entitlement > 0 {
                percent = used / entitlement * 100
            } else {
                continue
            }

            var detail: String?
            if let used, entitlement > 0 { detail = "\(grouped(used)) / \(grouped(entitlement))" }
            limits.append(LimitInfo(kind: group, group: group, displayName: name + " (monthly)",
                                    percent: percent, resetsAt: reset, detail: detail))
        }
        return ApiUsage(limits: limits, extraCreditsUSD: nil, fetchedAt: fetchedAt,
                        plan: obj["copilot_plan"] as? String, tokenBased: credits)
    }

    private static func grouped(_ value: Double) -> String {
        let f = NumberFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.numberStyle = .decimal
        f.usesGroupingSeparator = true
        f.groupingSeparator = ","
        f.maximumFractionDigits = 0
        f.roundingMode = .halfEven
        return f.string(from: NSNumber(value: value)) ?? String(format: "%.0f", value)
    }

    private static func resetDate(_ obj: [String: Any]) -> Date? {
        if let date = ISODate.parse(obj["quota_reset_date_utc"] as? String) { return date }
        guard let day = obj["quota_reset_date"] as? String else { return nil }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: day)
    }

    /// The quota response Copilot CLI cached when it last started.
    static func readCLICache(login: CopilotLogin?) -> ApiUsage? {
        let path = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Caches/copilot/copilot-user-cache.json")
        return parseCLICache(CopilotAuth.readJSONC(path), login: login)
    }

    static func parseCLICache(_ cache: [String: Any], login: CopilotLogin?) -> ApiUsage? {
        guard let entries = cache["copilotUserCache"] as? [String: Any] else { return nil }
        var best: ApiUsage?
        for case let entry as [String: Any] in entries.values {
            guard let response = entry["response"] as? [String: Any] else { continue }
            if let login, (response["login"] as? String) != login.login { continue }
            guard let retrieved = ISODate.parse(entry["retrievedAt"] as? String),
                  let usage = parseUser(response, fetchedAt: retrieved) else { continue }
            if best.map({ usage.fetchedAt > $0.fetchedAt }) ?? true { best = usage }
        }
        return best
    }
}
