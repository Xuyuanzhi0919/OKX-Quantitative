/**
 * WebSocket连接管理服务
 */
import { io, Socket } from 'socket.io-client'

export interface TickerData {
  symbol: string
  last: number
  lastSz: number
  askPx: number
  askSz: number
  bidPx: number
  bidSz: number
  open24h: number
  high24h: number
  low24h: number
  vol24h: number
  volCcy24h: number
  ts: number
}

export interface OrderBookData {
  symbol: string
  asks: [number, number][] // [price, size]
  bids: [number, number][]
  ts: number
}

export interface TradeData {
  tradeId: string
  price: number
  size: number
  side: 'buy' | 'sell'
  ts: number
}

export interface TradesData {
  symbol: string
  trades: TradeData[]
}

export interface KlineData {
  symbol: string
  bar: string // K线周期: 1m, 5m, 15m, 1H, 4H, 1D
  ts: string // 开始时间(毫秒时间戳)
  o: string // 开盘价
  h: string // 最高价
  l: string // 最低价
  c: string // 收盘价
  vol: string // 成交量(张)
  volCcy: string // 成交量(币)
  confirm: string // 0:未确认 1:已确认
}

export interface StrategyUpdateData {
  strategy_id: number
  total_profit: number
  total_trades: number
  win_rate: number
  status: string
  timestamp: number
}

export interface StrategyStatsData {
  strategy_id: number
  is_running: boolean
  position_size: number
  position_cost: number
  realized_pnl: number
  total_trades: number
  total_buy_volume: number
  total_sell_volume: number
  grid_orders: number
  signal_status?: Record<string, any>
  position_status?: Record<string, any>
  risk_status?: Record<string, any>
  health_status?: Record<string, any>
}

export interface NotificationData {
  type: 'success' | 'warning' | 'error' | 'info'
  title: string
  message: string
  strategy_id?: number
  timestamp: number
}

export interface PositionUpdateData {
  strategy_id: number
  symbol: string
  position: number
  avg_cost: number
  current_price: number
  floating_profit: number
  floating_profit_rate: number
  timestamp: number
}

export interface OrderUpdateData {
  strategy_id: number
  order_id: string
  symbol: string
  side: 'buy' | 'sell'
  type: 'limit' | 'market'
  price: number
  amount: number
  filled: number
  status: 'pending' | 'filled' | 'partially_filled' | 'cancelled' | 'failed'
  event: 'created' | 'filled' | 'partially_filled' | 'cancelled'
  message: string
  timestamp: number
}

export interface BalanceUpdateData {
  total_equity: number
  available_balance: number
  unrealized_pnl: number
  margin_ratio: number
  adjusted_equity?: number
  imr?: number
  mmr?: number
  notional_usd?: number
  details: any[]
  timestamp: number
}

export interface PositionsUpdateData {
  positions: Array<{
    pos_id?: string
    pos_side?: 'long' | 'short' | 'net'
    mgn_mode?: string
    symbol: string
    side: 'long' | 'short'
    size: number
    avg_price: number
    current_price: number
    last_price?: number
    unrealized_pnl: number
    unrealized_pnl_pct: number
    margin: number
    imr?: number
    mmr?: number
    mgn_ratio?: number
    adl?: number
    liquidation_price?: number
    leverage: number
    inst_type: string
    notional_usd?: number // OKX返回的持仓美元价值（准确值）
  }>
  total_positions: number
  total_unrealized_pnl: number
  timestamp: number
}

type TickerCallback = (data: TickerData) => void
type OrderBookCallback = (data: OrderBookData) => void
type TradesCallback = (data: TradesData) => void
type KlineCallback = (data: KlineData) => void
type StrategyUpdateCallback = (data: StrategyUpdateData) => void
type StrategyStatsCallback = (data: StrategyStatsData) => void
type PositionUpdateCallback = (data: PositionUpdateData) => void
type OrderUpdateCallback = (data: OrderUpdateData) => void
type NotificationCallback = (data: NotificationData) => void
type BalanceUpdateCallback = (data: BalanceUpdateData) => void
type PositionsUpdateCallback = (data: PositionsUpdateData) => void
type ConnectionCallback = () => void

