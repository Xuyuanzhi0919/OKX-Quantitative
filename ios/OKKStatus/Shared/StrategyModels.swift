import Foundation

struct StrategyStats: Decodable {
    let strategyID: Int
    let isRunning: Bool
    let realizedPnL: Double?
    let totalTrades: Int?
    let signalStatus: SignalStatus?
    let positionStatus: PositionStatus?

    enum CodingKeys: String, CodingKey {
        case strategyID = "strategy_id"
        case isRunning = "is_running"
        case realizedPnL = "realized_pnl"
        case totalTrades = "total_trades"
        case signalStatus = "signal_status"
        case positionStatus = "position_status"
    }
}

struct StrategyPnL: Decodable {
    let totalPnL: Double
    let realizedPnL: Double
    let unrealizedPnL: Double
    let totalTrades: Int
    let winRate: Double
    let openPositions: Int
    let strategyOpenPositions: Int?

    enum CodingKeys: String, CodingKey {
        case totalPnL = "total_pnl"
        case realizedPnL = "realized_pnl"
        case unrealizedPnL = "unrealized_pnl"
        case totalTrades = "total_trades"
        case winRate = "win_rate"
        case openPositions = "open_positions"
        case strategyOpenPositions = "strategy_open_positions"
    }
}

struct MobileSnapshotResponse: Decodable {
    let strategy: MobileStrategySummary
    let account: AccountSummary
    let stats: StrategyStats
    let pnl: StrategyPnL
}

struct MobileStrategySummary: Decodable {
    let id: Int
    let name: String
    let status: String
}

struct AccountSummary: Decodable {
    let totalEquity: Double
    let availableBalance: Double
    let cashBalance: Double
    let unrealizedPnL: Double
    let initialMargin: Double
    let positionNotionalUSD: Double

    enum CodingKeys: String, CodingKey {
        case totalEquity = "total_equity"
        case availableBalance = "available_balance"
        case cashBalance = "cash_balance"
        case unrealizedPnL = "unrealized_pnl"
        case initialMargin = "initial_margin"
        case positionNotionalUSD = "position_notional_usd"
    }
}

struct SignalStatus: Decodable {
    let message: String?
    let minSignal: Double?
    let marketFilter: String?
    let takeProfitPct: Double?
    let candidates: [SignalCandidate]?

    enum CodingKeys: String, CodingKey {
        case message
        case minSignal = "min_signal"
        case marketFilter = "market_filter"
        case takeProfitPct = "take_profit_pct"
        case candidates
    }
}

struct SignalCandidate: Decodable {
    let symbol: String?
    let score: Double?
    let volumeRatio: Double?

    enum CodingKeys: String, CodingKey {
        case symbol, score
        case volumeRatio = "vol_ratio"
    }
}

struct PositionStatus: Decodable {
    let openPositions: Int?
    let currentNotionalUSD: Double?
    let positions: [LivePosition]?

    enum CodingKeys: String, CodingKey {
        case openPositions = "open_positions"
        case currentNotionalUSD = "current_notional_usd"
        case positions
    }
}

struct LivePosition: Decodable, Identifiable {
    let symbol: String
    let side: String
    let qty: Double
    let entryPrice: Double
    let currentPrice: Double
    let stopPrice: Double
    let takeProfitPrice: Double?
    let openTime: Double
    let leverage: Double
    let notionalUSD: Double
    let unrealizedPnL: Double
    let unrealizedPnLPct: Double
    let distanceToStopPct: Double?
    let distanceToTakeProfitPct: Double?
    let source: String
    let margin: Double
    let initialMargin: Double
    let liquidationPrice: Double?

    var id: String { "\(symbol)-\(side)" }
    var displaySymbol: String { symbol.replacingOccurrences(of: "-USDT-SWAP", with: "") }
    var isLong: Bool { side.lowercased() != "short" }
    var openedAt: Date? { openTime > 0 ? Date(timeIntervalSince1970: openTime) : nil }

    enum CodingKeys: String, CodingKey {
        case symbol, side, qty, leverage
        case entryPrice = "entry_price"
        case currentPrice = "current_price"
        case stopPrice = "stop_px"
        case takeProfitPrice = "take_profit_px"
        case openTime = "open_time"
        case notionalUSD = "notional_usd"
        case unrealizedPnL = "unrealized_pnl"
        case unrealizedPnLPct = "unrealized_pnl_pct"
        case distanceToStopPct = "distance_to_stop_pct"
        case distanceToTakeProfitPct = "distance_to_take_profit_pct"
        case source
        case margin
        case initialMargin = "initial_margin"
        case liquidationPrice = "liquidation_price"
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        symbol = try values.decodeIfPresent(String.self, forKey: .symbol) ?? "UNKNOWN"
        side = try values.decodeIfPresent(String.self, forKey: .side) ?? "long"
        qty = try values.decodeIfPresent(Double.self, forKey: .qty) ?? 0
        entryPrice = try values.decodeIfPresent(Double.self, forKey: .entryPrice) ?? 0
        currentPrice = try values.decodeIfPresent(Double.self, forKey: .currentPrice) ?? entryPrice
        stopPrice = try values.decodeIfPresent(Double.self, forKey: .stopPrice) ?? 0
        takeProfitPrice = try values.decodeIfPresent(Double.self, forKey: .takeProfitPrice)
        openTime = try values.decodeIfPresent(Double.self, forKey: .openTime) ?? 0
        leverage = try values.decodeIfPresent(Double.self, forKey: .leverage) ?? 0
        notionalUSD = try values.decodeIfPresent(Double.self, forKey: .notionalUSD) ?? 0
        unrealizedPnL = try values.decodeIfPresent(Double.self, forKey: .unrealizedPnL) ?? 0
        unrealizedPnLPct = try values.decodeIfPresent(Double.self, forKey: .unrealizedPnLPct) ?? 0
        distanceToStopPct = try values.decodeIfPresent(Double.self, forKey: .distanceToStopPct)
        distanceToTakeProfitPct = try values.decodeIfPresent(Double.self, forKey: .distanceToTakeProfitPct)
        source = try values.decodeIfPresent(String.self, forKey: .source) ?? "strategy"
        margin = try values.decodeIfPresent(Double.self, forKey: .margin) ?? 0
        initialMargin = try values.decodeIfPresent(Double.self, forKey: .initialMargin) ?? margin
        liquidationPrice = try values.decodeIfPresent(Double.self, forKey: .liquidationPrice)
    }
}

struct StrategySnapshot {
    let strategyID: Int
    let strategyName: String
    let account: AccountSummary
    let isRunning: Bool
    let totalPnL: Double
    let unrealizedPnL: Double
    let totalTrades: Int
    let winRate: Double
    let accountOpenPositions: Int
    let strategyOpenPositions: Int
    let currentNotionalUSD: Double
    let signalMessage: String
    let candidate: SignalCandidate?
    let positions: [LivePosition]
    let fetchedAt: Date

    static let placeholder = StrategySnapshot(
        strategyID: 0,
        strategyName: "爆量急拉追涨",
        account: AccountSummary(
            totalEquity: 0,
            availableBalance: 0,
            cashBalance: 0,
            unrealizedPnL: 0,
            initialMargin: 0,
            positionNotionalUSD: 0
        ),
        isRunning: true,
        totalPnL: 29.67,
        unrealizedPnL: 0,
        totalTrades: 1,
        winRate: 100,
        accountOpenPositions: 0,
        strategyOpenPositions: 0,
        currentNotionalUSD: 0,
        signalMessage: "等待下一根1H K线",
        candidate: nil,
        positions: [],
        fetchedAt: .now
    )
}
