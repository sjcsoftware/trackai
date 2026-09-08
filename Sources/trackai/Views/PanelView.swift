import SwiftUI

struct PanelView: View {
    @ObservedObject var state: AppState
    @ObservedObject var settings = Settings.shared
    var openSettings: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
                .padding(.horizontal, 14)
                .padding(.top, 12)
                .padding(.bottom, 10)

            content

            footer
                .padding(.horizontal, 14)
                .padding(.top, 9)
                .padding(.bottom, 11)
        }
        .frame(width: 344)
    }

    // MARK: Header

    private var header: some View {
        HStack(spacing: 8) {
            Image(nsImage: StatusIcon.gauge(percent: state.menuBarPercent, color: headerColor, size: 16))
            Text("trackai").font(.system(size: 13, weight: .bold))
            if let percent = state.menuBarPercent {
                Text(Formatting.percent(percent))
                    .font(.system(size: 11, weight: .semibold, design: .rounded))
                    .foregroundStyle(settings.usageColor(percent: percent))
            }
            Spacer()
            IconButton(systemName: "arrow.clockwise", help: "Refresh now", dimmed: state.isRefreshing) {
                state.refresh(force: true)
            }
            IconButton(systemName: "power", help: "Quit trackai") {
                NSApp.terminate(nil)
            }
        }
    }

    private var headerColor: NSColor {
        state.menuBarPercent.map { settings.usageNSColor(percent: $0) } ?? .systemGray
    }

    // MARK: Body

    @ViewBuilder
    private var content: some View {
        let visible = state.visibleSnapshots
        if visible.isEmpty {
            VStack(spacing: 6) {
                Text("No providers enabled")
                    .font(.system(size: 12, weight: .medium))
                Text("Open Settings → Providers to turn one on.")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 28)
        } else {
            ScrollView(showsIndicators: false) {
                VStack(spacing: 9) {
                    ForEach(visible, id: \.kind) { snapshot in
                        if state.page == .overview {
                            OverviewBoxView(snapshot: snapshot)
                        } else {
                            DetailBoxView(snapshot: snapshot)
                        }
                    }
                }
                .padding(.horizontal, 14)
                .padding(.bottom, 2)
            }
            .frame(maxHeight: state.page == .overview ? 420 : 520)
        }
    }

    // MARK: Footer

    private var footer: some View {
        HStack(spacing: 8) {
            PagePicker(page: $state.page)
            Spacer()
            if let last = state.lastRefresh, let ago = Formatting.agoShort(last) {
                Text(ago)
                    .font(.system(size: 9.5))
                    .foregroundStyle(.tertiary)
            }
            IconButton(systemName: "gearshape", help: "Settings", action: openSettings)
        }
    }
}
