import SwiftUI

@MainActor
final class StrategyViewModel: ObservableObject {
    @Published var snapshot = StrategySnapshot.placeholder
    @Published var isLoading = false
    @Published var errorMessage: String?

    func refresh(showLoading: Bool = true) async {
        if showLoading { isLoading = true }
        defer {
            if showLoading { isLoading = false }
        }
        do {
            snapshot = try await StrategyAPI().fetchSnapshot()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func startAutoRefresh() async {
        await refresh(showLoading: true)
        while !Task.isCancelled {
            do {
                try await Task.sleep(for: .seconds(20))
            } catch {
                break
            }
            guard !Task.isCancelled else { break }
            await refresh(showLoading: false)
        }
    }
}

struct ContentView: View {
    @StateObject private var viewModel = StrategyViewModel()

    var body: some View {
        TabView {
            NavigationStack {
                AccountOverviewView(viewModel: viewModel)
            }
            .tabItem { Label("首页", systemImage: "house.fill") }

            NavigationStack {
                RunningStrategiesView(viewModel: viewModel)
            }
            .tabItem { Label("策略", systemImage: "waveform.path.ecg") }

            NavigationStack {
                PositionDetailView(viewModel: viewModel)
            }
            .tabItem { Label("持仓", systemImage: "briefcase.fill") }
        }
        .tint(StrategyPalette.cyan)
        .preferredColorScheme(.dark)
        .task { await viewModel.startAutoRefresh() }
    }
}

struct AccountOverviewView: View {
    @ObservedObject var viewModel: StrategyViewModel

    private var snapshot: StrategySnapshot { viewModel.snapshot }
    private var account: AccountSummary { snapshot.account }

    var body: some View {
        ZStack {
            StrategyPalette.ink.ignoresSafeArea()
            ambientGlow

            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    accountHero
                    if !riskNotices.isEmpty {
                        riskOverview
                    }
                    pnlOverview
                    runningStrategies

                    if let errorMessage = viewModel.errorMessage {
                        errorBanner(errorMessage)
                    }
                }
                .padding(.horizontal, 18)
                .padding(.top, 8)
                .padding(.bottom, 28)
            }
            .refreshable { await viewModel.refresh(showLoading: true) }
        }
        .navigationTitle("总览")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarColorScheme(.dark, for: .navigationBar)
        .toolbarBackground(StrategyPalette.ink.opacity(0.92), for: .navigationBar)
    }

    private var ambientGlow: some View {
        GeometryReader { proxy in
            ZStack {
                Circle()
                    .fill(StrategyPalette.coral.opacity(0.18))
                    .frame(width: 260, height: 260)
                    .blur(radius: 90)
                    .offset(x: proxy.size.width * 0.55, y: -170)
                Circle()
                    .fill(StrategyPalette.mint.opacity(0.10))
                    .frame(width: 250, height: 250)
                    .blur(radius: 100)
                    .offset(x: -proxy.size.width * 0.52, y: 130)
            }
        }
        .allowsHitTesting(false)
    }