class WebSocketService {
  private socket: Socket | null = null
  private tickerCallbacks: Map<string, Set<TickerCallback>> = new Map()
  private orderbookCallbacks: Map<string, Set<OrderBookCallback>> = new Map()
  private tradesCallbacks: Map<string, Set<TradesCallback>> = new Map()
  private klineCallbacks: Map<string, Set<KlineCallback>> = new Map() // symbol -> callbacks
  private strategyUpdateCallbacks: Set<StrategyUpdateCallback> = new Set()
  private strategyStatsCallbacks: Set<StrategyStatsCallback> = new Set()
  private positionUpdateCallbacks: Set<PositionUpdateCallback> = new Set()
  private orderUpdateCallbacks: Set<OrderUpdateCallback> = new Set()
  private singleStrategyUpdateCallbacks: Map<number, Set<StrategyUpdateCallback>> = new Map() // strategy_id -> callbacks
  private singleStrategyStatsCallbacks: Map<number, Set<StrategyStatsCallback>> = new Map()
  private singlePositionUpdateCallbacks: Map<number, Set<PositionUpdateCallback>> = new Map()
  private singleOrderUpdateCallbacks: Map<number, Set<OrderUpdateCallback>> = new Map()
  private notificationCallbacks: Set<NotificationCallback> = new Set()
  private balanceUpdateCallbacks: Set<BalanceUpdateCallback> = new Set()
  private positionsUpdateCallbacks: Set<PositionsUpdateCallback> = new Set()
  private connectCallbacks: Set<ConnectionCallback> = new Set()
  private disconnectCallbacks: Set<ConnectionCallback> = new Set()
  private subscribedSymbols: Set<string> = new Set()
  private subscribedToAllStrategies: boolean = false
  private subscribedStrategies: Set<number> = new Set()

  /**
   * 连接到WebSocket服务器
   */
  connect(url?: string): void {
    if (this.socket?.connected) {
      return
    }

    // 如果没有提供URL，则根据环境判断
    // 生产环境使用相对路径(空字符串)，开发环境使用localhost:8000
    const targetUrl = url || ((import.meta as any).env?.DEV ? 'http://localhost:8000' : '')

    this.socket = io(targetUrl, {
      transports: ['polling', 'websocket'], // 先尝试polling，再升级到websocket
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionAttempts: 10,
      path: '/socket.io/', // 明确指定路径
    })

    this.setupEventListeners()
  }

