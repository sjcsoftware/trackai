import Foundation

/// USD per million tokens for the OpenAI models Codex runs. ChatGPT-plan users
/// are not billed per token, so these values are an estimate of what the same
/// traffic would cost on the API — shown as "est." in the UI.
enum CodexPricing {
    static func pricing(for model: String) -> ModelPricing {
        let m = model.lowercased()
        if m.contains("mini") {
            return ModelPricing(input: 0.25, output: 2, cacheWrite: 0.25, cacheRead: 0.025)
        }
        if m.contains("nano") {
            return ModelPricing(input: 0.05, output: 0.4, cacheWrite: 0.05, cacheRead: 0.005)
        }
        // gpt-5.x / gpt-6.x codex tiers.
        return ModelPricing(input: 1.25, output: 10, cacheWrite: 1.25, cacheRead: 0.125)
    }

    static func cost(model: String, input: Int, output: Int, cacheCreate: Int, cacheRead: Int) -> Double {
        let p = pricing(for: model)
        return (Double(input) * p.input
            + Double(output) * p.output
            + Double(cacheCreate) * p.cacheWrite
            + Double(cacheRead) * p.cacheRead) / 1_000_000
    }

    /// "gpt-6-astra" -> "GPT-6 Astra", "gpt-5.5" -> "GPT-5.5"
    static func prettyModelName(_ model: String) -> String {
        guard !model.isEmpty else { return "unknown" }
        var parts = model.split(separator: "-").map(String.init)
        var head = parts.removeFirst()
        if head.lowercased() == "gpt" {
            head = "GPT"
            // The version number belongs to the family name: gpt-6 -> GPT-6.
            if let next = parts.first, next.first?.isNumber == true {
                head += "-" + next
                parts.removeFirst()
            }
        } else {
            head = head.prefix(1).uppercased() + head.dropFirst()
        }
        let tail = parts.map { $0.prefix(1).uppercased() + $0.dropFirst() }
        return ([head] + tail).joined(separator: " ")
    }
}
