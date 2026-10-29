import Foundation
import Security

struct ClaudeCredentials {
    let accessToken: String
    let expiresAt: Date?
    let subscriptionType: String?
    let rateLimitTier: String?

    var isExpired: Bool {
        guard let expiresAt else { return false }
        return expiresAt.timeIntervalSinceNow < 60
    }
}

/// Reads the login Claude Code already established, so the user never pastes a token.
enum ClaudeAuth {
    static let keychainService = "Claude Code-credentials"

    /// ~/.claude, or $CLAUDE_CONFIG_DIR when set.
    static var defaultConfigDir: URL {
        if let env = ProcessInfo.processInfo.environment["CLAUDE_CONFIG_DIR"], !env.isEmpty {
            return URL(fileURLWithPath: (env as NSString).expandingTildeInPath)
        }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".claude")
    }

    /// Every config dir we should scan: the default plus user-added ones.
    static func configDirs(extra: [String]) -> [URL] {
        var dirs: [URL] = [defaultConfigDir]
        var seen = Set([defaultConfigDir.standardizedFileURL.path])
        for raw in extra {
            let expanded = (raw as NSString).expandingTildeInPath
            var isDir: ObjCBool = false
            guard FileManager.default.fileExists(atPath: expanded, isDirectory: &isDir), isDir.boolValue else { continue }
            let url = URL(fileURLWithPath: expanded)
            guard seen.insert(url.standardizedFileURL.path).inserted else { continue }
            dirs.append(url)
        }
        return dirs
    }

    /// email/organization from claude.json next to the config dir.
    static func accountInfo(configDir: URL) -> (email: String?, organization: String?) {
        var candidates = [configDir.appendingPathComponent(".claude.json")]
        let home = FileManager.default.homeDirectoryForCurrentUser
        if configDir.standardizedFileURL.path == home.appendingPathComponent(".claude").path {
            candidates.append(home.appendingPathComponent(".claude.json"))
        }
        for url in candidates {
            guard let data = try? Data(contentsOf: url),
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let oauth = obj["oauthAccount"] as? [String: Any] else { continue }
            return (oauth["emailAddress"] as? String, oauth["organizationName"] as? String)
        }
        return (nil, nil)
    }

    /// Credentials file first, then the Keychain (default config dir only).
    static func load(configDir: URL, isDefault: Bool, skipKeychainPrompt: Bool) -> ClaudeCredentials? {
        if let creds = readCredentialsFile(configDir: configDir) { return creds }
        if isDefault { return readKeychain(skipPrompt: skipKeychainPrompt) }
        return nil
    }

    static func readCredentialsFile(configDir: URL) -> ClaudeCredentials? {
        guard let data = try? Data(contentsOf: configDir.appendingPathComponent(".credentials.json")) else { return nil }
        return parse(data: data)
    }

    /// Claude Code saves this item with `/usr/bin/security add-generic-password -U`,
    /// so Apple's `security` tool stays on the item's access list and reads it
    /// without a prompt. trackai itself is ad-hoc signed: each build has a new
    /// code hash, so a direct read asks for the login password again after every
    /// update, however often the user clicks "Always Allow".
    static func readKeychain(skipPrompt: Bool) -> ClaudeCredentials? {
        if skipPrompt { return readKeychainViaCLI() }
        switch copyKeychainItem(interactive: false) {
        case .found(let data): return parse(data: data)
        case .missing: return nil
        case .needsPrompt: break
        }
        KeychainPromptHint.show()
        defer { KeychainPromptHint.hide() }
        if case .found(let data) = copyKeychainItem(interactive: true) { return parse(data: data) }
        // Fall back to the `security` CLI, which can succeed when the direct
        // API is denied.
        return readKeychainViaCLI()
    }

    private enum KeychainRead { case found(Data), missing, needsPrompt }

    private static func copyKeychainItem(interactive: Bool) -> KeychainRead {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        // The file-based login keychain ignores kSecUseAuthenticationUI; this
        // process-wide switch is the only way to ask without showing a dialog.
        if !interactive { SecKeychainSetUserInteractionAllowed(false) }
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if !interactive { SecKeychainSetUserInteractionAllowed(true) }
        if status == errSecSuccess, let data = result as? Data { return .found(data) }
        if status == errSecItemNotFound || interactive { return .missing }
        return .needsPrompt
    }

    private static func readKeychainViaCLI() -> ClaudeCredentials? {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/security")
        proc.arguments = ["find-generic-password", "-s", keychainService, "-w"]
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = Pipe()
        guard (try? proc.run()) != nil else { return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        proc.waitUntilExit()
        guard proc.terminationStatus == 0 else { return nil }
        return parse(data: data)
    }

    private static func parse(data: Data) -> ClaudeCredentials? {
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        let oauth = (obj["claudeAiOauth"] as? [String: Any]) ?? obj
        guard let token = oauth["accessToken"] as? String, !token.isEmpty else { return nil }
        var expires: Date?
        if let ms = oauth["expiresAt"] as? Double { expires = Date(timeIntervalSince1970: ms / 1000) }
        return ClaudeCredentials(accessToken: token,
                                 expiresAt: expires,
                                 subscriptionType: oauth["subscriptionType"] as? String,
                                 rateLimitTier: oauth["rateLimitTier"] as? String)
    }
}
