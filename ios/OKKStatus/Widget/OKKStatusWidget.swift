import SwiftUI
import WidgetKit

struct StrategyEntry: TimelineEntry {
    let date: Date
    let snapshot: StrategySnapshot
    let errorMessage: String?
}

struct StrategyTimelineProvider: TimelineProvider {
    func placeholder(in context: Context) -> StrategyEntry {
        StrategyEntry(date: .now, snapshot: .placeholder, errorMessage: nil)
    }

    func getSnapshot(in context: Context, completion: @escaping (StrategyEntry) -> Void) {
        if context.isPreview {
            completion(placeholder(in: context))
            return
        }
        load(completion: completion)
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<StrategyEntry>) -> Void) {
        load { entry in
            let nextRefresh = Calendar.current.date(byAdding: .minute, value: 15, to: .now) ?? .now.addingTimeInterval(900)
            completion(Timeline(entries: [entry], policy: .after(nextRefresh)))
        }
    }

    private func load(completion: @escaping (StrategyEntry) -> Void) {
        Task {
            do {
                let snapshot = try await StrategyAPI().fetchSnapshot()
                completion(StrategyEntry(date: .now, snapshot: snapshot, errorMessage: nil))
            } catch {
                completion(StrategyEntry(date: .now, snapshot: .placeholder, errorMessage: error.localizedDescription))
            }
        }
    }
}