  /**
   * 设置事件监听器
   */
  private setupEventListeners(): void {
    if (!this.socket) return

    this.socket.on('connect', () => {
      this.connectCallbacks.forEach((cb) => cb())

      // 重新订阅之前订阅的交易对
      this.subscribedSymbols.forEach((symbol) => {
        this.subscribe(symbol)
      })

      // 重新订阅策略更新
      if (this.subscribedToAllStrategies) {
        this.subscribeAllStrategies()
      }

      // 重新订阅单个策略
      this.subscribedStrategies.forEach((strategy_id) => {
        this.subscribeStrategy(strategy_id)
      })
    })

    this.socket.on('disconnect', () => {
      this.disconnectCallbacks.forEach((cb) => cb())
    })

    this.socket.on('error', (error: any) => {
      // WebSocket错误处理
    })

    // Ticker数据
    this.socket.on('ticker', (data: TickerData) => {
      const callbacks = this.tickerCallbacks.get(data.symbol)
      callbacks?.forEach((cb) => cb(data))
    })

    // 订单簿数据
    this.socket.on('orderbook', (data: OrderBookData) => {
      const callbacks = this.orderbookCallbacks.get(data.symbol)
      callbacks?.forEach((cb) => cb(data))
    })

    // 成交记录数据
    this.socket.on('trades', (data: TradesData) => {
      const callbacks = this.tradesCallbacks.get(data.symbol)
      callbacks?.forEach((cb) => cb(data))
    })

    // K线数据
    this.socket.on('kline', (data: KlineData) => {
      const callbacks = this.klineCallbacks.get(data.symbol)
      callbacks?.forEach((cb) => cb(data))
    })

    // 策略状态更新
    this.socket.on('strategy_update', (data: StrategyUpdateData) => {
      // 触发全局监听器
      this.strategyUpdateCallbacks.forEach((cb) => cb(data))
      // 触发单个策略监听器
      const singleCallbacks = this.singleStrategyUpdateCallbacks.get(data.strategy_id)
      singleCallbacks?.forEach((cb) => cb(data))
    })

    // 策略统计数据
    this.socket.on('strategy_stats', (data: StrategyStatsData) => {
      // 触发全局监听器
      this.strategyStatsCallbacks.forEach((cb) => cb(data))
      // 触发单个策略监听器
      const singleCallbacks = this.singleStrategyStatsCallbacks.get(data.strategy_id)
      singleCallbacks?.forEach((cb) => cb(data))
    })

    // 持仓更新
    this.socket.on('position_update', (data: PositionUpdateData) => {
      // 触发全局监听器
      this.positionUpdateCallbacks.forEach((cb) => cb(data))
      // 触发单个策略监听器
      const singleCallbacks = this.singlePositionUpdateCallbacks.get(data.strategy_id)
      singleCallbacks?.forEach((cb) => cb(data))
    })

    // 订单更新
    this.socket.on('order_update', (data: OrderUpdateData) => {
      // 触发全局监听器
      this.orderUpdateCallbacks.forEach((cb) => cb(data))
      // 触发单个策略监听器
      const singleCallbacks = this.singleOrderUpdateCallbacks.get(data.strategy_id)
      singleCallbacks?.forEach((cb) => cb(data))
    })

    this.socket.on('subscribed', (data: { symbol: string }) => {
      // 订阅成功处理
    })

    this.socket.on('unsubscribed', (data: { symbol: string }) => {
      // 取消订阅处理
    })

    this.socket.on('subscribed_strategies', () => {
      // 策略订阅成功
    })

    this.socket.on('unsubscribed_strategies', () => {
      // 策略取消订阅
    })

    // 账户余额更新
    this.socket.on('balance_update', (data: BalanceUpdateData) => {
      this.balanceUpdateCallbacks.forEach((cb) => cb(data))
    })

    // 全局持仓列表更新
    this.socket.on('positions_update', (data: PositionsUpdateData) => {
      this.positionsUpdateCallbacks.forEach((cb) => cb(data))
    })

    // 系统通知
    this.socket.on('notification', (data: NotificationData) => {
      this.notificationCallbacks.forEach((cb) => cb(data))
    })
  }

  /**
   * 订阅交易对
   */
  subscribe(symbol: string): void {
    if (!this.socket?.connected) {
      this.subscribedSymbols.add(symbol)
      return
    }

    this.socket.emit('subscribe', { symbol })
    this.subscribedSymbols.add(symbol)
  }

  /**
   * 取消订阅交易对
   */
  unsubscribe(symbol: string): void {
    if (!this.socket?.connected) {
      this.subscribedSymbols.delete(symbol)
      return
    }

    this.socket.emit('unsubscribe', { symbol })
    this.subscribedSymbols.delete(symbol)

    // 清理回调
    this.tickerCallbacks.delete(symbol)
    this.orderbookCallbacks.delete(symbol)
    this.tradesCallbacks.delete(symbol)
    this.klineCallbacks.delete(symbol)
  }

  /**
   * 监听Ticker数据
   */
  onTicker(symbol: string, callback: TickerCallback): () => void {
    if (!this.tickerCallbacks.has(symbol)) {
      this.tickerCallbacks.set(symbol, new Set())
    }
    this.tickerCallbacks.get(symbol)!.add(callback)

    // 返回取消监听函数
    return () => {
      const callbacks = this.tickerCallbacks.get(symbol)
      callbacks?.delete(callback)
      if (callbacks?.size === 0) {
        this.tickerCallbacks.delete(symbol)
      }
    }
  }