    private var accountHero: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Label("实盘账户", systemImage: "shield.lefthalf.filled")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.white.opacity(0.82))
                Spacer()
                livePill
            }

            VStack(alignment: .leading, spacing: 4) {
                Text("总资产")
                    .font(.subheadline)
                    .foregroundStyle(.white.opacity(0.60))
                Text(money(account.totalEquity))
                    .font(.system(size: 45, weight: .bold, design: .rounded))
                    .foregroundStyle(.white)
                    .minimumScaleFactor(0.62)
                    .lineLimit(1)
            }

            HStack(spacing: 0) {
                heroMetric("可用余额", money(account.availableBalance))
                divider
                heroMetric("占用保证金", money(account.initialMargin))
                divider
                heroMetric("账户持仓", "\(snapshot.accountOpenPositions) · \(compactMoney(account.positionNotionalUSD))")
            }

            HStack {
                Image(systemName: "dot.radiowaves.left.and.right")
                Spacer()
                Text(snapshot.fetchedAt.formatted(date: .omitted, time: .standard))
            }
            .font(.caption2.weight(.medium))
            .foregroundStyle(.white.opacity(0.48))
        }
        .padding(20)
        .background {
            ZStack {
                RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .fill(Color(red: 0.035, green: 0.037, blue: 0.041))
                Circle()
                    .fill(StrategyPalette.coral.opacity(0.19))
                    .frame(width: 190, height: 190)
                    .blur(radius: 52)
                    .offset(x: 145, y: -115)
                Circle()
                    .fill(StrategyPalette.mint.opacity(0.12))
                    .frame(width: 170, height: 170)
                    .blur(radius: 58)
                    .offset(x: -155, y: 125)
            }
            .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
        }
        .overlay {
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .stroke(StrategyPalette.hairline, lineWidth: 1)
        }
        .shadow(color: .black.opacity(0.30), radius: 24, y: 14)
    }

    private var pnlOverview: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionHeader("资产盈亏", icon: "chart.line.uptrend.xyaxis")

            HStack(spacing: 12) {
                pnlCard(
                    title: "策略累计",
                    value: snapshot.totalPnL,
                    icon: "sum"
                )
                pnlCard(
                    title: "账户浮盈",
                    value: account.unrealizedPnL,
                    icon: "arrow.up.and.down"
                )
            }
        }
    }

    private var runningStrategies: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                sectionHeader("运行策略", icon: "bolt.horizontal.fill")
                Spacer()
                Circle()
                    .fill(snapshot.isRunning ? StrategyPalette.mint : .orange)
                    .frame(width: 8, height: 8)
            }

            NavigationLink {
                StrategyDetailView(viewModel: viewModel)
            } label: {
                strategyRow
            }
            .buttonStyle(.plain)
        }
    }

    private var strategyRow: some View {
        VStack(alignment: .leading, spacing: 17) {
            HStack(spacing: 13) {
                ZStack {
                    RoundedRectangle(cornerRadius: 13, style: .continuous)
                        .fill(StrategyPalette.cyan.opacity(0.13))
                    Image(systemName: "chart.line.uptrend.xyaxis")
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(StrategyPalette.cyan)
                }
                .frame(width: 48, height: 48)

                VStack(alignment: .leading, spacing: 4) {
                    Text(snapshot.strategyName)
                        .font(.headline)
                        .foregroundStyle(.white)
                    Text("1H · 3x")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(StrategyPalette.secondaryText)
                }

                Spacer()
                livePill
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(StrategyPalette.secondaryText)
            }

            HStack(spacing: 0) {
                strategyMetric("累计收益", signedMoney(snapshot.totalPnL), pnlColor(snapshot.totalPnL))
                strategyMetric("策略持仓", "\(snapshot.strategyOpenPositions)", .white)
                strategyMetric("胜率", percent(snapshot.winRate), .white)
            }

        }
        .padding(18)
        .background {
            TradingCardSurface(cornerRadius: 23, accent: StrategyPalette.violet)
        }
    }

    private var livePill: some View {
        HStack(spacing: 6) {
            Circle().fill(StrategyPalette.mint).frame(width: 7, height: 7)
            Text(snapshot.isRunning ? "运行" : "停止")
        }
        .font(.system(size: 10, weight: .bold, design: .rounded))
        .tracking(0.8)
        .foregroundStyle(.white.opacity(0.84))
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background((snapshot.isRunning ? StrategyPalette.mint : StrategyPalette.amber).opacity(0.11), in: Capsule())
    }

    private var divider: some View {
        Rectangle().fill(.white.opacity(0.12)).frame(width: 1, height: 34)
    }

    private func heroMetric(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(.white.opacity(0.48))
            Text(value)
                .font(.system(size: 13, weight: .semibold, design: .rounded))
                .foregroundStyle(.white.opacity(0.90))
                .minimumScaleFactor(0.7)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func pnlCard(title: String, value: Double, icon: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: icon)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(pnlColor(value))
                Spacer()
                Circle().fill(pnlColor(value)).frame(width: 6, height: 6)
            }
            Text(title)
                .font(.caption)
                .foregroundStyle(StrategyPalette.secondaryText)
            Text(signedMoney(value))
                .font(.system(size: 25, weight: .bold, design: .rounded))
                .foregroundStyle(pnlColor(value))
                .minimumScaleFactor(0.72)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(StrategyPalette.raised, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .stroke(pnlColor(value).opacity(0.13), lineWidth: 1)
        }
    }

    private func strategyMetric(_ title: String, _ value: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.caption2).foregroundStyle(StrategyPalette.secondaryText)
            Text(value)
                .font(.system(size: 15, weight: .bold, design: .rounded))
                .foregroundStyle(color)
                .minimumScaleFactor(0.72)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func errorBanner(_ message: String) -> some View {
        Label(message, systemImage: "wifi.exclamationmark")
            .font(.footnote)
            .foregroundStyle(.orange)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(14)
            .background(.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 16))
    }

    private var riskNotices: [String] {
        var notices: [String] = []
        let usage = account.totalEquity > 0 ? account.initialMargin / account.totalEquity : 0
        if usage >= 0.5 {
            notices.append("保证金占总资产 \((usage * 100).formatted(.number.precision(.fractionLength(0))))%")
        }
        if account.totalEquity > 0 && account.availableBalance / account.totalEquity < 0.1 {
            notices.append("可用余额低于总资产 10%")
        }
        if snapshot.positions.contains(where: { $0.leverage >= 5 }) {
            notices.append("存在 5x 以上高杠杆持仓")
        }
        if snapshot.positions.contains(where: { $0.stopPrice <= 0 }) {
            notices.append("移动端未检测到止损保护")
        }
        return notices
    }

    private var riskOverview: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("风险提醒", systemImage: "exclamationmark.shield.fill")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(StrategyPalette.amber)
            ForEach(riskNotices, id: \.self) { notice in
                HStack(spacing: 8) {
                    Circle().fill(StrategyPalette.amber).frame(width: 5, height: 5)
                    Text(notice)
                }
                .font(.caption)
                .foregroundStyle(.white.opacity(0.78))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(StrategyPalette.amber.opacity(0.08), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(StrategyPalette.amber.opacity(0.22), lineWidth: 1)
        }
    }
}

