import Foundation

/// USD per million tokens.
struct ModelPricing {
    let input: Double
    let output: Double
    let cacheWrite: Double
    let cacheRead: Double
}

enum ClaudePricing {
    static func pricing(for model: String) -> ModelPricing {
        let m = model.lowercased()
        if m.contains("fable") || m.contains("mythos") {
            return ModelPricing(input: 10, output: 50, cacheWrite: 12.5, cacheRead: 1.0)
        }
        if m.contains("opus") {
            // Opus 4.5 and later dropped to $5/$25; older Opus tiers were $15/$75.
            if m.contains("opus-4-5") || m.contains("opus-4-6") || m.contains("opus-4-7")
                || m.contains("opus-4-8") || m.contains("opus-5") {
                return ModelPricing(input: 5, output: 25, cacheWrite: 6.25, cacheRead: 0.5)
            }
            return ModelPricing(input: 15, output: 75, cacheWrite: 18.75, cacheRead: 1.5)
        }
        if m.contains("haiku") {
            if m.contains("haiku-3-5") { return ModelPricing(input: 0.8, output: 4, cacheWrite: 1.0, cacheRead: 0.08) }
            if m.contains("haiku-3") { return ModelPricing(input: 0.25, output: 1.25, cacheWrite: 0.3, cacheRead: 0.03) }
            return ModelPricing(input: 1, output: 5, cacheWrite: 1.25, cacheRead: 0.1)
        }
        // Sonnet and anything unrecognised falls back to Sonnet-tier pricing.
        return ModelPricing(input: 3, output: 15, cacheWrite: 3.75, cacheRead: 0.3)
    }

    static func cost(model: String, input: Int, output: Int, cacheCreate: Int, cacheRead: Int) -> Double {
        let p = pricing(for: model)
        return (Double(input) * p.input
            + Double(output) * p.output
            + Double(cacheCreate) * p.cacheWrite
            + Double(cacheRead) * p.cacheRead) / 1_000_000
    }

    /// "claude-opus-4-5-20251101" -> "Opus 4.5"
    static func prettyModelName(_ model: String) -> String {
        var m = model
        if m.hasPrefix("claude-") { m.removeFirst("claude-".count) }
        var parts = m.split(separator: "-").map(String.init)
        if let last = parts.last, last.count == 8, Int(last) != nil { parts.removeLast() }
        guard let family = parts.first else { return model }
        let version = parts.dropFirst().joined(separator: ".")
        let famName = family.prefix(1).uppercased() + family.dropFirst()
        return version.isEmpty ? famName : "\(famName) \(version)"
    }
}
