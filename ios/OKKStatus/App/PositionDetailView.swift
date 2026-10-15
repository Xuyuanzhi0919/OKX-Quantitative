import SwiftUI

struct PositionDetailView: View {
    @ObservedObject var viewModel: StrategyViewModel

    private var positions: [LivePosition] { viewModel.snapshot.positions }
    private var fetchedAt: Date { viewModel.snapshot.fetchedAt }

    var body: some View {
        ZStack {
            TradingBackdrop()

            ScrollView {
                if positions.isEmpty {
                    emptyState
                } else {
                    LazyVStack(spacing: 14) {
                        ForEach(positions) { position in
                            positionCard(position)
                        }
                    }
                    .padding(20)
                }
            }
        }
        .navigationTitle("实盘持仓")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarColorScheme(.dark, for: .navigationBar)
    }

    private var emptyState: some View {
        VStack(spacing: 14) {
            ZStack {
                Circle().fill(StrategyPalette.cyan.opacity(0.10))
                Image(systemName: "tray")
                    .font(.system(size: 28, weight: .medium))
                    .foregroundStyle(StrategyPalette.cyan)
            }
            .frame(width: 76, height: 76)

            Text("当前暂无持仓")
                .font(.title3.weight(.semibold))
                .foregroundStyle(.white)
            Text(fetchedAt.formatted(date: .omitted, time: .shortened))
                .font(.caption2)
                .foregroundStyle(StrategyPalette.secondaryText.opacity(0.7))
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 110)
    }

    private func positionCard(_ position: LivePosition) -> some View {
        VStack(alignment: .leading, spacing: 17) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 7) {
                        Text(position.displaySymbol)
                            .font(.title3.weight(.bold))
                            .foregroundStyle(.white)
                        if position.source == "manual" {
                            Text("手动")
                                .font(.caption2.weight(.semibold))
                                .foregroundStyle(StrategyPalette.cyan)
                                .padding(.horizontal, 7)
                                .padding(.vertical, 3)
                                .background(StrategyPalette.cyan.opacity(0.12), in: Capsule())
                        }
                    }
                    Text("USDT 永续")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(StrategyPalette.secondaryText)
                }
                Spacer()
                Text(position.isLong ? "做多 · \(leverageText(position))" : "做空 · \(leverageText(position))")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(position.isLong ? StrategyPalette.mint : StrategyPalette.coral)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                    .background((position.isLong ? StrategyPalette.mint : StrategyPalette.coral).opacity(0.12), in: Capsule())
            }

            VStack(alignment: .leading, spacing: 3) {
                Text("未实现盈亏")
                    .font(.caption)
                    .foregroundStyle(StrategyPalette.secondaryText)
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(currency(position.unrealizedPnL))
                        .font(.system(size: 31, weight: .bold, design: .rounded))
                    Text(percent(position.unrealizedPnLPct))
                        .font(.subheadline.weight(.semibold))
                }
                .foregroundStyle(position.unrealizedPnL >= 0 ? StrategyPalette.mint : StrategyPalette.coral)
            }

            HStack(spacing: 0) {
                valueCell("数量", position.qty.formatted(.number.precision(.fractionLength(0...4))))
                valueCell("入场价", price(position.entryPrice))
                valueCell("标记价", price(position.currentPrice))
            }

            HStack(spacing: 0) {
                valueCell("名义仓位", "$\(position.notionalUSD.formatted(.number.precision(.fractionLength(0))))")
                valueCell("保证金", money(position.initialMargin > 0 ? position.initialMargin : position.margin))
                valueCell("强平价", price(position.liquidationPrice))
            }

            Divider().overlay(StrategyPalette.hairline)

            if position.leverage >= 5 || position.stopPrice <= 0 {
                HStack(spacing: 8) {
                    Image(systemName: "exclamationmark.triangle.fill")
                    Text(position.stopPrice <= 0 ? "未检测到止损保护" : "高杠杆持仓")
                    Spacer()
                    if position.leverage >= 5 {
                        Text("\(leverageText(position))")
                    }
                }
                .font(.caption.weight(.semibold))
                .foregroundStyle(StrategyPalette.amber)
                .padding(11)
                .background(StrategyPalette.amber.opacity(0.09), in: RoundedRectangle(cornerRadius: 12))
            }

            VStack(spacing: 11) {
                riskRow("止盈", price(position.takeProfitPrice), position.distanceToTakeProfitPct, StrategyPalette.mint)
                riskRow("止损", price(position.stopPrice), position.distanceToStopPct, StrategyPalette.coral)
            }

            if let openedAt = position.openedAt {
                HStack {
                    Label("持仓时间", systemImage: "clock")
                    Spacer()
                    Text(openedAt, style: .relative)
                }
                .font(.caption2)
                .foregroundStyle(StrategyPalette.secondaryText)
            }
        }
        .padding(18)
        .background {
            TradingCardSurface(
                cornerRadius: 22,
                accent: position.unrealizedPnL >= 0 ? StrategyPalette.mint : StrategyPalette.coral
            )
        }
    }

    private func valueCell(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.caption2).foregroundStyle(StrategyPalette.secondaryText)
            Text(value)
                .font(.system(size: 13, weight: .semibold, design: .rounded))
                .foregroundStyle(.white)
                .minimumScaleFactor(0.7)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func riskRow(_ label: String, _ value: String, _ distance: Double?, _ color: Color) -> some View {
        HStack {
            Circle().fill(color).frame(width: 7, height: 7)
            Text(label).foregroundStyle(StrategyPalette.secondaryText)
            Text(value).foregroundStyle(.white)
            Spacer()
            if let distance {
                Text("距离 \(abs(distance).formatted(.number.precision(.fractionLength(2))))%")
                    .foregroundStyle(color)
            }
        }
        .font(.caption.weight(.medium))
    }

    private func leverageText(_ position: LivePosition) -> String {
        "\(position.leverage.formatted(.number.precision(.fractionLength(0))))x"
    }

    private func currency(_ value: Double) -> String {
        let sign = value >= 0 ? "+" : "−"
        return "\(sign)$\(abs(value).formatted(.number.precision(.fractionLength(2))))"
    }

    private func percent(_ value: Double) -> String {
        let sign = value >= 0 ? "+" : "−"
        return "\(sign)\(abs(value).formatted(.number.precision(.fractionLength(2))))%"
    }

    private func price(_ value: Double?) -> String {
        guard let value, value > 0 else { return "—" }
        return value.formatted(.number.precision(.fractionLength(value < 1 ? 6 : 2)))
    }

    private func money(_ value: Double) -> String {
        guard value > 0 else { return "—" }
        return "$" + value.formatted(.number.precision(.fractionLength(2)))
    }
}
