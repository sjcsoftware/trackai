import Foundation

/// Scans $COPILOT_HOME/session-state/<id>/events.jsonl. Copilot CLI logs every
/// model call as a `session.usage_record` event, with exact per-type token
/// counts and the AI credits it cost.
final class CopilotSessionScanner {
    /// GitHub bills Copilot in AI credits; 1 AI credit = $0.01.
    private static let usdPerAICredit = 0.01

    private struct FileCacheEntry {
        let mtime: Date
        let size: Int
        let entries: [UsageEntry]
    }

    private var cache: [String: FileCacheEntry] = [:]

    func scan(home: URL) -> LocalStats {
        let fm = FileManager.default
        let root = home.appendingPathComponent("session-state")
        var byKey: [String: UsageEntry] = [:]
        var livePaths = Set<String>()

        for dir in (try? fm.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? [] {
            let url = dir.appendingPathComponent("events.jsonl")
            guard let attrs = try? url.resourceValues(forKeys: [.contentModificationDateKey, .fileSizeKey]) else { continue }
            let path = url.path
            let mtime = attrs.contentModificationDate ?? .distantPast
            let size = attrs.fileSize ?? 0
            livePaths.insert(path)

            let parsed: FileCacheEntry
            if let cached = cache[path], cached.mtime == mtime, cached.size == size {
                parsed = cached
            } else {
                parsed = FileCacheEntry(mtime: mtime, size: size, entries: parseFile(url: url))
                cache[path] = parsed
            }
            for entry in parsed.entries {
                if let existing = byKey[entry.key], entry.date < existing.date { continue }
                byKey[entry.key] = entry
            }
        }
        for key in cache.keys where !livePaths.contains(key) { cache.removeValue(forKey: key) }

        return UsageAggregator.aggregate(Array(byKey.values))
    }

    private func parseFile(url: URL) -> [UsageEntry] {
        guard let data = try? Data(contentsOf: url) else { return [] }
        let sessionID = url.deletingLastPathComponent().lastPathComponent
        var records: [String: UsageEntry] = [:]
        var lineNo = 0

        for line in String(decoding: data, as: UTF8.self).split(separator: "\n", omittingEmptySubsequences: false) {
            lineNo += 1
            guard line.contains("\"session.usage_record\""),
                  let obj = (try? JSONSerialization.jsonObject(with: Data(line.utf8))) as? [String: Any],
                  (obj["type"] as? String) == "session.usage_record",
                  let usage = (obj["data"] as? [String: Any])?["usage"] as? [String: Any],
                  let date = ISODate.parse(obj["timestamp"] as? String) else { continue }

            let model = nonEmpty(usage["model"]) ?? nonEmpty(usage["responseModel"]) ?? "unknown"
            let tokens = tokenCounts(usage)
            guard tokens.input + tokens.output + tokens.cacheWrite + tokens.cacheRead > 0 else { continue }

            let accounting = usage["accounting"] as? [String: Any]
            let ident = identifier(accounting?["usageId"]) ?? identifier(usage["apiCallId"])
                ?? identifier(obj["id"]) ?? "\(sessionID):\(lineNo)"
            let key = "copilot:\(ident)"
            records[key] = UsageEntry(key: key, model: model, date: date,
                                      input: tokens.input, output: tokens.output,
                                      cacheCreate: tokens.cacheWrite, cacheRead: tokens.cacheRead,
                                      costUSD: credits(usage) * Self.usdPerAICredit)
        }
        return Array(records.values)
    }

    private func tokenCounts(_ usage: [String: Any]) -> (input: Int, output: Int, cacheWrite: Int, cacheRead: Int) {
        let copilotUsage = usage["copilotUsage"] as? [String: Any]
        if let details = copilotUsage?["tokenDetails"] as? [Any], !details.isEmpty {
            var counts: [String: Int] = [:]
            for case let item as [String: Any] in details {
                guard let type = item["tokenType"] as? String else { continue }
                counts[type, default: 0] += int(item["tokenCount"])
            }
            return (counts["input"] ?? 0, counts["output"] ?? 0, counts["cache_write"] ?? 0, counts["cache_read"] ?? 0)
        }
        // inputTokens includes cached reads and writes.
        let read = int(usage["cacheReadTokens"])
        let write = int(usage["cacheWriteTokens"])
        return (max(0, int(usage["inputTokens"]) - read - write), int(usage["outputTokens"]), write, read)
    }

    private func credits(_ usage: [String: Any]) -> Double {
        guard let copilotUsage = usage["copilotUsage"] as? [String: Any] else { return 0 }
        var nano = CopilotUsageAPI.number(copilotUsage["totalNanoAiu"])
        if nano == nil {
            var sum = 0.0
            for case let item as [String: Any] in (copilotUsage["tokenDetails"] as? [Any]) ?? [] {
                guard let batch = CopilotUsageAPI.number(item["batchSize"]), batch != 0 else { continue }
                sum += Double(int(item["tokenCount"])) * (CopilotUsageAPI.number(item["costPerBatch"]) ?? 0) / batch
            }
            nano = sum
        }
        return max(0, nano ?? 0) / 1e9
    }

    private func int(_ any: Any?) -> Int {
        guard let value = CopilotUsageAPI.number(any), abs(value) < 9e18 else { return 0 }
        return max(0, Int(value))
    }

    private func nonEmpty(_ any: Any?) -> String? {
        guard let s = any as? String, !s.isEmpty else { return nil }
        return s
    }

    private func identifier(_ any: Any?) -> String? {
        if let s = nonEmpty(any) { return s }
        guard let value = CopilotUsageAPI.number(any), value != 0 else { return nil }
        return (any as? NSNumber)?.stringValue
    }
}
