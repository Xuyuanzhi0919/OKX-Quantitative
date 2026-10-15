import SwiftUI

enum StrategyPalette {
    static let ink = Color(red: 0.006, green: 0.006, blue: 0.008)
    static let raised = Color(red: 0.055, green: 0.058, blue: 0.064)
    static let cyan = Color(red: 1.0, green: 0.16, blue: 0.37)
    static let violet = Color(red: 0.54, green: 0.16, blue: 1.0)
    static let amber = Color(red: 1.0, green: 0.62, blue: 0.05)
    static let mint = Color(red: 0.18, green: 0.90, blue: 0.52)
    static let coral = Color(red: 1.0, green: 0.18, blue: 0.38)
    static let text = Color.white
    static let secondaryText = Color.white.opacity(0.55)
    static let hairline = Color.white.opacity(0.11)

    static var background: LinearGradient {
        LinearGradient(
            colors: [Color.white.opacity(0.075), raised],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }
}

struct TradingBackdrop: View {
    var body: some View {
        ZStack {
            StrategyPalette.ink
            RadialGradient(
                colors: [StrategyPalette.coral.opacity(0.15), .clear],
                center: .topTrailing,
                startRadius: 0,
                endRadius: 260
            )
            RadialGradient(
                colors: [StrategyPalette.mint.opacity(0.07), .clear],
                center: .bottomLeading,
                startRadius: 0,
                endRadius: 240
            )
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
    }
}

struct TradingCardSurface: View {
    var cornerRadius: CGFloat = 22
    var accent: Color? = nil

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                .fill(StrategyPalette.raised)
            RadialGradient(
                colors: [(accent ?? StrategyPalette.coral).opacity(0.10), .clear],
                center: .topTrailing,
                startRadius: 0,
                endRadius: 180
            )
        }
        .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                .stroke(StrategyPalette.hairline, lineWidth: 1)
        }
    }
}

struct StrategyCardView: View {
    let snapshot: StrategySnapshot
    var compact = false

    private var pnlColor: Color {
        snapshot.totalPnL >= 0 ? StrategyPalette.mint : StrategyPalette.coral
    }

    private var statusColor: Color {
        snapshot.isRunning ? StrategyPalette.mint : .orange
    }

    private var formattedPnL: String {
        let sign = snapshot.totalPnL >= 0 ? "+" : "−"
        return "\(sign)$\(abs(snapshot.totalPnL).formatted(.number.precision(.fractionLength(2))))"
    }

    var body: some View {
        if compact {
            smallLayout
        } else {
            mediumLayout
        }
    }

    private var smallLayout: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                mark
                Spacer(minLength: 6)
                statusDot
            }

            Spacer(minLength: 8)

            Text("收益")
                .font(.caption2.weight(.medium))
                .foregroundStyle(StrategyPalette.secondaryText)

            Text(formattedPnL)
                .font(.system(size: 28, weight: .bold, design: .rounded))
                .foregroundStyle(pnlColor)
                .minimumScaleFactor(0.64)
                .lineLimit(1)

            Spacer(minLength: 8)

            statusDot
        }
        .padding(16)
    }

    private var mediumLayout: some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 9) {
                    mark
                    Text(snapshot.strategyName)
                        .font(.system(size: 14, weight: .semibold, design: .rounded))
                        .foregroundStyle(StrategyPalette.text)
                        .lineLimit(1)
                }

                Spacer(minLength: 14)

                Text("累计盈亏")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(StrategyPalette.secondaryText)

                Text(formattedPnL)
                    .font(.system(size: 31, weight: .bold, design: .rounded))
                    .foregroundStyle(pnlColor)
                    .minimumScaleFactor(0.72)
                    .lineLimit(1)

                Spacer(minLength: 10)
                statusPill
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Rectangle()
                .fill(StrategyPalette.hairline)
                .frame(width: 1)
                .padding(.vertical, 2)
                .padding(.horizontal, 16)

            VStack(alignment: .leading, spacing: 11) {
                metricRow(title: "策略仓", value: "\(snapshot.strategyOpenPositions)", icon: "square.stack.3d.up")
                metricRow(title: "交易", value: "\(snapshot.totalTrades)", icon: "arrow.left.arrow.right")
                metricRow(
                    title: "胜率",
                    value: snapshot.winRate.formatted(.number.precision(.fractionLength(0))) + "%",
                    icon: "scope"
                )
            }
            .frame(width: 124)
        }
        .padding(16)
    }

    private var mark: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(StrategyPalette.cyan.opacity(0.13))
            Image(systemName: "chart.line.uptrend.xyaxis")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(StrategyPalette.cyan)
        }
        .frame(width: 30, height: 30)
    }

    private var statusDot: some View {
        HStack(spacing: 5) {
            Circle()
                .fill(statusColor)
                .frame(width: 6, height: 6)
                .shadow(color: statusColor.opacity(0.65), radius: 4)
            Text(snapshot.isRunning ? "LIVE" : "OFF")
                .font(.system(size: 9, weight: .bold, design: .rounded))
                .tracking(0.8)
                .foregroundStyle(StrategyPalette.secondaryText)
        }
    }

    private var statusPill: some View {
        HStack(spacing: 4) {
            Circle().fill(statusColor).frame(width: 5, height: 5)
            Text(snapshot.isRunning ? "运行中" : "已停止")
        }
        .font(.system(size: 9, weight: .semibold))
        .foregroundStyle(StrategyPalette.text.opacity(0.82))
        .padding(.horizontal, 7)
        .padding(.vertical, 4)
        .background(statusColor.opacity(0.12), in: Capsule())
    }

    private func metricRow(title: String, value: String, icon: String) -> some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(StrategyPalette.cyan)
                .frame(width: 16)
            Text(title)
                .font(.caption2)
                .foregroundStyle(StrategyPalette.secondaryText)
            Spacer(minLength: 4)
            Text(value)
                .font(.system(size: 12, weight: .semibold, design: .rounded))
                .foregroundStyle(StrategyPalette.text)
        }
    }
}
