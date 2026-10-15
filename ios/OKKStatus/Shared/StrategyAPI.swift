import Foundation

enum OKKConfiguration {
    static let serverURL = URL(string: "http://43.155.213.45:8088")!

    static var readToken: String {
        let value = Bundle.main.object(forInfoDictionaryKey: "MobileReadToken") as? String ?? ""
        return value.hasPrefix("$(") ? "" : value.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

enum StrategyAPIError: LocalizedError {
    case invalidResponse
    case serverStatus(Int)
    case missingToken
    case unauthorized

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "服务器返回了无效数据"
        case .serverStatus(let code):
            return "服务器请求失败（HTTP \(code)）"
        case .missingToken:
            return "移动端只读令牌尚未配置"
        case .unauthorized:
            return "只读令牌无效或已过期"
        }
    }
}

struct StrategyAPI {
    private let decoder = JSONDecoder()

    func fetchSnapshot() async throws -> StrategySnapshot {
        let response: MobileSnapshotResponse = try await request(
            path: "/api/v1/strategies/mobile/current-snapshot"
        )
        let statsResult = response.stats
        let pnlResult = response.pnl

        return StrategySnapshot(
            strategyID: response.strategy.id,
            strategyName: response.strategy.name,
            account: response.account,
            isRunning: statsResult.isRunning,
            totalPnL: pnlResult.totalPnL,
            unrealizedPnL: pnlResult.unrealizedPnL,
            totalTrades: pnlResult.totalTrades,
            winRate: pnlResult.winRate,
            accountOpenPositions: pnlResult.openPositions,
            strategyOpenPositions: pnlResult.strategyOpenPositions ?? 0,
            currentNotionalUSD: statsResult.positionStatus?.currentNotionalUSD ?? 0,
            signalMessage: statsResult.signalStatus?.message ?? "等待策略状态",
            candidate: statsResult.signalStatus?.candidates?.first,
            positions: statsResult.positionStatus?.positions ?? [],
            fetchedAt: .now
        )
    }

    private func request<T: Decodable>(path: String) async throws -> T {
        let url = OKKConfiguration.serverURL.appending(path: path)
        var request = URLRequest(url: url)
        request.timeoutInterval = 12
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        guard !OKKConfiguration.readToken.isEmpty else {
            throw StrategyAPIError.missingToken
        }
        request.setValue("Bearer \(OKKConfiguration.readToken)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw StrategyAPIError.invalidResponse
        }
        if httpResponse.statusCode == 401 {
            throw StrategyAPIError.unauthorized
        }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw StrategyAPIError.serverStatus(httpResponse.statusCode)
        }
        return try decoder.decode(T.self, from: data)
    }
}
