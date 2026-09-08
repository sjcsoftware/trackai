import SwiftUI
import UniformTypeIdentifiers

struct SettingsView: View {
    @ObservedObject var settings = Settings.shared
    @ObservedObject var state: AppState
    @State private var newClaudeDir = ""
    @State private var dragging: ProviderKind?

    var body: some View {
        Form {
            orderSection
            menuBarSection
            thresholdSection
            appearanceSection
            providerSection
            generalSection
        }
        .formStyle(.grouped)
        .frame(width: 460, height: 620)
    }

    // MARK: 1. Box order

    private var orderSection: some View {
        Section {
            HStack(spacing: 10) {
                ForEach(settings.providerOrder) { kind in
                    orderTile(kind)
                        .onDrag {
                            dragging = kind
                            return NSItemProvider(object: kind.rawValue as NSString)
                        }
                        .onDrop(of: [.text],
                                delegate: ProviderDropDelegate(target: kind,
                                                               dragging: $dragging,
                                                               order: $settings.providerOrder))
                }
                Spacer()
            }
            .animation(.easeInOut(duration: 0.18), value: settings.providerOrder)
            Text("Drag the logos through each other to change the order the boxes appear in.")
                .font(.system(size: 10)).foregroundStyle(.secondary)
        } header: {
            Text("Provider order")
        }
    }

