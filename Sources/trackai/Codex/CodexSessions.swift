import Foundation

/// Rate limits Codex records in its rollout logs after every response.
struct CodexRateLimits {
    var limits: [LimitInfo] = []
    var planType: String?
    var creditBalance: String?
    var hasCredits = false
    var observedAt: Date

    var isEmpty: Bool { limits.isEmpty }
}

/// Scans ~/.codex/sessions/**.jsonl for token usage and the newest rate-limit
/// snapshot. Codex writes both into its rollout log, so no network call is
/// needed — the numbers are exactly what the CLI last saw.
final class CodexSessionScanner {
    private struct FileCacheEntry {
        let mtime: Date
        let size: Int
        let entries: [UsageEntry]
        let rateLimits: CodexRateLimits?
    }

    private var cache: [String: FileCacheEntry] = [:]

    struct ScanResult {
        var stats: LocalStats
        var rateLimits: CodexRateLimits?
    }

    func scan(home: URL) -> ScanResult {
        let sessionsDir = home.appendingPathComponent("sessions")
        let fm = FileManager.default
        var byKey: [String: UsageEntry] = [:]
        var livePaths = Set<String>()
        var newest: CodexRateLimits?

        if let walker = fm.enumerator(at: sessionsDir,
                                      includingPropertiesForKeys: [.contentModificationDateKey, .fileSizeKey],
                                      options: [.skipsHiddenFiles]) {
            for case let url as URL in walker {
                guard url.pathExtension == "jsonl" else { continue }
                let path = url.path
                livePaths.insert(path)
                let attrs = try? url.resourceValues(forKeys: [.contentModificationDateKey, .fileSizeKey])
                let mtime = attrs?.contentModificationDate ?? .distantPast
                let size = attrs?.fileSize ?? 0

                let parsed: FileCacheEntry
                if let cached = cache[path], cached.mtime == mtime, cached.size == size {
                    parsed = cached
                } else {
                    let result = parseFile(url: url)
                    parsed = FileCacheEntry(mtime: mtime, size: size,
                                            entries: result.entries, rateLimits: result.rateLimits)
                    cache[path] = parsed
                }
                for e in parsed.entries { byKey[e.key] = e }
                if let rl = parsed.rateLimits, newest == nil || rl.observedAt > newest!.observedAt {
                    newest = rl
                }
            }
        }
        for key in cache.keys where !livePaths.contains(key) { cache.removeValue(forKey: key) }

        return ScanResult(stats: UsageAggregator.aggregate(Array(byKey.values)), rateLimits: newest)
    }

    // MARK: - Rollout parsing

    private struct FileResult {
        var entries: [UsageEntry] = []
        var rateLimits: CodexRateLimits?
    }

    /// Codex has written usage two ways. Newer CLIs emit one `token_usage_record`
    /// per response; older ones only emit `event_msg`/`token_count` carrying the
    /// delta in `info.last_token_usage`. Prefer the records when a file has them
    /// so the same response is never counted twice.
    private func parseFile(url: URL) -> FileResult {
        guard let data = try? Data(contentsOf: url),
              let text = String(data: data, encoding: .utf8) else { return FileResult() }

        var result = FileResult()
        var records: [UsageEntry] = []
        var events: [UsageEntry] = []
        var model = "unknown"
        var lineNo = 0
        let fileID = url.deletingPathExtension().lastPathComponent

        for line in text.split(separator: "\n", omittingEmptySubsequences: true) {
            lineNo += 1
            guard let lineData = line.data(using: .utf8),
                  let obj = try? JSONSerialization.jsonObject(with: lineData) as? [String: Any],
                  let type = obj["type"] as? String else { continue }
            let payload = (obj["payload"] as? [String: Any]) ?? [:]
            let timestamp = ISODate.parse(obj["timestamp"] as? String)

            switch type {
            case "session_meta", "turn_context":
                if let m = payload["model"] as? String, !m.isEmpty { model = m }

            case "token_usage_record":
                guard let usage = payload["usage"] as? [String: Any], let date = timestamp else { continue }
                let id = (payload["response_id"] as? String) ?? "\(fileID):\(lineNo)"
                if let entry = makeEntry(key: "codex:rec:\(id)", model: model, date: date, usage: usage) {
                    records.append(entry)
                }

            case "event_msg":
                guard (payload["type"] as? String) == "token_count" else { continue }
                if let rl = parseRateLimits(payload["rate_limits"], observedAt: timestamp ?? Date()) {
                    if result.rateLimits == nil || rl.observedAt > result.rateLimits!.observedAt {
                        result.rateLimits = rl
                    }
                }
                guard let info = payload["info"] as? [String: Any],
                      let usage = info["last_token_usage"] as? [String: Any],
                      let date = timestamp else { continue }
                if let entry = makeEntry(key: "codex:evt:\(fileID):\(lineNo)", model: model, date: date, usage: usage) {
                    events.append(entry)
                }

            default:
                continue
            }
        }

        result.entries = records.isEmpty ? events : records
        return result
    }

