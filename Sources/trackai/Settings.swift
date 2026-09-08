import Foundation
import SwiftUI
import ServiceManagement

/// Which number the menu bar (and the overview bars) reports.
enum UsageMetric: String, CaseIterable, Identifiable, Codable {
    case daily
    case weekly
    case session

    var id: String { rawValue }

    var label: String {
        switch self {
        case .daily: return "Daily usage"
        case .weekly: return "Weekly limit"
        case .session: return "Session (5h) limit"
        }
    }

    var shortLabel: String {
        switch self {
        case .daily: return "Daily"
        case .weekly: return "Weekly"
        case .session: return "Session"
        }
    }
}

/// How the menu bar percentage is derived from the configured providers.
enum MenuBarMode: String, CaseIterable, Identifiable, Codable {
    case average
    case single
    case highest

    var id: String { rawValue }

    var label: String {
        switch self {
        case .average: return "Average of selected providers"
        case .highest: return "Highest of selected providers"
        case .single: return "One provider"
        }
    }
}

/// Reads a value on the main thread. Provider scans run on a utility queue but
/// need settings that only the UI mutates, and blocking there is safe because
/// nothing on main ever waits for a scan.
func onMain<T>(_ body: () -> T) -> T {
    Thread.isMainThread ? body() : DispatchQueue.main.sync(execute: body)
}

final class Settings: ObservableObject {
    static let shared = Settings()
    private let d = UserDefaults.standard

    // Layout
    @Published var providerOrder: [ProviderKind] {
        didSet { d.set(providerOrder.map(\.rawValue), forKey: "providerOrder") }
    }
    @Published var enabledProviders: Set<ProviderKind> {
        didSet { d.set(enabledProviders.map(\.rawValue).sorted(), forKey: "enabledProviders") }
    }

    // Menu bar
    @Published var menuBarMode: MenuBarMode { didSet { d.set(menuBarMode.rawValue, forKey: "menuBarMode") } }
    @Published var menuBarMetric: UsageMetric { didSet { d.set(menuBarMetric.rawValue, forKey: "menuBarMetric") } }
    @Published var menuBarProviders: Set<ProviderKind> {
        didSet { d.set(menuBarProviders.map(\.rawValue).sorted(), forKey: "menuBarProviders") }
    }
    @Published var menuBarSingleProvider: ProviderKind {
        didSet { d.set(menuBarSingleProvider.rawValue, forKey: "menuBarSingleProvider") }
    }
    @Published var showPercentInMenuBar: Bool { didSet { d.set(showPercentInMenuBar, forKey: "showPercentInMenuBar") } }

    // Colors
    @Published var warnThreshold: Double { didSet { d.set(warnThreshold, forKey: "warnThreshold") } }
    @Published var critThreshold: Double { didSet { d.set(critThreshold, forKey: "critThreshold") } }

    // Appearance
    @Published var transparency: Double { didSet { d.set(transparency, forKey: "transparency") } }
    @Published var opaqueBackground: Bool { didSet { d.set(opaqueBackground, forKey: "opaqueBackground") } }

    // General
    @Published var refreshInterval: Double { didSet { d.set(refreshInterval, forKey: "refreshInterval") } }
    @Published var launchAtLogin: Bool {
        didSet {
            d.set(launchAtLogin, forKey: "launchAtLogin")
            applyLaunchAtLogin()
        }
    }

    // Provider configuration
    @Published var claudeExtraConfigDirs: [String] {
        didSet { d.set(claudeExtraConfigDirs, forKey: "claudeExtraConfigDirs") }
    }
    @Published var codexHome: String { didSet { d.set(codexHome, forKey: "codexHome") } }

    private init() {
        let storedOrder = (d.stringArray(forKey: "providerOrder") ?? []).compactMap(ProviderKind.init(rawValue:))
        // Append any provider added by a later version so nothing silently vanishes.
        providerOrder = storedOrder + ProviderKind.defaultOrder.filter { !storedOrder.contains($0) }

        if let stored = d.stringArray(forKey: "enabledProviders") {
            enabledProviders = Set(stored.compactMap(ProviderKind.init(rawValue:)))
        } else {
            enabledProviders = Set(ProviderKind.allCases)
        }

        menuBarMode = MenuBarMode(rawValue: d.string(forKey: "menuBarMode") ?? "") ?? .average
        menuBarMetric = UsageMetric(rawValue: d.string(forKey: "menuBarMetric") ?? "") ?? .daily
        if let stored = d.stringArray(forKey: "menuBarProviders") {
            menuBarProviders = Set(stored.compactMap(ProviderKind.init(rawValue:)))
        } else {
            menuBarProviders = Set(ProviderKind.allCases)
        }
        menuBarSingleProvider = ProviderKind(rawValue: d.string(forKey: "menuBarSingleProvider") ?? "") ?? .claude
        showPercentInMenuBar = d.object(forKey: "showPercentInMenuBar") as? Bool ?? true

        warnThreshold = d.object(forKey: "warnThreshold") as? Double ?? 50
        critThreshold = d.object(forKey: "critThreshold") as? Double ?? 80

        transparency = d.object(forKey: "transparency") as? Double ?? 0.65
        opaqueBackground = d.bool(forKey: "opaqueBackground")

        refreshInterval = d.object(forKey: "refreshInterval") as? Double ?? 120
        launchAtLogin = d.bool(forKey: "launchAtLogin")

        claudeExtraConfigDirs = d.stringArray(forKey: "claudeExtraConfigDirs") ?? []
        codexHome = d.string(forKey: "codexHome") ?? ""
    }

    /// The providers whose boxes are shown, in the user's order.
    var visibleProviders: [ProviderKind] {
        providerOrder.filter { enabledProviders.contains($0) }
    }

    /// Red never sits below orange, however the user drags the two sliders.
    private var effectiveCrit: Double { max(critThreshold, warnThreshold) }

    func usageColor(percent: Double) -> Color {
        if percent < warnThreshold { return .green }
        if percent < effectiveCrit { return .orange }
        return .red
    }

    func usageNSColor(percent: Double) -> NSColor {
        if percent < warnThreshold { return .systemGreen }
        if percent < effectiveCrit { return .systemOrange }
        return .systemRed
    }

    private func applyLaunchAtLogin() {
        guard Bundle.main.bundleIdentifier != nil else { return }
        do {
            if launchAtLogin {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
        } catch {
            NSLog("trackai: launch-at-login change failed: \(error)")
        }
    }
}