struct RunningStrategiesView: View {
    @ObservedObject var viewModel: StrategyViewModel

    var body: some View {
        ZStack {
            TradingBackdrop()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    NavigationLink {
                        StrategyDetailView(viewModel: viewModel)
                    } label: {
                        StrategyCardView(snapshot: viewModel.snapshot)
                            .frame(height: 188)
                            .background { TradingCardSurface(cornerRadius: 24, accent: StrategyPalette.violet) }
                    }
                    .buttonStyle(.plain)
                }
                .padding(18)
            }
            .refreshable { await viewModel.refresh(showLoading: true) }
        }
        .navigationTitle("策略")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarColorScheme(.dark, for: .navigationBar)
    }
}

struct StrategyDetailView: View {
    @ObservedObject var viewModel: StrategyViewModel

    private var snapshot: StrategySnapshot { viewModel.snapshot }

    var body: some View {
        ZStack {
            TradingBackdrop()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    StrategyCardView(snapshot: snapshot)
                        .frame(height: 210)
                        .background { TradingCardSurface(cornerRadius: 24, accent: StrategyPalette.violet) }

                    detailSection("运行指标", icon: "gauge.with.dots.needle.67percent") {
                        HStack(spacing: 10) {
                            detailMetric("策略持仓", "\(snapshot.strategyOpenPositions)")
                            detailMetric("交易", "\(snapshot.totalTrades)")
                            detailMetric("胜率", percent(snapshot.winRate))
                        }
                    }

                    detailSection("信号监控", icon: "waveform.path.ecg") {
                        HStack(spacing: 13) {
                            Image(systemName: snapshot.candidate == nil ? "waveform.path" : "bolt.fill")
                                .foregroundStyle(StrategyPalette.cyan)
                                .frame(width: 42, height: 42)
                                .background(StrategyPalette.cyan.opacity(0.12), in: Circle())
                            VStack(alignment: .leading, spacing: 4) {
                                Text(snapshot.candidate == nil ? "正在扫描市场" : "发现候选信号")
                                    .font(.subheadline.weight(.semibold))
                                    .foregroundStyle(.white)
                                Text(snapshot.signalMessage)
                                    .font(.caption)
                                    .foregroundStyle(StrategyPalette.secondaryText)
                                    .lineLimit(2)
                            }
                            Spacer()
                        }
                        .padding(16)
                        .background { TradingCardSurface(cornerRadius: 18, accent: StrategyPalette.cyan) }
                    }

                    NavigationLink {
                        PositionDetailView(viewModel: viewModel)
                    } label: {
                        Label("查看实盘持仓", systemImage: "briefcase.fill")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 15)
                            .background(StrategyPalette.cyan.opacity(0.15), in: RoundedRectangle(cornerRadius: 16))
                            .overlay {
                                RoundedRectangle(cornerRadius: 16, style: .continuous)
                                    .stroke(StrategyPalette.cyan.opacity(0.35), lineWidth: 1)
                            }
                    }
                }
                .padding(18)
                .padding(.bottom, 20)
            }
        }
        .navigationTitle(snapshot.strategyName)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarColorScheme(.dark, for: .navigationBar)
    }

    private func detailSection<Content: View>(
        _ title: String,
        icon: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 13) {
            sectionHeader(title, icon: icon)
            content()
        }
    }

    private func detailMetric(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(value)
                .font(.system(size: 23, weight: .bold, design: .rounded))
                .foregroundStyle(.white)
            Text(title)
                .font(.caption2)
                .foregroundStyle(StrategyPalette.secondaryText)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(15)
        .background { TradingCardSurface(cornerRadius: 17, accent: StrategyPalette.violet) }
    }
}

private func sectionHeader(_ title: String, icon: String) -> some View {
    Label(title, systemImage: icon)
        .font(.headline)
        .foregroundStyle(.white.opacity(0.92))
}

private func pnlColor(_ value: Double) -> Color {
    value >= 0 ? StrategyPalette.mint : StrategyPalette.coral
}

private func money(_ value: Double) -> String {
    "$" + value.formatted(.number.precision(.fractionLength(2)))
}

private func compactMoney(_ value: Double) -> String {
    "$" + value.formatted(.number.notation(.compactName).precision(.fractionLength(1)))
}

private func signedMoney(_ value: Double) -> String {
    let sign = value >= 0 ? "+" : "−"
    return sign + "$" + abs(value).formatted(.number.precision(.fractionLength(2)))
}

private func percent(_ value: Double) -> String {
    value.formatted(.number.precision(.fractionLength(0))) + "%"
}

#Preview {
    ContentView()
}
