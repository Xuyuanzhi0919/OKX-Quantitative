/**
 * API服务
 */
import axios from 'axios'
import type { AxiosInstance, AxiosRequestConfig } from 'axios'
import type {
  Strategy,
  StrategyEvent,
  Order,
  Position,
  Ticker,
  Kline,
  Instrument,
  StrategyPerformance,
  User,
  TopAltcoinStrategyCandidate,
} from '@/types'

type ApiClient = Omit<AxiosInstance, 'get' | 'post' | 'put' | 'delete'> & {
  get<T = any>(url: string, config?: AxiosRequestConfig): Promise<T>
  post<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T>
  put<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T>
  delete<T = any>(url: string, config?: AxiosRequestConfig): Promise<T>
}

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 10000,
}) as ApiClient

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    // TODO: 添加token
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  },
)

// 响应拦截器
api.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    if (
      error?.response?.status === 401 &&
      !String(error?.config?.url || '').includes('/auth/login')
    ) {
      localStorage.removeItem('token')
      if (window.location.pathname !== '/login') {
        window.location.assign('/login')
      }
    }
    return Promise.reject(error)
  },
)

// 认证API
export const authApi = {
  login: (username: string, password: string) =>
    api.post<{ access_token: string; token_type: string; user: User }>('/auth/login', {
      username,
      password,
    }),
  register: (username: string, email: string, password: string) =>
    api.post<User>('/auth/register', { username, email, password }),
  getCurrentUser: () => api.get<User>('/auth/me'),
}

// 策略API
export const strategyApi = {
  getList: () => api.get<{ total: number; items: Strategy[] }>('/strategies/'),
  getById: (id: number) => api.get<Strategy>(`/strategies/${id}`),
  create: (data: Partial<Strategy>) => api.post('/strategies', data),
  update: (id: number, data: Partial<Strategy>) => api.put(`/strategies/${id}`, data),
  delete: (id: number) => api.delete(`/strategies/${id}`),
  start: (id: number, forceStart: boolean = false) =>
    api.post(`/strategies/${id}/start`, null, { params: { force_start: forceStart } }),
  startPreflight: (id: number) =>
    api
      .get<{ code: number; msg: string; data: any }>(`/strategies/${id}/start-preflight`)
      .then((res) => (res as any).data),
  stop: (id: number, cancelOrders: boolean = true, closePosition: boolean = true) =>
    api.post(`/strategies/${id}/stop`, null, {
      params: { cancel_orders: cancelOrders, close_position: closePosition },
    }),
  getStats: (id: number) => api.get(`/strategies/${id}/stats`),
  getOrders: (id: number, skip?: number, limit?: number) =>
    api
      .get<{
        code: number
        msg: string
        data: { total: number; items: Order[] }
      }>(`/strategies/${id}/orders`, { params: { skip, limit } })
      .then((res) => (res as any).data),
  getEvents: (id: number, skip?: number, limit?: number) =>
    api
      .get<{
        code: number
        msg: string
        data: { total: number; items: StrategyEvent[] }
      }>(`/strategies/${id}/events`, { params: { skip, limit } })
      .then((res) => (res as any).data),
  getPerformance: (id: number) =>
    api
      .get<{
        code: number
        msg: string
        data: StrategyPerformance
      }>(`/strategies/${id}/performance`)
      .then((res) => (res as any).data),
  getAdaptiveGridTrendRecommendation: () =>
    api.get('/strategies/adaptive-grid-trend/recommendation'),
  backtest: (id: number, params: any) => api.post(`/strategies/${id}/backtest`, params),
  getPnl: (id: number) => api.get(`/strategies/${id}/pnl`),
}

export const safetyApi = {
  emergencyStop: (data: {
    action: 'pause_all' | 'close_all'
    strategy_ids?: number[]
    cancel_orders?: boolean
    close_positions?: boolean
  }) => api.post('/risk-control/emergency-stop', data),
}