struct OKKStatusWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: StrategyEntry

    private var pnlColor: Color {
        entry.snapshot.totalPnL >= 0 ? StrategyPalette.mint : StrategyPalette.coral
    }

    private var statusColor: Color {
        entry.snapshot.isRunning ? StrategyPalette.mint : StrategyPalette.amber
    }

    private var formattedPnL: String {
        let sign = entry.snapshot.totalPnL >= 0 ? "+" : "−"
        return "\(sign)$\(abs(entry.snapshot.totalPnL).formatted(.number.precision(.fractionLength(2))))"
    }

    var body: some View {
        ZStack {
            if family == .systemSmall {
                smallWidget
            } else {
                mediumWidget
            }

            if entry.errorMessage != nil {
                Image(systemName: "wifi.exclamationmark")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(StrategyPalette.amber)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
                    .padding(14)
                    .accessibilityLabel("数据刷新失败")
            }
        }
        .containerBackground(for: .widget) {
            widgetBackground
        }
        .widgetURL(OKKConfiguration.serverURL)
    }

    private var smallWidget: some View {
        VStack(alignment: .leading, spacing: 0) {
            widgetHeader(showSubtitle: false)

            Spacer(minLength: 10)

            Text("累计盈亏")
                .font(.caption2.weight(.medium))
                .foregroundStyle(StrategyPalette.secondaryText)

            Text(formattedPnL)
                .font(.system(size: 30, weight: .bold, design: .rounded))
                .foregroundStyle(pnlColor)
                .minimumScaleFactor(0.60)
                .lineLimit(1)

            Spacer(minLength: 10)

            HStack(alignment: .firstTextBaseline) {
                systemMetric(label: "策略仓", value: "\(entry.snapshot.strategyOpenPositions)")
                Spacer(minLength: 8)
                systemMetric(
                    label: "胜率",
                    value: entry.snapshot.winRate.formatted(.number.precision(.fractionLength(0))) + "%"
                )
            }
        }
        .padding(16)
    }

    private var mediumWidget: some View {
        VStack(alignment: .leading, spacing: 0) {
            widgetHeader(showSubtitle: true)

            Spacer(minLength: 9)

            HStack(alignment: .lastTextBaseline) {
                VStack(alignment: .leading, spacing: 1) {
                    Text("累计盈亏")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(StrategyPalette.secondaryText)
                    Text(formattedPnL)
                        .font(.system(size: 30, weight: .bold, design: .rounded))
                        .foregroundStyle(pnlColor)
                        .minimumScaleFactor(0.70)
                        .lineLimit(1)
                }

                Spacer(minLength: 12)

                VStack(alignment: .trailing, spacing: 2) {
                    Text("更新于")
                        .font(.system(size: 8, weight: .medium))
                        .foregroundStyle(.white.opacity(0.32))
                    Text(entry.date, style: .time)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(StrategyPalette.secondaryText)
                }
            }

            Spacer(minLength: 8)

            Rectangle()
                .fill(StrategyPalette.hairline)
                .frame(height: 1)

            HStack {
                systemMetric(label: "策略持仓", value: "\(entry.snapshot.strategyOpenPositions)")
                Spacer()
                systemMetric(label: "累计交易", value: "\(entry.snapshot.totalTrades)")
                Spacer()
                systemMetric(
                    label: "胜率",
                    value: entry.snapshot.winRate.formatted(.number.precision(.fractionLength(0))) + "%"
                )
            }
            .padding(.top, 8)
        }
        .padding(16)
    }

    private var widgetBackground: some View {
        ZStack {
            LinearGradient(
                colors: [
                    Color(red: 0.070, green: 0.040, blue: 0.095),
                    Color(red: 0.030, green: 0.024, blue: 0.048)
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            RadialGradient(
                colors: [StrategyPalette.violet.opacity(0.22), .clear],
                center: .topTrailing,
                startRadius: 0,
                endRadius: 210
            )
            RadialGradient(
                colors: [StrategyPalette.cyan.opacity(0.10), .clear],
                center: .bottomLeading,
                startRadius: 0,
                endRadius: 170
            )
            RadialGradient(
                colors: [pnlColor.opacity(0.055), .clear],
                center: .bottomTrailing,
                startRadius: 0,
                endRadius: 140
            )
        }
    }

    private func widgetHeader(showSubtitle: Bool) -> some View {
        HStack(spacing: 9) {
            Image(systemName: "chart.line.uptrend.xyaxis")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(StrategyPalette.cyan)
                .frame(width: 30, height: 30)
                .background(StrategyPalette.cyan.opacity(0.13), in: RoundedRectangle(cornerRadius: 8, style: .continuous))

            VStack(alignment: .leading, spacing: 1) {
                Text(showSubtitle ? entry.snapshot.strategyName : "策略")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(StrategyPalette.text)
                    .lineLimit(1)
                if showSubtitle {
                    Text("1H · 3x")
                        .font(.system(size: 8, weight: .medium, design: .rounded))
                        .foregroundStyle(StrategyPalette.secondaryText)
                }
            }

            Spacer(minLength: 4)

            HStack(spacing: 5) {
            Circle()
                .fill(statusColor)
                .frame(width: 6, height: 6)
                Text(entry.snapshot.isRunning ? "运行" : "停止")
                    .lineLimit(1)
                    .fixedSize()
            }
            .font(.system(size: 9, weight: .semibold))
            .foregroundStyle(.white.opacity(0.76))
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
            .background(statusColor.opacity(0.11), in: Capsule())
        }
    }

    private func systemMetric(label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(value)
                .font(.system(size: 13, weight: .semibold, design: .rounded))
                .foregroundStyle(StrategyPalette.text)
            Text(label)
                .font(.system(size: 8, weight: .medium))
                .foregroundStyle(StrategyPalette.secondaryText)
        }
    }
}

struct OKKStatusWidget: Widget {
    let kind = "OKKStatusWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: StrategyTimelineProvider()) { entry in
            OKKStatusWidgetView(entry: entry)
        }
        .configurationDisplayName("量化脉搏")
        .description("快速查看策略运行状态、盈亏与最新交易信号。")
        .supportedFamilies([.systemSmall, .systemMedium])
        .contentMarginsDisabled()
    }
}

@main
struct OKKStatusWidgetBundle: WidgetBundle {
    var body: some Widget {
        OKKStatusWidget()
    }
}

#Preview(as: .systemMedium) {
    OKKStatusWidget()
} timeline: {
    StrategyEntry(date: .now, snapshot: .placeholder, errorMessage: nil)
}
