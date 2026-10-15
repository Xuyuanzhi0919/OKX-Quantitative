/**
 * 通用类型定义
 */

// 策略状态
export enum StrategyStatus {
  STOPPED = 'stopped',
  RUNNING = 'running',
  PAUSED = 'paused',
  ERROR = 'error',
}

// 订单方向
export enum OrderSide {
  BUY = 'buy',
  SELL = 'sell',
}

// 订单类型
export enum OrderType {
  LIMIT = 'limit',
  MARKET = 'market',
  STOP_LIMIT = 'stop_limit',
  STOP_MARKET = 'stop_market',
}

// 订单状态
export enum OrderStatus {
  PENDING = 'pending',
  SUBMITTED = 'submitted',
  PARTIAL_FILLED = 'partial_filled',
  FILLED = 'filled',
  CANCELED = 'canceled',
  FAILED = 'failed',
}

// 策略接口
export interface Strategy {
  id: number
  api_config_id?: number
  name: string
  type: string
  status: StrategyStatus
  symbol: string
  timeframe?: string
  parameters: Record<string, any>
  total_profit: number
  total_trades: number
  win_rate: number
  created_at: string
  updated_at?: string
}

// 订单接口
export interface Order {
  id: number
  order_id: string
  symbol: string
  side: OrderSide
  order_type: OrderType
  status: OrderStatus
  price?: number
  amount: number
  filled_amount: number
  avg_price?: number
  fee: number
  fee_currency?: string
  created_at: string
  submitted_at?: string
  filled_at?: string
  canceled_at?: string
  note?: string
}

// 持仓接口
export interface Position {
  id: number
  symbol: string
  amount: number
  available_amount: number
  avg_price: number
  total_cost: number
  unrealized_pnl: number
  realized_pnl: number
}

// K线数据
export interface Kline {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

// 实时行情 (OKX API格式)
export interface Ticker {
  instType?: string
  instId?: string
  last?: string
  lastSz?: string
  askPx?: string
  askSz?: string
  bidPx?: string
  bidSz?: string
  open24h?: string
  high24h?: string
  low24h?: string
  volCcy24h?: string
  vol24h?: string
  sodUtc0?: string
  sodUtc8?: string
  ts?: string
}

export interface TopAltcoinStrategyCandidate {
  symbol: string
  base_ccy: string
  last: number
  open24h: number
  high24h: number
  low24h: number
  volume_usdt: number
  change_pct: number
  analysis: {
    decision: 'long' | 'short' | 'wait'
    confidence: number
    risk_level: 'low' | 'medium' | 'high'
    reasoning: string
    suggested_strategy?: string | null
    scores?: {
      long_score: number
      short_score: number
      wait_score: number
    }
  }
  recommended_strategy: {
    type: string
    label: string
    direction: 'long' | 'short' | 'both'
    timeframe: string
    parameters: Record<string, any>
  }
}

// 交易产品信息 (OKX API格式)
export interface Instrument {
  instType: string // 产品类型: SPOT/SWAP/FUTURES/OPTION
  instId: string // 产品ID: BTC-USDT
  uly?: string // 标的指数
  baseCcy?: string // 交易货币: BTC
  quoteCcy?: string // 计价货币: USDT
  settCcy?: string // 盈亏结算和保证金币种
  ctVal?: string // 合约面值
  ctMult?: string // 合约乘数
  ctValCcy?: string // 合约面值计价币种
  minSz: string // 最小下单量
  maxSz?: string // 最大下单量
  lotSz: string // 下单量精度
  tickSz: string // 下单价格精度
  listTime?: string // 上线时间
  expTime?: string // 到期日期
  lever?: string // 杠杆倍数
  state: string // 产品状态: live/suspend/preopen
  category?: string // 产品类别
}

// 用户信息
export interface User {
  id: number
  username: string
  email?: string
  is_active: boolean
}

// API响应
export interface ApiResponse<T = any> {
  data?: T
  message?: string
  error?: string
}

// 网格参数推荐
export interface GridParamsRecommendation {
  symbol: string
  current_price: number
  price_upper: number
  price_lower: number
  grid_num: number
  total_amount: number
  amount_per_grid: number
  min_order_size: number
  size_per_grid: number
  grid_step: number
  profit_per_grid_percent: number
  price_range_percent: number
  risk_assessment: {
    max_drawdown_percent: number
    estimated_daily_trades: number
    estimated_daily_profit: number
    risk_level: string
  }
  recommendations: string[]
}

// 策略性能统计
export interface StrategyPerformance {
  strategy_id: number
  total_profit: number // 总盈亏
  total_profit_rate: number // 总收益率(%)
  realized_profit: number // 已实现盈亏
  unrealized_profit: number // 未实现盈亏
  total_trades: number // 总交易次数
  total_orders?: number // 总订单次数
  in_position?: boolean // 是否当前持仓中
  position_side?: string // 当前持仓方向
  successful_trades: number // 成功交易次数
  failed_trades: number // 失败交易次数
  win_rate: number // 胜率(%)
  total_fee: number // 总手续费
  max_drawdown: number // 最大回撤
  profit_history: ProfitHistoryItem[] // 盈亏历史
  daily_profits: DailyProfit[] // 每日盈亏
}

export interface StrategyEvent {
  id: number
  strategy_id: number
  event_type: string
  level: 'info' | 'warning' | 'error' | 'success' | string
  title: string
  message?: string
  data?: Record<string, any>
  parameter_snapshot?: Record<string, any>
  created_at?: string
}

export interface ProfitHistoryItem {
  timestamp: string
  profit: number
  cumulative_profit: number
}

export interface DailyProfit {
  date: string
  profit: number
}

// 告警类型
export enum AlertType {
  STOP_LOSS = 'stop_loss',
  TAKE_PROFIT = 'take_profit',
  RISK_WARNING = 'risk_warning',
  SYSTEM_ERROR = 'system_error',
}

// 告警严重级别
export enum AlertSeverity {
  INFO = 'info',
  WARNING = 'warning',
  ERROR = 'error',
  SUCCESS = 'success',
}

// 告警接口
export interface Alert {
  id: number
  user_id: number
  strategy_id?: number
  alert_type: AlertType
  severity: AlertSeverity
  title: string
  message: string
  data?: string // JSON字符串
  is_read: boolean
  is_handled: boolean
  created_at: string
  handled_at?: string
}