    /// Codex reports `input_tokens` inclusive of `cached_input_tokens`, and
    /// `output_tokens` inclusive of `reasoning_output_tokens`. Split them out so
    /// cached reads are priced at the cache rate.
    private func makeEntry(key: String, model: String, date: Date, usage: [String: Any]) -> UsageEntry? {
        let rawInput = intValue(usage["input_tokens"])
        let cacheRead = intValue(usage["cached_input_tokens"])
        let cacheWrite = intValue(usage["cache_write_input_tokens"])
        let output = intValue(usage["output_tokens"])
        let input = max(0, rawInput - cacheRead - cacheWrite)
        if input + output + cacheRead + cacheWrite == 0 { return nil }
        return UsageEntry(key: key, model: model, date: date,
                          input: input, output: output,
                          cacheCreate: cacheWrite, cacheRead: cacheRead,
                          costUSD: CodexPricing.cost(model: model, input: input, output: output,
                                                     cacheCreate: cacheWrite, cacheRead: cacheRead))
    }

    private func parseRateLimits(_ any: Any?, observedAt: Date) -> CodexRateLimits? {
        guard let obj = any as? [String: Any] else { return nil }
        var out = CodexRateLimits(observedAt: observedAt)
        out.planType = obj["plan_type"] as? String

        if let credits = obj["credits"] as? [String: Any] {
            out.hasCredits = (credits["has_credits"] as? Bool) ?? false
            out.creditBalance = credits["balance"] as? String
        }

        for (key, kind) in [("primary", "session"), ("secondary", "weekly")] {
            guard let window = obj[key] as? [String: Any] else { continue }
            let percent = doubleValue(window["used_percent"])
            let minutes = intValue(window["window_minutes"])
            let resets = (window["resets_at"] as? Double).map { Date(timeIntervalSince1970: $0) }
                ?? (window["resets_in_seconds"] as? Double).map { Date(timeIntervalSinceNow: $0) }
            out.limits.append(LimitInfo(kind: kind,
                                        group: kind,
                                        displayName: windowName(kind: kind, minutes: minutes),
                                        percent: percent,
                                        resetsAt: resets))
        }
        return out.limits.isEmpty ? nil : out
    }

    /// Codex names its windows only by length, so derive a label from the minutes.
    private func windowName(kind: String, minutes: Int) -> String {
        switch minutes {
        case 0: return kind == "session" ? "Session" : "Weekly"
        case ..<60: return "Limit (\(minutes)m)"
        case ..<1440: return "Session (\(minutes / 60)h)"
        case 10080: return "Weekly"
        default: return "Limit (\(minutes / 1440)d)"
        }
    }

    private func intValue(_ any: Any?) -> Int {
        if let i = any as? Int { return i }
        if let d = any as? Double { return Int(d) }
        return 0
    }

    private func doubleValue(_ any: Any?) -> Double {
        if let d = any as? Double { return d }
        if let i = any as? Int { return Double(i) }
        return 0
    }
}
