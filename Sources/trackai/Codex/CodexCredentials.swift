import Foundation

struct CodexAccount {
    let email: String?
    let planType: String?
    let accountID: String?
    /// When the CLI last exchanged its refresh token. The id_token itself lives
    /// for about an hour and Codex renews it on demand, so its `exp` says
    /// nothing about whether the user is still logged in.
    let lastRefresh: Date?
}

/// Reads the login the Codex CLI already established (~/.codex/auth.json).
/// The ChatGPT id_token is a JWT whose claims carry the email and plan, so the
/// user never has to paste anything.
enum CodexAuth {
    /// ~/.codex, or $CODEX_HOME when set.
    static var defaultHome: URL {
        if let env = ProcessInfo.processInfo.environment["CODEX_HOME"], !env.isEmpty {
            return URL(fileURLWithPath: (env as NSString).expandingTildeInPath)
        }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".codex")
    }

    static func home(override: String) -> URL {
        let trimmed = override.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return defaultHome }
        return URL(fileURLWithPath: (trimmed as NSString).expandingTildeInPath)
    }

    static func load(home: URL) -> CodexAccount? {
        guard let data = try? Data(contentsOf: home.appendingPathComponent("auth.json")),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        let tokens = (obj["tokens"] as? [String: Any]) ?? [:]
        let accountID = tokens["account_id"] as? String
        let lastRefresh = ISODate.parse(obj["last_refresh"] as? String)

        guard let idToken = tokens["id_token"] as? String,
              let claims = decodeJWT(idToken) else {
            // API-key mode has no id_token but is still a valid configuration.
            let hasKey = (obj["OPENAI_API_KEY"] as? String).map { !$0.isEmpty } ?? false
            guard hasKey || accountID != nil else { return nil }
            return CodexAccount(email: nil, planType: obj["auth_mode"] as? String,
                                accountID: accountID, lastRefresh: lastRefresh)
        }

        let auth = claims["https://api.openai.com/auth"] as? [String: Any]
        return CodexAccount(email: claims["email"] as? String,
                            planType: auth?["chatgpt_plan_type"] as? String,
                            accountID: (auth?["chatgpt_account_id"] as? String) ?? accountID,
                            lastRefresh: lastRefresh)
    }

    /// Decodes a JWT payload. Signature is irrelevant here — we only read claims
    /// out of a file the user already trusts on their own disk.
    static func decodeJWT(_ token: String) -> [String: Any]? {
        let parts = token.split(separator: ".")
        guard parts.count >= 2 else { return nil }
        var b64 = String(parts[1]).replacingOccurrences(of: "-", with: "+")
                                  .replacingOccurrences(of: "_", with: "/")
        while b64.count % 4 != 0 { b64.append("=") }
        guard let data = Data(base64Encoded: b64),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return obj
    }
}