  /**
   * 监听订单簿数据
   */
  onOrderBook(symbol: string, callback: OrderBookCallback): () => void {
    if (!this.orderbookCallbacks.has(symbol)) {
      this.orderbookCallbacks.set(symbol, new Set())
    }
    this.orderbookCallbacks.get(symbol)!.add(callback)

    return () => {
      const callbacks = this.orderbookCallbacks.get(symbol)
      callbacks?.delete(callback)
      if (callbacks?.size === 0) {
        this.orderbookCallbacks.delete(symbol)
      }
    }
  }

  /**
   * 监听成交记录数据
   */
  onTrades(symbol: string, callback: TradesCallback): () => void {
    if (!this.tradesCallbacks.has(symbol)) {
      this.tradesCallbacks.set(symbol, new Set())
    }
    this.tradesCallbacks.get(symbol)!.add(callback)

    return () => {
      const callbacks = this.tradesCallbacks.get(symbol)
      callbacks?.delete(callback)
      if (callbacks?.size === 0) {
        this.tradesCallbacks.delete(symbol)
      }
    }
  }

  /**
   * 监听K线数据
   */
  onKline(symbol: string, callback: KlineCallback): () => void {
    if (!this.klineCallbacks.has(symbol)) {
      this.klineCallbacks.set(symbol, new Set())
    }
    this.klineCallbacks.get(symbol)!.add(callback)

    return () => {
      const callbacks = this.klineCallbacks.get(symbol)
      callbacks?.delete(callback)
      if (callbacks?.size === 0) {
        this.klineCallbacks.delete(symbol)
      }
    }
  }

  /**
   * 监听连接事件
   */
  onConnect(callback: ConnectionCallback): () => void {
    this.connectCallbacks.add(callback)
    return () => this.connectCallbacks.delete(callback)
  }

  /**
   * 监听断开事件
   */
  onDisconnect(callback: ConnectionCallback): () => void {
    this.disconnectCallbacks.add(callback)
    return () => this.disconnectCallbacks.delete(callback)
  }

  /**
   * 断开连接
   */
  disconnect(): void {
    this.socket?.disconnect()
    this.socket = null
    this.subscribedSymbols.clear()
  }

  /**
   * 获取连接状态
   */
  isConnected(): boolean {
    return this.socket?.connected || false
  }

  /**
   * 订阅所有策略更新
   */
  subscribeAllStrategies(): void {
    if (!this.socket?.connected) {
      this.subscribedToAllStrategies = true
      return
    }

    this.socket.emit('subscribe_strategies')
    this.subscribedToAllStrategies = true
  }

  /**
   * 取消订阅所有策略
   */
  unsubscribeAllStrategies(): void {
    if (!this.socket?.connected) {
      this.subscribedToAllStrategies = false
      return
    }

    this.socket.emit('unsubscribe_strategies')
    this.subscribedToAllStrategies = false
    this.strategyUpdateCallbacks.clear()
    this.strategyStatsCallbacks.clear()
  }

  /**
   * 监听策略状态更新
   */
  onStrategyUpdate(callback: StrategyUpdateCallback): () => void {
    this.strategyUpdateCallbacks.add(callback)

    return () => {
      this.strategyUpdateCallbacks.delete(callback)
    }
  }

  /**
   * 监听策略统计数据
   */
  onStrategyStats(callback: StrategyStatsCallback): () => void {
    this.strategyStatsCallbacks.add(callback)

    return () => {
      this.strategyStatsCallbacks.delete(callback)
    }
  }

  /**
   * 订阅单个策略
   */
  subscribeStrategy(strategy_id: number): void {
    if (!this.socket?.connected) {
      this.subscribedStrategies.add(strategy_id)
      return
    }

    this.socket.emit('subscribe_strategy', { strategy_id })
    this.subscribedStrategies.add(strategy_id)
  }

  /**
   * 取消订阅单个策略
   */
  unsubscribeStrategy(strategy_id: number): void {
    if (!this.socket?.connected) {
      this.subscribedStrategies.delete(strategy_id)
      return
    }

    this.socket.emit('unsubscribe_strategy', { strategy_id })
    this.subscribedStrategies.delete(strategy_id)

    // 清理回调
    this.singleStrategyUpdateCallbacks.delete(strategy_id)
    this.singleStrategyStatsCallbacks.delete(strategy_id)
  }

