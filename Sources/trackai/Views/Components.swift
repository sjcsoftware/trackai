import SwiftUI

/// A labelled usage bar: name on the left, value on the right, coloured track
/// underneath, optional caption below.
struct BarRow: View {
    let name: String
    let percent: Double
    var valueText: String?
    var subtitle: String?
    var emphasised = false
    /// Set for bars that show a share rather than a quota, so they are not
    /// coloured as if the user were close to a limit.
    var tint: Color?
    @ObservedObject private var settings = Settings.shared

    private var barColor: Color { tint ?? settings.usageColor(percent: percent) }

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Text(name)
                    .font(.system(size: emphasised ? 12 : 11, weight: emphasised ? .semibold : .medium))
                Spacer(minLength: 4)
                Text(Formatting.percent(percent))
                    .font(.system(size: emphasised ? 12 : 11, weight: .semibold, design: .rounded))
                    .foregroundStyle(tint ?? settings.usageColor(percent: percent))
                if let valueText {
                    Text(valueText)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.primary.opacity(0.09))
                    Capsule()
                        .fill(barColor)
                        .frame(width: max(4, geo.size.width * min(1, percent / 100)))
                }
            }
            .frame(height: emphasised ? 7 : 5)
            if let subtitle {
                Text(subtitle)
                    .font(.system(size: 9.5))
                    .foregroundStyle(.tertiary)
            }
        }
    }
}

/// A plain right-aligned figure for windows that have no percentage of their own.
struct StatLine: View {
    let name: String
    let totals: TokenTotals
    var costPrefix = ""

    var body: some View {
        HStack {
            Text(name).font(.system(size: 11)).foregroundStyle(.secondary)
            Spacer()
            Text("\(Formatting.tokens(totals.total)) · \(costPrefix)\(Formatting.usd(totals.cost))")
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(.secondary)
        }
    }
}

/// Blurs what is behind it *within* the window, so each provider box reads as a
/// frosted pane sitting on the panel rather than a flat rectangle.
struct BlockGlass: NSViewRepresentable {
    var cornerRadius: CGFloat = 14

    func makeNSView(context: Context) -> NSVisualEffectView {
        let v = NSVisualEffectView()
        v.blendingMode = .withinWindow
        v.material = .popover
        v.state = .active
        v.wantsLayer = true
        v.layer?.cornerRadius = cornerRadius
        v.layer?.cornerCurve = .continuous
        v.layer?.masksToBounds = true
        return v
    }

    func updateNSView(_ v: NSVisualEffectView, context: Context) {
        v.layer?.cornerRadius = cornerRadius
    }
}

/// The rounded frosted box one provider's stats live in, with its mark in the
/// top-left corner.
struct ProviderBox<Content: View>: View {
    let snapshot: ProviderSnapshot
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 7) {
                ProviderMarkView(kind: snapshot.kind, size: 16)
                Text(snapshot.kind.displayName)
                    .font(.system(size: 12.5, weight: .semibold))
                Spacer(minLength: 4)
                if let plan = snapshot.planName, snapshot.status == .ok {
                    Text(plan.capitalized)
                        .font(.system(size: 9.5, weight: .semibold))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Capsule().fill(Color.primary.opacity(0.10)))
                        .foregroundStyle(.secondary)
                } else if snapshot.status != .ok {
                    Text(snapshot.status.summary)
                        .font(.system(size: 9.5, weight: .medium))
                        .foregroundStyle(snapshot.status == .notInstalled ? Color.secondary : Color.orange)
                }
            }
            content
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(BlockGlass())
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.5)
        )
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

/// Two-state pill used for the Overview / Detailed switch in the footer.
struct PagePicker: View {
    @Binding var page: AppState.PanelPage

    var body: some View {
        HStack(spacing: 2) {
            segment("Overview", .overview)
            segment("Detailed", .detailed)
        }
        .padding(2)
        .background(Capsule().fill(Color.primary.opacity(0.08)))
    }

    private func segment(_ title: String, _ value: AppState.PanelPage) -> some View {
        let selected = page == value
        return Button(action: { withAnimation(.easeInOut(duration: 0.16)) { page = value } }) {
            Text(title)
                .font(.system(size: 11, weight: selected ? .semibold : .regular))
                .foregroundStyle(selected ? Color.primary : Color.secondary)
                .padding(.horizontal, 10)
                .padding(.vertical, 3)
                .background(
                    Capsule().fill(selected ? Color.primary.opacity(0.13) : Color.clear)
                )
        }
        .buttonStyle(.plain)
    }
}

/// Header/footer icon button, kept visually quiet next to the stats.
struct IconButton: View {
    let systemName: String
    let help: String
    var dimmed = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: 12))
                .frame(width: 20, height: 20)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundStyle(.secondary)
        .opacity(dimmed ? 0.4 : 1)
        .help(help)
    }
}
