import AppKit
import Foundation
import SwiftUI

let arguments = Array(CommandLine.arguments.dropFirst())

func jsonString(_ obj: Any) -> String {
    guard let data = try? JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys]),
          let s = String(data: data, encoding: .utf8) else { return "{}" }
    return s
}

func totalsDict(_ t: TokenTotals) -> [String: Any] {
    ["input": t.input, "output": t.output, "cacheCreate": t.cacheCreate, "cacheRead": t.cacheRead,
     "messages": t.messages, "total": t.total, "estimatedCostUSD": (t.cost * 100).rounded() / 100]
}

/// Collect every provider's snapshot synchronously, for the CLI modes.
func gatherCLI() -> [[String: Any]] {
    var out: [[String: Any]] = []
    for provider in ProviderRegistry.all {
        let local = provider.scanLocal()
        var snapshot = local
        let sem = DispatchSemaphore(value: 0)
        provider.fetchLimits(into: local, force: true) { updated in
            snapshot = updated
            sem.signal()
        }
        _ = sem.wait(timeout: .now() + 25)

        var entry: [String: Any] = [
            "provider": snapshot.kind.rawValue,
            "name": snapshot.kind.displayName,
            "status": snapshot.status.summary,
            "account": snapshot.accountLabel ?? NSNull(),
            "plan": snapshot.planName ?? NSNull(),
        ]
        entry["limits"] = snapshot.limits.map { l -> [String: Any] in
            var d: [String: Any] = ["kind": l.kind, "group": l.group,
                                    "name": l.displayName, "percent": l.percent]
            if let r = l.resetsAt { d["resetsAt"] = ISODate.string(r) }
            return d
        }
        if let err = snapshot.limitsError { entry["limitsNote"] = err }
        if let s = snapshot.local {
            entry["local"] = [
                "today": totalsDict(s.today),
                "last5h": totalsDict(s.last5h),
                "last7d": totalsDict(s.last7d),
                "last30d": totalsDict(s.last30d),
                "allTime": totalsDict(s.allTime),
                "dailyPercent": (s.dailyRelativePercent * 10).rounded() / 10,
                "byModel": s.perModel.map { ["model": $0.model, "stats": totalsDict($0.totals)] },
            ]
        }
        out.append(entry)
    }
    return out
}

if arguments.contains("--version") {
    print("trackai \(AppInfo.version)")
    exit(0)
}

if arguments.contains("--stats") {
    print(jsonString(["providers": gatherCLI()]))
    exit(0)
}

if arguments.contains("--setup") {
    print("trackai setup")
    print("=============")
    let results = gatherCLI()
    var connected = 0

    for entry in results {
        let name = entry["name"] as? String ?? "?"
        let status = entry["status"] as? String ?? "?"
        print("")
        print("• \(name): \(status)")
        if let account = entry["account"] as? String { print("  Account: \(account)") }
        if let plan = entry["plan"] as? String { print("  Plan:    \(plan)") }
        if let limits = entry["limits"] as? [[String: Any]], !limits.isEmpty {
            for l in limits {
                print(String(format: "  %@: %.0f%% used",
                             l["name"] as? String ?? "?", l["percent"] as? Double ?? 0))
            }
        } else if let note = entry["limitsNote"] as? String {
            print("  Limits:  \(note)")
        }
        if let local = entry["local"] as? [String: Any],
           let today = local["today"] as? [String: Any],
           let total = today["total"] as? Int {
            print("  Today:   \(Formatting.tokens(total)) tokens")
        }
        if status == "connected" { connected += 1 }
    }

    print("")
    if connected > 0 {
        print("✓ trackai is reading \(connected) provider\(connected == 1 ? "" : "s") from your existing logins.")
        print("  The menu bar icon will appear now (or run `trackai start`).")
        exit(0)
    }
    print("No usable login found yet.")
    print("Open a terminal and run `claude` and/or `codex`, log in, then run `trackai setup` again.")
    exit(1)
}

if arguments.contains("--help") || arguments.contains("-h") {
    print("""
    trackai — Claude Code and Codex usage in your Mac menu bar.

      trackai            launch the menu bar app
      trackai --setup    check which providers are connected
      trackai --stats    print everything as JSON
      trackai --version  print the version
    """)
    exit(0)
}

/// Renders the panel to a PNG without showing a window. Used for the README
/// screenshots and for checking layout changes without clicking through the app.
if let idx = arguments.firstIndex(of: "--render"), idx + 1 < arguments.count {
    let outPath = arguments[idx + 1]
    let page: AppState.PanelPage = arguments.contains("--detailed") ? .detailed : .overview
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)

    let state = AppState()
    state.page = page
    let wantsSettings = arguments.contains("--settings")
    // Screenshots go into a public README, so never bake a real account into one.
    let redact = arguments.contains("--redact")
    state.refresh {
        if redact {
            for (kind, var snap) in state.snapshots {
                snap.accountLabel = snap.accountLabel.map { _ in "you@example.com" }
                state.snapshots[kind] = snap
            }
        }
        let view = AnyView(
            wantsSettings
                ? AnyView(SettingsView(state: state))
                : AnyView(PanelView(state: state, openSettings: {}))
        ).background(Color(nsColor: .windowBackgroundColor))
        let hosting = NSHostingView(rootView: view)
        hosting.frame.size = hosting.fittingSize
        guard let rep = hosting.bitmapImageRepForCachingDisplay(in: hosting.bounds) else { exit(1) }
        hosting.cacheDisplay(in: hosting.bounds, to: rep)
        guard let data = rep.representation(using: .png, properties: [:]) else { exit(1) }
        try? data.write(to: URL(fileURLWithPath: outPath))
        print("wrote \(outPath) (\(Int(hosting.frame.width))x\(Int(hosting.frame.height)))")
        exit(0)
    }
    app.run()
}

// GUI mode
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
