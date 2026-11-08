import Foundation
import Security

struct CopilotLogin: Equatable {
    let host: String
    let login: String
}

/// Reads the login Copilot CLI already established, so the user never pastes a
/// token. Nothing is ever written back.
enum CopilotAuth {
    static let keychainService = "copilot-cli"
    static let defaultHost = "https://github.com"

    /// ~/.copilot, or $COPILOT_HOME when set.
    static var home: URL {
        if let env = ProcessInfo.processInfo.environment["COPILOT_HOME"], !env.isEmpty {
            return URL(fileURLWithPath: (env as NSString).expandingTildeInPath)
        }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".copilot")
    }

    /// Copilot's JSON files start with `//` comment lines.
    static func readJSONC(_ url: URL) -> [String: Any] {
        guard let data = try? Data(contentsOf: url) else { return [:] }
        let body = String(decoding: data, as: UTF8.self)
            .split(separator: "\n", omittingEmptySubsequences: false)
            .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
            .joined(separator: "\n")
        return (try? JSONSerialization.jsonObject(with: Data(body.utf8))) as? [String: Any] ?? [:]
    }

    /// The account Copilot CLI last signed in with.
    static func readLogin(home: URL) -> CopilotLogin? {
        let config = readJSONC(home.appendingPathComponent("config.json"))
        guard let user = (config["lastLoggedInUser"] ?? config["last_logged_in_user"]) as? [String: Any],
              let login = user["login"] as? String, !login.isEmpty else { return nil }
        var host = (user["host"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? defaultHost
        while host.hasSuffix("/") { host.removeLast() }
        return CopilotLogin(host: host, login: login)
    }

    static func apiBase(host: String) -> String {
        let name = hostname(host)
        if name == "github.com" { return "https://api.github.com" }
        if name.hasSuffix(".ghe.com") { return "https://api.\(name)" }
        return "https://\(name)/api/v3"
    }

    private static func hostname(_ host: String) -> String {
        var name = host
        for scheme in ["https://", "http://"] where name.hasPrefix(scheme) {
            name.removeFirst(scheme.count)
        }
        return name.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }

    /// Copilot CLI's own token, in the CLI's order. Read-only, never pasted.
    static func findToken(home: URL, login: CopilotLogin?) -> String? {
        let env = ProcessInfo.processInfo.environment["COPILOT_GITHUB_TOKEN"]?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !env.isEmpty { return env }

        if let login {
            let account = "\(login.host):\(login.login)"
            // Without a keyring the CLI keeps {"<host>:<login>": token} in config.json.
            for value in readJSONC(home.appendingPathComponent("config.json")).values {
                if let tokens = value as? [String: Any], let token = tokens[account] as? String, !token.isEmpty {
                    return token
                }
            }
            if let token = readKeychain(account: account) { return token }
        }
        return ghToken(host: login?.host ?? defaultHost)
    }

    /// The item's access list names only Copilot's own binaries, so neither this
    /// ad-hoc-signed app nor `/usr/bin/security` is trusted and any ordinary read
    /// raises a password dialog on every poll. Interaction stays off: this
    /// succeeds only where no dialog would be needed.
    private static func readKeychain(account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        SecKeychainSetUserInteractionAllowed(false)
        defer { SecKeychainSetUserInteractionAllowed(true) }
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        let token = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        return token.isEmpty ? nil : token
    }

    private static func ghToken(host: String) -> String? {
        guard let gh = findGH() else { return nil }
        let proc = Process()
        proc.executableURL = gh
        proc.arguments = ["auth", "token", "--hostname", hostname(host)]
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = FileHandle.nullDevice
        proc.standardInput = FileHandle.nullDevice
        guard (try? proc.run()) != nil else { return nil }

        let watchdog = DispatchWorkItem { if proc.isRunning { proc.terminate() } }
        DispatchQueue.global().asyncAfter(deadline: .now() + 10, execute: watchdog)
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        proc.waitUntilExit()
        watchdog.cancel()

        guard proc.terminationReason == .exit, proc.terminationStatus == 0 else { return nil }
        let token = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        return token.isEmpty ? nil : token
    }

    /// An app started from the menu bar or at login has only the system PATH,
    /// which leaves out the usual Homebrew and user install locations.
    private static func findGH() -> URL? {
        let fm = FileManager.default
        let inherited = (ProcessInfo.processInfo.environment["PATH"] ?? "").split(separator: ":").map(String.init)
        let extra = ["/opt/homebrew/bin", "/usr/local/bin",
                     fm.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin").path]
        for dir in inherited + extra {
            let candidate = URL(fileURLWithPath: dir).appendingPathComponent("gh")
            if fm.isExecutableFile(atPath: candidate.path) { return candidate }
        }
        return nil
    }
}