// 订单API
export const orderApi = {
  getList: (params?: {
    symbol?: string
    status?: string
    side?: string
    strategy_id?: number
    limit?: number
  }) => api.get<Order[]>('/orders/list', { params }).then((res) => (res as any).data || res),
  getById: (id: string) => api.get<Order>(`/orders/${id}`),

  // 创建订单 (新实现)
  create: (data: {
    symbol: string
    side: 'buy' | 'sell'
    order_type: 'market' | 'limit' | 'post_only' | 'fok' | 'ioc'
    amount: number
    price?: number
    td_mode?: 'cash' | 'isolated' | 'cross'
    cl_ord_id?: string
    pos_side?: 'long' | 'short' | 'net'
    reduce_only?: boolean
    tgt_ccy?: 'base_ccy' | 'quote_ccy'
  }) =>
    api
      .post<{ code: number; msg: string; data: any }>('/orders/create', data)
      .then((res) => res.data),

  // 取消订单 (新实现)
  cancel: (symbol: string, orderId?: string, clOrdId?: string) =>
    api
      .post<{ code: number; msg: string; data: any }>('/orders/cancel', {
        symbol,
        order_id: orderId,
        cl_ord_id: clOrdId,
      })
      .then((res) => res.data),

  // 查询订单详情 (新实现)
  getDetail: (symbol: string, orderId?: string, clOrdId?: string) =>
    api
      .post<{ code: number; msg: string; data: any }>('/orders/detail', {
        symbol,
        order_id: orderId,
        cl_ord_id: clOrdId,
      })
      .then((res) => res.data),
}

// 持仓API
export const positionApi = {
  getList: () => api.get<Position[]>('/positions'),
  getBySymbol: (symbol: string) => api.get<Position>(`/positions/${symbol}`),
}

// 行情API
export const marketApi = {
  getTicker: (symbol: string) =>
    api
      .get<{ code: number; msg: string; data: Ticker }>(`/market/ticker/${symbol}`)
      .then((res) => (res as any).data as Ticker),

  getKline: (
    symbol: string,
    timeframe: string = '1m',
    limit: number = 100,
    after?: string,
    before?: string,
  ) =>
    api
      .get<{ code: number; msg: string; data: Kline[] }>(`/market/kline/${symbol}`, {
        params: { timeframe, limit, after, before },
      })
      .then((res) => (res as any).data as Kline[]),

  getOrderbook: (symbol: string, depth: number = 20) =>
    api
      .get<{ code: number; msg: string; data: any }>(`/market/orderbook/${symbol}`, {
        params: { depth },
      })
      .then((res) => (res as any).data),

  // 获取交易产品列表
  getInstruments: (params?: {
    inst_type?: 'SPOT' | 'SWAP' | 'FUTURES' | 'OPTION'
    uly?: string
    inst_id?: string
    quote_ccy?: string
  }) =>
    api
      .get<{ code: number; msg: string; data: Instrument[] }>('/market/instruments', {
        params: {
          inst_type: params?.inst_type || 'SPOT',
          uly: params?.uly,
          inst_id: params?.inst_id,
          quote_ccy: params?.quote_ccy,
        },
      })
      .then((res) => (res as any).data as Instrument[]),
}

// 账户API (新增)
export const accountApi = {
  getBalance: (ccy?: string) =>
    api
      .get<{ code: number; msg: string; data: any }>('/positions/balance', {
        params: { ccy },
      })
      .then((res) => (res as any).data),

  // 后端直接返回数组，拦截器已提取 response.data，无需再取 .data
  getPositions: (instType?: string, instId?: string, posId?: string) =>
    api.get<Position[]>('/positions/list', {
      params: {
        inst_type: instType,
        inst_id: instId,
        pos_id: posId,
      },
    }),

  // 获取账户净值历史快照（用于计算最大回撤）
  getAccountSnapshots: (days: number = 7) =>
    api
      .get<{
        code: number
        msg: string
        data: {
          snapshots: Array<{
            total_equity: number
            available_balance: number
            unrealized_pnl: number
            timestamp: string
          }>
          max_drawdown: number
          max_drawdown_pct: number
          days: number
          count: number
        }
      }>('/positions/account-snapshots', { params: { days } })
      .then((res) => (res as any).data),

  // 获取今日盈亏基线（UTC+8 自然日 0:00 重置）
  getDailyPnlBaseline: () =>
    api
      .get<{
        code: number
        msg: string
        data: {
          baseline_equity: number | null
          baseline_time: string | null
          has_baseline: boolean
        }
      }>('/positions/daily-pnl')
      .then((res) => (res as any).data),
}

