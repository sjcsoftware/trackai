import Foundation

/// Scans Claude Code transcript JSONL files and aggregates token usage.
/// Per-file results are cached by (mtime, size) so refreshes stay cheap.
final class ClaudeTranscriptScanner {
    private struct FileCacheEntry {
        let mtime: Date
        let size: Int
        let entries: [UsageEntry]
    }

    private var cache: [String: FileCacheEntry] = [:]

    func scan(configDirs: [URL]) -> LocalStats {
        var byKey: [String: UsageEntry] = [:]
        var livePaths = Set<String>()
        let fm = FileManager.default

        for configDir in configDirs {
            let projectsDir = configDir.appendingPathComponent("projects")
            guard let walker = fm.enumerator(at: projectsDir,
                                             includingPropertiesForKeys: [.contentModificationDateKey, .fileSizeKey],
                                             options: [.skipsHiddenFiles]) else { continue }
            for case let url as URL in walker {
                guard url.pathExtension == "jsonl" else { continue }
                let path = url.path
                livePaths.insert(path)
                let attrs = try? url.resourceValues(forKeys: [.contentModificationDateKey, .fileSizeKey])
                let mtime = attrs?.contentModificationDate ?? .distantPast
                let size = attrs?.fileSize ?? 0

                let entries: [UsageEntry]
                if let cached = cache[path], cached.mtime == mtime, cached.size == size {
                    entries = cached.entries
                } else {
                    entries = parseFile(url: url)
                    cache[path] = FileCacheEntry(mtime: mtime, size: size, entries: entries)
                }
                for e in entries {
                    if let existing = byKey[e.key], existing.date > e.date { continue }
                    byKey[e.key] = e
                }
            }
        }
        for key in cache.keys where !livePaths.contains(key) { cache.removeValue(forKey: key) }

        return UsageAggregator.aggregate(Array(byKey.values))
    }

    private func parseFile(url: URL) -> [UsageEntry] {
        guard let data = try? Data(contentsOf: url),
              let text = String(data: data, encoding: .utf8) else { return [] }
        var byKey: [String: UsageEntry] = [:]
        var lineNo = 0

        for line in text.split(separator: "\n", omittingEmptySubsequences: true) {
            lineNo += 1
            // Only assistant records carry usage; this pre-filter avoids parsing
            // JSON for the ~90% of lines that cannot match.
            guard line.contains("\"type\":\"assistant\"") || line.contains("\"type\": \"assistant\"") else { continue }
            guard let lineData = line.data(using: .utf8),
                  let obj = try? JSONSerialization.jsonObject(with: lineData) as? [String: Any],
                  (obj["type"] as? String) == "assistant",
                  let message = obj["message"] as? [String: Any],
                  let model = message["model"] as? String,
                  model != "<synthetic>",
                  let usage = message["usage"] as? [String: Any] else { continue }

            let input = intValue(usage["input_tokens"])
            let output = intValue(usage["output_tokens"])
            let cc = intValue(usage["cache_creation_input_tokens"])
            let cr = intValue(usage["cache_read_input_tokens"])
            if input + output + cc + cr == 0 { continue }

            guard let date = ISODate.parse(obj["timestamp"] as? String) else { continue }

            let msgID = (message["id"] as? String) ?? "\(url.lastPathComponent):\(lineNo)"
            let reqID = (obj["requestId"] as? String) ?? ""
            let key = "claude:\(msgID):\(reqID)"

            // Streaming can write the same message on several lines; last wins.
            byKey[key] = UsageEntry(key: key, model: model, date: date,
                                    input: input, output: output,
                                    cacheCreate: cc, cacheRead: cr,
                                    costUSD: ClaudePricing.cost(model: model, input: input, output: output,
                                                               cacheCreate: cc, cacheRead: cr))
        }
        return Array(byKey.values)
    }

    private func intValue(_ any: Any?) -> Int {
        if let i = any as? Int { return i }
        if let d = any as? Double { return Int(d) }
        return 0
    }
}
