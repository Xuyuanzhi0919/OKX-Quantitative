/**
 * API配置文件
 * 统一管理所有API端点URL
 */

// API基础URL - 生产环境使用相对路径，开发环境使用localhost
export const API_BASE_URL =
  (import.meta as any).env?.VITE_API_BASE_URL ||
  ((import.meta as any).env?.DEV ? 'http://localhost:8000' : '')

// API版本前缀
const API_V1 = `${API_BASE_URL}/api/v1`

/**
 * 回测相关API端点
 */
export const BACKTEST_API = {
  // 回测管理
  list: `${API_V1}/backtest/list`,
  detail: (id: number | string) => `${API_V1}/backtest/${id}`,
  run: `${API_V1}/backtest/run`,
  delete: (id: number | string) => `${API_V1}/backtest/${id}`,
  trades: (id: number | string) => `${API_V1}/backtest/${id}/trades`,
  updateDescription: (id: number | string) => `${API_V1}/backtest/${id}/description`,

  // 策略类型
  strategyTypes: `${API_V1}/backtest/strategy-types`,
  topGainersMomentum: `${API_V1}/backtest/top-gainers-momentum/analyze`,

  // 交易对列表
  symbols: `${API_V1}/backtest/symbols`,
  symbolsDetail: `${API_V1}/backtest/symbols/detail`,

  // K线数据管理
  klines: {
    fetch: `${API_V1}/backtest/klines/fetch`,
    range: `${API_V1}/backtest/klines/range`,
    validate: `${API_V1}/backtest/klines/validate`,
    delete: `${API_V1}/backtest/klines/delete`,
  },
}

/**
 * 市场数据API端点
 */
export const MARKET_API = {
  ticker: `${API_V1}/market/ticker`,
  tickers: `${API_V1}/market/tickers`,
  orderbook: `${API_V1}/market/orderbook`,
}

/**
 * 账户相关API端点
 */
export const ACCOUNT_API = {
  balance: `${API_V1}/account/balance`,
  positions: `${API_V1}/account/positions`,
}

/**
 * 交易相关API端点
 */
export const TRADE_API = {
  createOrder: `${API_V1}/trade/order`,
  cancelOrder: (orderId: string) => `${API_V1}/trade/order/${orderId}`,
  orders: `${API_V1}/trade/orders`,
  orderDetail: (orderId: string) => `${API_V1}/trade/order/${orderId}`,
}

/**
 * 策略相关API端点
 */
export const STRATEGY_API = {
  list: `${API_V1}/strategies/list`,
  detail: (id: number | string) => `${API_V1}/strategies/${id}`,
  create: `${API_V1}/strategies/create`,
  update: (id: number | string) => `${API_V1}/strategies/${id}`,
  delete: (id: number | string) => `${API_V1}/strategies/${id}`,
  start: (id: number | string) => `${API_V1}/strategies/${id}/start`,
  stop: (id: number | string) => `${API_V1}/strategies/${id}/stop`,
  stats: (id: number | string) => `${API_V1}/strategies/${id}/stats`,
}

/**
 * 持仓相关API端点
 */
export const POSITIONS_API = {
  list: `${API_V1}/positions/list`,
  detail: (id: number | string) => `${API_V1}/positions/${id}`,
  close: (id: number | string) => `${API_V1}/positions/${id}/close`,
}

/**
 * 订单相关API端点
 */
export const ORDERS_API = {
  list: `${API_V1}/orders/list`,
  detail: (id: number | string) => `${API_V1}/orders/${id}`,
  create: `${API_V1}/orders/create`,
  cancel: (id: number | string) => `${API_V1}/orders/${id}/cancel`,
}

/**
 * 认证相关API端点
 */
export const AUTH_API = {
  login: `${API_V1}/auth/login`,
  register: `${API_V1}/auth/register`,
  logout: `${API_V1}/auth/logout`,
  refresh: `${API_V1}/auth/refresh`,
}
