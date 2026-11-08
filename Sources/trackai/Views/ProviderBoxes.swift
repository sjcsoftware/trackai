import SwiftUI

/// Overview: the three headline numbers for one provider, in the order the
/// windows actually tighten — the rolling session first, then today, then the week.
/// Providers without a daily window (Codex, Copilot) skip the middle row, and
/// plans with no weekly window (Copilot's AI-credit plans) skip the last.
struct OverviewBoxView: View {
    let snapshot: ProviderSnapshot

    var body: some View {
        ProviderBox(snapshot: snapshot) {
            if let local = snapshot.local, snapshot.status != .notInstalled {
                primaryRow
                if snapshot.kind.tracksDailyUsage {
                    dailyRow(local)
                }
                if snapshot.weeklyIsFromPlan || snapshot.hasWeekly {
                    weeklyRow(local)
                }
            } else {
                Text(emptyMessage)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    @ViewBuilder
    private var primaryRow: some View {
        if let primary = snapshot.primaryLimit {
            BarRow(name: primary.displayName,
                   percent: primary.percent,
                   valueText: primary.detail,
                   subtitle: Formatting.resetsIn(primary.resetsAt),
                   emphasised: true)
        } else {
            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text(snapshot.kind.primaryName).font(.system(size: 12, weight: .semibold))
                    Spacer()
                    Text("—").font(.system(size: 12, weight: .semibold, design: .rounded))
                        .foregroundStyle(.tertiary)
                }
                Text(primaryPlaceholder)
                    .font(.system(size: 9.5)).foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var primaryPlaceholder: String {
        switch snapshot.status {
        case .ok: return snapshot.limitsError ?? "no limit data yet"
        case .expired: return "login expired"
        case .missing: return snapshot.limitsError ?? "not logged in"
        case .notInstalled: return "not installed"
        }
    }

    @ViewBuilder
    private func dailyRow(_ local: LocalStats) -> some View {
        if local.hasDailyBaseline {
            BarRow(name: "Daily",
                   percent: local.dailyRelativePercent,
                   valueText: "\(Formatting.tokens(local.today.total)) · \(Formatting.usd(local.today.cost))",
                   subtitle: "\(local.today.messages) messages · vs. busiest day in 30d",
                   emphasised: true)
        } else {
            // Without a few days to compare against, a percentage here would
            // only ever say "today is your busiest day" and read as 100%.
            VStack(alignment: .leading, spacing: 2) {
                StatLine(name: "Daily", totals: local.today)
                Text("building a 30-day baseline · \(local.activeDays30) active day\(local.activeDays30 == 1 ? "" : "s")")
                    .font(.system(size: 9.5))
                    .foregroundStyle(.tertiary)
            }
        }
    }

    @ViewBuilder
    private func weeklyRow(_ local: LocalStats) -> some View {
        BarRow(name: snapshot.weeklyIsFromPlan ? "Weekly limit" : "Weekly",
               percent: snapshot.weeklyPercent ?? 0,
               valueText: "\(Formatting.tokens(local.last7d.total)) · \(Formatting.usd(local.last7d.cost))",
               subtitle: weeklySubtitle,
               emphasised: true)
    }

    private var weeklySubtitle: String? {
        if snapshot.weeklyIsFromPlan {
            return Formatting.resetsIn(snapshot.weeklyLimit?.resetsAt) ?? "of your plan's weekly window"
        }
        return "vs. busiest 7-day stretch"
    }

    private var emptyMessage: String {
        switch snapshot.status {
        case .notInstalled:
            return "\(snapshot.kind.displayName) isn't installed. Run `\(snapshot.kind.command)` once and it will appear here."
        case .missing:
            return "Not logged in yet — no usage recorded."
        default:
            return "No usage recorded yet."
        }
    }
}

/// Detailed: plan windows, every local time window, and the per-model split.
struct DetailBoxView: View {
    let snapshot: ProviderSnapshot

    var body: some View {
        ProviderBox(snapshot: snapshot) {
            if snapshot.status == .notInstalled {
                Text("Not installed on this Mac.")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
            } else {
                planSection
                Divider().opacity(0.35)
                localSection
                if let local = snapshot.local, !local.perModel30d.isEmpty {
                    Divider().opacity(0.35)
                    modelSection(local)
                }
                footer
            }
        }
    }

    // MARK: Plan windows

    @ViewBuilder
    private var planSection: some View {
        sectionTitle("Plan limits")
        if !snapshot.limits.isEmpty {
            ForEach(snapshot.limits) { limit in
                BarRow(name: limit.displayName,
                       percent: limit.percent,
                       valueText: limit.detail,
                       subtitle: Formatting.resetsIn(limit.resetsAt))
            }
            if let note = snapshot.limitsError {
                Text(note).font(.system(size: 9.5)).foregroundStyle(.tertiary)
            }
        } else {
            Text(planPlaceholder)
                .font(.system(size: 11))
                .foregroundStyle(snapshot.status == .ok ? Color.secondary : Color.orange)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var planPlaceholder: String {
        if let err = snapshot.limitsError { return err }
        switch snapshot.status {
        case .ok: return "Loading…"
        case .expired:
            return "Login expired — run `\(snapshot.kind.command)` in a terminal to refresh."
        case .missing:
            return "Not logged in — run `\(snapshot.kind.command)` in a terminal."
        case .notInstalled: return "Not installed."
        }
    }

    // MARK: Local token windows

    @ViewBuilder
    private var localSection: some View {
        sectionTitle("Token usage (local)")
        if let local = snapshot.local {
            if snapshot.kind.tracksDailyUsage, local.hasDailyBaseline {
                BarRow(name: "Today",
                       percent: local.dailyRelativePercent,
                       valueText: "\(Formatting.tokens(local.today.total)) · \(costPrefix)\(Formatting.usd(local.today.cost))",
                       subtitle: "\(local.today.messages) messages · vs. busiest day in 30d")
            } else {
                StatLine(name: "Today", totals: local.today, costPrefix: costPrefix)
            }
            StatLine(name: "Last 5 hours", totals: local.last5h, costPrefix: costPrefix)
            StatLine(name: "Last 7 days", totals: local.last7d, costPrefix: costPrefix)
            StatLine(name: "Last 30 days", totals: local.last30d, costPrefix: costPrefix)
            StatLine(name: "All time", totals: local.allTime, costPrefix: costPrefix)
            Text(breakdown(local.last30d))
                .font(.system(size: 9.5))
                .foregroundStyle(.tertiary)
        } else {
            Text("No transcripts found yet.")
                .font(.system(size: 11)).foregroundStyle(.secondary)
        }
    }

    private func breakdown(_ t: TokenTotals) -> String {
        "30d: in \(Formatting.tokens(t.input)) · out \(Formatting.tokens(t.output)) · cache \(Formatting.tokens(t.cacheCreate + t.cacheRead))"
    }

    private var costPrefix: String { snapshot.kind.costIsEstimate ? "est. " : "" }

    // MARK: Per-model

    @ViewBuilder
    private func modelSection(_ local: LocalStats) -> some View {
        sectionTitle("By model (last 30 days)")
        // Share of the window's tokens, not a quota — tinted neutrally so a
        // dominant model never looks like a warning.
        let total = max(1, local.last30d.total)
        ForEach(local.perModel30d.prefix(5)) { m in
            BarRow(name: snapshot.kind.prettyModelName(m.model),
                   percent: Double(m.totals.total) / Double(total) * 100,
                   valueText: "\(Formatting.tokens(m.totals.total))",
                   subtitle: "in \(Formatting.tokens(m.totals.input)) · out \(Formatting.tokens(m.totals.output)) · cache \(Formatting.tokens(m.totals.cacheCreate + m.totals.cacheRead))",
                   tint: .accentColor)
        }
    }

    // MARK: Chrome

    private func sectionTitle(_ text: String) -> some View {
        Text(text.uppercased())
            .font(.system(size: 9, weight: .semibold))
            .foregroundStyle(.tertiary)
            .padding(.top, 1)
    }

    @ViewBuilder
    private var footer: some View {
        let bits = [snapshot.accountLabel,
                    snapshot.planDetail,
                    snapshot.limitsFetchedAt.flatMap { Formatting.agoShort($0).map { "limits \($0)" } }]
            .compactMap { $0 }
        if !bits.isEmpty {
            Text(bits.joined(separator: " · "))
                .font(.system(size: 9.5))
                .foregroundStyle(.tertiary)
                .lineLimit(1)
                .truncationMode(.middle)
        }
    }
}