// 告警API
export const alertApi = {
  // 获取告警列表
  getList: (params?: {
    skip?: number
    limit?: number
    strategy_id?: number
    alert_type?: 'stop_loss' | 'take_profit' | 'risk_warning' | 'system_error'
    severity?: 'info' | 'warning' | 'error' | 'success'
    is_read?: boolean
  }) =>
    api
      .get<{
        code: number
        msg: string
        data: { total: number; alerts: any[] }
      }>('/alerts/list', { params })
      .then((res) => (res as any).data),

  // 获取未读告警数量
  getUnreadCount: () =>
    api
      .get<{ code: number; msg: string; data: { count: number } }>('/alerts/unread-count')
      .then((res) => (res as any).data),

  // 标记单个告警为已读
  markRead: (id: number) =>
    api.post<{ code: number; msg: string }>(`/alerts/${id}/mark-read`).then((res) => res as any),

  // 标记所有告警为已读
  markAllRead: () =>
    api
      .post<{ code: number; msg: string; data: { count: number } }>('/alerts/mark-all-read')
      .then((res) => (res as any).data),

  // 标记告警为已处理
  handleAlert: (id: number) =>
    api.post<{ code: number; msg: string }>(`/alerts/${id}/handle`).then((res) => res as any),

  // 删除告警
  delete: (id: number) =>
    api.delete<{ code: number; msg: string }>(`/alerts/${id}`).then((res) => res as any),
}

// AI分析API
export const aiApi = {
  // 市场分析
  analyze: (symbol: string, detailed: boolean = false) =>
    api.post<{
      symbol: string
      timestamp: string
      decision: 'long' | 'short' | 'wait'
      confidence: number
      scores: {
        long_score: number
        short_score: number
        wait_score: number
      }
      factors: any
      risk_level: 'low' | 'medium' | 'high'
      suggested_strategy: string | null
      reasoning: string
    }>('/ai/analyze', { symbol, detailed }),

  // 批量分析
  analyzeBatch: (symbols: string[]) => api.post('/ai/analyze/batch', symbols),

  analyzeTopAltcoinStrategies: (params?: {
    limit?: number
    inst_type?: 'SPOT' | 'SWAP'
    quote_ccy?: string
    min_volume_usdt?: number
    exclude_majors?: boolean
  }) =>
    api
      .post<{
        code: number
        msg: string
        data: { items: TopAltcoinStrategyCandidate[]; universe_count: number; ai_enabled: boolean }
      }>('/ai/top-altcoin-strategies', {
        limit: params?.limit ?? 5,
        inst_type: params?.inst_type ?? 'SWAP',
        quote_ccy: params?.quote_ccy ?? 'USDT',
        min_volume_usdt: params?.min_volume_usdt ?? 1000000,
        exclude_majors: params?.exclude_majors ?? true,
      })
      .then((res) => (res as any).data),

  analyzeStealthAltcoinStrategies: (params?: {
    limit?: number
    inst_type?: 'SPOT' | 'SWAP'
    quote_ccy?: string
    min_volume_usdt?: number
    min_range_pct?: number
    max_range_pct?: number
    min_change_pct?: number
    max_change_pct?: number
    trend_timeframe?: string
    trend_lookback?: number
    max_lookback_drop_pct?: number
    min_ma_gap_pct?: number
    max_recent_position?: number
    exclude_majors?: boolean
  }) =>
    api
      .post<{
        code: number
        msg: string
        data: { items: TopAltcoinStrategyCandidate[]; universe_count: number; ai_enabled: boolean }
      }>('/ai/stealth-altcoin-strategies', {
        limit: params?.limit ?? 5,
        inst_type: params?.inst_type ?? 'SWAP',
        quote_ccy: params?.quote_ccy ?? 'USDT',
        min_volume_usdt: params?.min_volume_usdt ?? 3000000,
        min_range_pct: params?.min_range_pct ?? 3,
        max_range_pct: params?.max_range_pct ?? 12,
        min_change_pct: params?.min_change_pct ?? -8,
        max_change_pct: params?.max_change_pct ?? 8,
        trend_timeframe: params?.trend_timeframe ?? '15m',
        trend_lookback: params?.trend_lookback ?? 192,
        max_lookback_drop_pct: params?.max_lookback_drop_pct ?? 10,
        min_ma_gap_pct: params?.min_ma_gap_pct ?? -2,
        max_recent_position: params?.max_recent_position ?? 0.75,
        exclude_majors: params?.exclude_majors ?? true,
      })
      .then((res) => (res as any).data),

  // AI配置管理
  getConfigList: () => api.get<any[]>('/ai-configs/list'),

  createConfig: (data: { name: string; provider: string; api_key: string; model: string }) =>
    api.post('/ai-configs/create', data),

  updateConfig: (
    id: number,
    data: {
      name?: string
      api_key?: string
      model?: string
      is_active?: boolean
    },
  ) => api.put(`/ai-configs/update/${id}`, data),

  deleteConfig: (id: number) => api.delete(`/ai-configs/delete/${id}`),

  activateConfig: (id: number) => api.post(`/ai-configs/activate/${id}`),

  getActiveConfig: () => api.get<any>('/ai-configs/active'),
}

export default api