  /**
   * 监听单个策略状态更新
   */
  onSingleStrategyUpdate(strategy_id: number, callback: StrategyUpdateCallback): () => void {
    if (!this.singleStrategyUpdateCallbacks.has(strategy_id)) {
      this.singleStrategyUpdateCallbacks.set(strategy_id, new Set())
    }
    this.singleStrategyUpdateCallbacks.get(strategy_id)!.add(callback)

    return () => {
      const callbacks = this.singleStrategyUpdateCallbacks.get(strategy_id)
      callbacks?.delete(callback)
      if (callbacks?.size === 0) {
        this.singleStrategyUpdateCallbacks.delete(strategy_id)
      }
    }
  }

  /**
   * 监听单个策略统计数据
   */
  onSingleStrategyStats(strategy_id: number, callback: StrategyStatsCallback): () => void {
    if (!this.singleStrategyStatsCallbacks.has(strategy_id)) {
      this.singleStrategyStatsCallbacks.set(strategy_id, new Set())
    }
    this.singleStrategyStatsCallbacks.get(strategy_id)!.add(callback)

    return () => {
      const callbacks = this.singleStrategyStatsCallbacks.get(strategy_id)
      callbacks?.delete(callback)
      if (callbacks?.size === 0) {
        this.singleStrategyStatsCallbacks.delete(strategy_id)
      }
    }
  }

  /**
   * 监听系统通知
   */
  onNotification(callback: NotificationCallback): () => void {
    this.notificationCallbacks.add(callback)

    return () => {
      this.notificationCallbacks.delete(callback)
    }
  }

  /**
   * 监听持仓更新
   */
  onPositionUpdate(callback: PositionUpdateCallback): () => void {
    this.positionUpdateCallbacks.add(callback)

    return () => {
      this.positionUpdateCallbacks.delete(callback)
    }
  }

  /**
   * 监听单个策略持仓更新
   */
  onSinglePositionUpdate(strategy_id: number, callback: PositionUpdateCallback): () => void {
    if (!this.singlePositionUpdateCallbacks.has(strategy_id)) {
      this.singlePositionUpdateCallbacks.set(strategy_id, new Set())
    }
    this.singlePositionUpdateCallbacks.get(strategy_id)!.add(callback)

    return () => {
      const callbacks = this.singlePositionUpdateCallbacks.get(strategy_id)
      callbacks?.delete(callback)
      if (callbacks?.size === 0) {
        this.singlePositionUpdateCallbacks.delete(strategy_id)
      }
    }
  }

  /**
   * 监听订单更新
   */
  onOrderUpdate(callback: OrderUpdateCallback): () => void {
    this.orderUpdateCallbacks.add(callback)

    return () => {
      this.orderUpdateCallbacks.delete(callback)
    }
  }

  /**
   * 监听单个策略订单更新
   */
  onSingleOrderUpdate(strategy_id: number, callback: OrderUpdateCallback): () => void {
    if (!this.singleOrderUpdateCallbacks.has(strategy_id)) {
      this.singleOrderUpdateCallbacks.set(strategy_id, new Set())
    }
    this.singleOrderUpdateCallbacks.get(strategy_id)!.add(callback)

    return () => {
      const callbacks = this.singleOrderUpdateCallbacks.get(strategy_id)
      callbacks?.delete(callback)
      if (callbacks?.size === 0) {
        this.singleOrderUpdateCallbacks.delete(strategy_id)
      }
    }
  }

  /**
   * 监听账户余额更新
   */
  onBalanceUpdate(callback: BalanceUpdateCallback): () => void {
    this.balanceUpdateCallbacks.add(callback)

    return () => {
      this.balanceUpdateCallbacks.delete(callback)
    }
  }

  /**
   * 监听全局持仓列表更新
   */
  onPositionsUpdate(callback: PositionsUpdateCallback): () => void {
    this.positionsUpdateCallbacks.add(callback)

    return () => {
      this.positionsUpdateCallbacks.delete(callback)
    }
  }
}

// 导出单例
export const wsService = new WebSocketService()