    private func orderTile(_ kind: ProviderKind) -> some View {
        let on = settings.enabledProviders.contains(kind)
        return VStack(spacing: 5) {
            ProviderMarkView(kind: kind, size: 24)
            Text(kind.displayName)
                .font(.system(size: 9.5, weight: .medium))
                .foregroundStyle(.secondary)
        }
        .frame(width: 96, height: 60)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color.primary.opacity(dragging == kind ? 0.16 : 0.07))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.5)
        )
        .opacity(on ? 1 : 0.4)
        .help(on ? "Drag to reorder" : "Disabled — enable it under Providers")
    }

    // MARK: 2. What the menu bar follows

    private var menuBarSection: some View {
        Section {
            Picker("Follows", selection: $settings.menuBarMode) {
                ForEach(MenuBarMode.allCases) { Text($0.label).tag($0) }
            }
            Picker("Metric", selection: $settings.menuBarMetric) {
                ForEach(UsageMetric.allCases) { Text($0.label).tag($0) }
            }
            if settings.menuBarMode == .single {
                Picker("Provider", selection: $settings.menuBarSingleProvider) {
                    ForEach(ProviderKind.allCases) { Text($0.displayName).tag($0) }
                }
            } else {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Include").font(.system(size: 11)).foregroundStyle(.secondary)
                    ForEach(ProviderKind.allCases) { kind in
                        Toggle(kind.displayName, isOn: Binding(
                            get: { settings.menuBarProviders.contains(kind) },
                            set: { on in
                                if on { settings.menuBarProviders.insert(kind) }
                                else { settings.menuBarProviders.remove(kind) }
                            }))
                    }
                }
            }
            Toggle("Show percentage next to the icon", isOn: $settings.showPercentInMenuBar)
            Text(menuBarExplanation)
                .font(.system(size: 10)).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        } header: {
            Text("Menu bar")
        }
    }

    private var menuBarExplanation: String {
        let metric: String
        switch settings.menuBarMetric {
        case .daily: metric = "today's tokens measured against your busiest day in the last 30"
        case .weekly: metric = "your plan's weekly window (local 7-day usage when a provider has no weekly limit)"
        case .session: metric = "your plan's rolling 5-hour window"
        }
        switch settings.menuBarMode {
        case .average: return "The icon shows the average across the ticked providers of \(metric)."
        case .highest: return "The icon shows whichever ticked provider is highest, using \(metric)."
        case .single: return "The icon shows \(settings.menuBarSingleProvider.displayName) only, using \(metric)."
        }
    }

    // MARK: 3. Colour thresholds

    private var thresholdSection: some View {
        Section {
            HStack {
                Text("Orange above")
                Slider(value: $settings.warnThreshold, in: 10...90, step: 5)
                Text("\(Int(settings.warnThreshold))%").monospacedDigit().frame(width: 40)
            }
            HStack {
                Text("Red above")
                Slider(value: $settings.critThreshold, in: 20...99, step: 1)
                Text("\(Int(settings.critThreshold))%").monospacedDigit().frame(width: 40)
            }
            HStack(spacing: 0) {
                ForEach(0..<50) { i in
                    Rectangle()
                        .fill(settings.usageColor(percent: Double(i) * 2))
                        .frame(height: 6)
                }
            }
            .clipShape(Capsule())
        } header: {
            Text("Colour thresholds")
        } footer: {
            Text("Red is clamped above orange automatically if the sliders cross.")
                .font(.system(size: 10)).foregroundStyle(.secondary)
        }
    }

    // MARK: 4. Appearance

    private var appearanceSection: some View {
        Section {
            Toggle("Opaque background", isOn: $settings.opaqueBackground)
            if !settings.opaqueBackground {
                HStack {
                    Text("Transparency")
                    Slider(value: $settings.transparency, in: 0.1...1.0)
                }
            }
        } header: {
            Text("Appearance")
        }
    }

    // MARK: 5. Providers

    private var providerSection: some View {
        Section {
            ForEach(ProviderKind.allCases) { kind in
                VStack(alignment: .leading, spacing: 4) {
                    Toggle(isOn: Binding(
                        get: { settings.enabledProviders.contains(kind) },
                        set: { on in
                            if on { settings.enabledProviders.insert(kind) }
                            else { settings.enabledProviders.remove(kind) }
                        })) {
                        HStack(spacing: 6) {
                            ProviderMarkView(kind: kind, size: 14)
                            Text(kind.displayName)
                        }
                    }
                    Text(statusLine(kind))
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                        .padding(.leading, 2)
                    if kind == .claude { claudeDirsEditor }
                    if kind == .codex { codexHomeEditor }
                }
                .padding(.vertical, 2)
            }
        } header: {
            Text("Providers")
        } footer: {
            Text("trackai reads the logins the CLIs already store on this Mac. Log into one of them and it shows up here — nothing to paste.")
                .font(.system(size: 10)).foregroundStyle(.secondary)
        }
    }

    private func statusLine(_ kind: ProviderKind) -> String {
        guard let snap = state.snapshots[kind] else { return "checking…" }
        var bits = [snap.status.summary]
        if let label = snap.accountLabel { bits.append(label) }
        if let plan = snap.planName { bits.append(plan.capitalized) }
        return bits.joined(separator: " · ")
    }

    @ViewBuilder
    private var claudeDirsEditor: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(settings.claudeExtraConfigDirs, id: \.self) { dir in
                HStack {
                    Text(dir).font(.system(size: 10, design: .monospaced)).lineLimit(1)
                    Spacer()
                    Button(action: {
                        settings.claudeExtraConfigDirs.removeAll { $0 == dir }
                        state.refresh()
                    }) { Image(systemName: "minus.circle") }
                    .buttonStyle(.plain)
                }
            }
            HStack {
                TextField("~/.claude-work", text: $newClaudeDir)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 11))
                Button("Add") {
                    let trimmed = newClaudeDir.trimmingCharacters(in: .whitespaces)
                    guard !trimmed.isEmpty else { return }
                    settings.claudeExtraConfigDirs.append(trimmed)
                    newClaudeDir = ""
                    state.refresh()
                }
            }
            Text("Extra CLAUDE_CONFIG_DIR paths to fold into Claude Code's totals.")
                .font(.system(size: 9.5)).foregroundStyle(.tertiary)
        }
        .padding(.leading, 20)
    }

    @ViewBuilder
    private var codexHomeEditor: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                TextField("~/.codex (default)", text: $settings.codexHome)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 11))
                Button("Rescan") { state.refresh(force: true) }
            }
            Text("Override CODEX_HOME if your Codex data lives elsewhere.")
                .font(.system(size: 9.5)).foregroundStyle(.tertiary)
        }
        .padding(.leading, 20)
    }

    // MARK: 6. General

    private var generalSection: some View {
        Section {
            Toggle("Launch at login", isOn: $settings.launchAtLogin)
            HStack {
                Text("Refresh every")
                Picker("", selection: $settings.refreshInterval) {
                    Text("30s").tag(30.0)
                    Text("1m").tag(60.0)
                    Text("2m").tag(120.0)
                    Text("5m").tag(300.0)
                }
                .pickerStyle(.segmented)
                .onChange(of: settings.refreshInterval) { _ in state.rescheduleTimer() }
            }
            HStack {
                Button("Refresh now") { state.refresh(force: true) }
                Spacer()
                Button("Quit trackai") { NSApp.terminate(nil) }
            }
        } header: {
            Text("General")
        } footer: {
            Text("trackai \(AppInfo.version) · MIT · © 2026 Cha Seungjoon")
                .font(.system(size: 10)).foregroundStyle(.tertiary)
        }
    }
}

/// Live-swapping drop target: dragging one logo across another reorders them
/// immediately rather than waiting for the drop.
struct ProviderDropDelegate: DropDelegate {
    let target: ProviderKind
    @Binding var dragging: ProviderKind?
    @Binding var order: [ProviderKind]

    func dropEntered(info: DropInfo) {
        guard let dragging, dragging != target,
              let from = order.firstIndex(of: dragging),
              let to = order.firstIndex(of: target) else { return }
        order.move(fromOffsets: IndexSet(integer: from), toOffset: to > from ? to + 1 : to)
    }

    func dropUpdated(info: DropInfo) -> DropProposal? {
        DropProposal(operation: .move)
    }

    func performDrop(info: DropInfo) -> Bool {
        dragging = nil
        return true
    }
}

enum AppInfo {
    static var version: String {
        (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String) ?? "0.1.0"
    }
}
