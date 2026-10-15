import { useEffect, useRef, useState } from 'react'
import { Row, Col, Card, Table, Spin, Button, Statistic, Progress, Tag, Tooltip, App } from 'antd'
import {
  TrendingUp,
  TrendingDown,
  RefreshCw,
  DollarSign,
  Wifi,
  Clock,
  ShieldAlert,
  Activity,
  BarChart2,
  AlertTriangle,
} from 'lucide-react'
import type { ColumnsType } from 'antd/es/table'
import { accountApi, marketApi, strategyApi, orderApi } from '@/services/api'
import {
  wsService,
  StrategyUpdateData,
  StrategyStatsData,
  OrderUpdateData,
  BalanceUpdateData,
  PositionsUpdateData,
} from '@/services/websocket'
import { useTranslation } from 'react-i18next'
import { formatPrice, formatQuantityDisplay, formatAmount, formatPercent } from '@/utils/format'

// ── 本地缓存（解决路由切换/刷新后数据闪烁：挂载时立即还原上次数据）──
const CACHE_KEY = 'okk_dashboard_v1'
const CACHE_TTL = 5 * 60 * 1000 // 5分钟过期

const safeNumber = (value: any, fallback = 0): number => {
  if (value === undefined || value === null || value === '') return fallback
  const parsed = typeof value === 'number' ? value : parseFloat(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const estimateInitialMargin = (notionalUsd: number, leverage: number, margin: number): number => {
  if (notionalUsd > 0 && leverage > 0) return notionalUsd / leverage
  return margin
}

const readCache = (): Record<string, any> | null => {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (Date.now() - (parsed.ts ?? 0) > CACHE_TTL) {
      localStorage.removeItem(CACHE_KEY)
      return null
    }
    return parsed
  } catch {
    return null
  }
}

const writeCache = (data: Record<string, any>) => {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({ ...data, ts: Date.now() }))
  } catch {}
}

const Dashboard = () => {
  const { t } = useTranslation()
  const { message } = App.useApp()

  // 首次渲染时读缓存，作为所有 state 的初始值（只调用一次）
  const [cache] = useState<Record<string, any> | null>(() => readCache())

  // 有缓存则直接跳过 loading，用缓存数据初始化 state
  const [loading, setLoading] = useState(!cache)
  const hasLoadedRef = useRef(!!cache)

  const [balance, setBalance] = useState<any>(cache?.balance ?? null)
  const [positionsWithPrice, setPositionsWithPrice] = useState<any[]>(cache?.positions ?? [])
  const [runningStrategies, setRunningStrategies] = useState<any[]>(cache?.strategies ?? [])
  const runningStrategiesRef = useRef<any[]>(cache?.strategies ?? [])
  const [recentOrders, setRecentOrders] = useState<any[]>(cache?.recentOrders ?? [])

  const [refreshing, setRefreshing] = useState(false)
  const [wsConnected, setWsConnected] = useState(false)
  const [lastUpdateTime, setLastUpdateTime] = useState<Date>(new Date())
  const [currentTime, setCurrentTime] = useState<Date>(new Date())

  // 风险指标（也从缓存初始化）
  const [marginRatio, setMarginRatio] = useState<number>(cache?.marginRatio ?? 0)
  const [accountImr, setAccountImr] = useState<number>(cache?.accountImr ?? 0)
  const [accountMmr, setAccountMmr] = useState<number>(cache?.accountMmr ?? 0)
  const [accountAdjEq, setAccountAdjEq] = useState<number>(cache?.accountAdjEq ?? 0)
  const [accountNotionalUsd, setAccountNotionalUsd] = useState<number>(
    cache?.accountNotionalUsd ?? 0,
  )
  const [dailyPnlBaseline, setDailyPnlBaseline] = useState<number | null>(
    cache?.dailyPnlBaseline ?? null,
  )
  const [maxDrawdown, setMaxDrawdown] = useState<number>(cache?.maxDrawdown ?? 0)
  const [maxDrawdownPct, setMaxDrawdownPct] = useState<number>(cache?.maxDrawdownPct ?? 0)

  // 格式化相对时间
  const getRelativeTime = (date: Date): string => {
    const seconds = Math.floor((currentTime.getTime() - date.getTime()) / 1000)
    if (seconds < 5) return '刚刚'
    if (seconds < 60) return `${seconds}秒前`
    const minutes = Math.floor(seconds / 60)
    if (minutes < 60) return `${minutes}分钟前`
    const hours = Math.floor(minutes / 60)
    if (hours < 24) return `${hours}小时前`
    return `${Math.floor(hours / 24)}天前`
  }

  // 同步更新 runningStrategies state 和 ref，保证 WS 闭包始终读到最新值
  const setRunningStrategiesWithRef = (strategies: any[]) => {
    runningStrategiesRef.current = strategies
    setRunningStrategies(strategies)
  }

  // 首次加载前显示全屏 Spinner；首次成功后所有刷新均为透明后台更新
  const fetchDashboardData = async () => {
    try {
      if (!hasLoadedRef.current) setLoading(true)
      else setRefreshing(true)

      // 并行获取余额、持仓、策略、最近订单、今日基线、最大回撤
      const [balanceData, positionsData, strategiesData, ordersData, dailyPnlData, snapshotsData] =
        await Promise.all([
          accountApi.getBalance().catch(() => null),
          accountApi.getPositions().catch(() => []),
          strategyApi.getList().catch(() => ({ items: [] })),
          orderApi.getList({ status: 'filled', limit: 10 }).catch(() => []),
          accountApi.getDailyPnlBaseline().catch(() => null),
          accountApi.getAccountSnapshots(7).catch(() => null),
        ])

      // ── 计算派生值（在所有 async 工作完成前，不调用任何 setState）──

      // OKX mgnRatio 是 adjEq / mmr，数值越大越安全，不是风险百分比。
      let newMarginRatio = 0
      if (balanceData?.mgnRatio) newMarginRatio = safeNumber(balanceData.mgnRatio)
      const newAccountImr = safeNumber(balanceData?.imr)
      const newAccountMmr = safeNumber(balanceData?.mmr)
      const newAccountAdjEq = safeNumber(balanceData?.adjEq)
      const newAccountNotionalUsd = safeNumber(balanceData?.notionalUsd)

      // 今日盈亏基线
      const newDailyPnlBaseline: number | null =
        dailyPnlData?.has_baseline && dailyPnlData.baseline_equity != null
          ? dailyPnlData.baseline_equity
          : null

      // 最大回撤（限制在 100% 以内，防止异常快照数据导致显示异常）
      const newMaxDrawdown = snapshotsData?.max_drawdown || 0
      const newMaxDrawdownPct = Math.min(100, snapshotsData?.max_drawdown_pct || 0)

      // 从余额数据提取现货余额
      const spotBalances: any[] = []
      if (balanceData?.details) {
        for (const detail of balanceData.details) {
          const eqUsd = parseFloat(detail.eqUsd || '0')
          if (eqUsd > 0.5 && detail.ccy !== 'USDT') {
            spotBalances.push({
              ccy: detail.ccy,
              eq: parseFloat(detail.eq || '0'),
              eqUsd,
              accAvgPx: parseFloat(detail.accAvgPx || '0'),
              spotUpl: parseFloat(detail.spotUpl || '0'),
            })
          }
        }
      }

      // 现货价格需要 ticker；合约持仓直接使用 OKX positions 返回的 markPx/notionalUsd。
      const posArr = Array.isArray(positionsData) ? positionsData : []

      const [spotResults, contractResults] = await Promise.all([
        // 现货：并行获取所有 ticker
        Promise.all(
          spotBalances.map(async (bal: any) => {
            try {
              const symbol = `${bal.ccy}-USDT`
              const ticker = await marketApi.getTicker(symbol)
              const currentPrice = parseFloat((ticker as any)?.last || '0')
              return {
                key: `spot-${bal.ccy}`,
                type: 'SPOT',
                symbol,
                amount: bal.eq,
                avgPrice: bal.accAvgPx > 0 ? bal.accAvgPx : currentPrice,
                currentPrice,
                profit: bal.spotUpl,
                profitPercent: bal.eqUsd > 0 ? (bal.spotUpl / bal.eqUsd) * 100 : 0,
                value: bal.eqUsd,
                margin: 0,
              }
            } catch {
              return {
                key: `spot-${bal.ccy}`,
                type: 'SPOT',
                symbol: `${bal.ccy}-USDT`,
                amount: bal.eq,
                avgPrice: bal.accAvgPx || 0,
                currentPrice: 0,
                profit: bal.spotUpl,
                profitPercent: 0,
                value: bal.eqUsd,
                margin: 0,
              }
            }
          }),
        ),
        // 合约：使用 positions 返回的标记价，避免逐仓位额外请求 ticker
        Promise.all(
          posArr.map(async (pos: any) => {
            try {
              const posData = pos as any
              const symbol = posData.symbol || posData.instId
              const currentPrice = safeNumber(
                posData.current_price || posData.markPx || posData.last_price || posData.last,
              )
              const posSize = safeNumber(posData.size ?? posData.pos)
              const posSide = posData.pos_side || posData.posSide || posData.side
              const value = safeNumber(
                posData.notional_usd || posData.notionalUsd,
                posSize * currentPrice,
              )
              const leverage = safeNumber(posData.leverage || posData.lever)
              const margin = safeNumber(posData.margin)
              const imr = safeNumber(posData.imr)
              return {
                key: `contract-${posData.pos_id || posData.posId || `${symbol}-${posSide || 'net'}`}`,
                type: 'SWAP',
                side: posSide === 'short' ? 'short' : 'long',
                symbol,
                amount: posSize,
                avgPrice: posData.avg_price || parseFloat(posData.avgPx || '0'),
                currentPrice,
                profit: posData.unrealized_pnl || parseFloat(posData.upl || '0'),
                profitPercent:
                  posData.unrealized_pnl_pct || parseFloat(posData.uplRatio || '0') * 100,
                // 优先用 notional_usd（OKX 准确持仓价值），否则 size*price（张数≠币数时不准）
                value,
                margin,
                imr: imr > 0 ? imr : estimateInitialMargin(value, leverage, margin),
                mmr: safeNumber(posData.mmr),
                mgnRatio: posData.mgn_ratio || posData.mgnRatio || 0,
                leverage,
                posId: posData.pos_id || posData.posId,
                posSide: posSide,
                mgnMode: posData.mgn_mode || posData.mgnMode,
              }
            } catch {
              return null
            }
          }),
        ).then((results) => results.filter(Boolean)),
      ])

      const allStrategies = (strategiesData as any)?.items || []
      const running = allStrategies.filter((s: any) => s.status === 'running')
      const orders = Array.isArray(ordersData) ? ordersData : []

      // ── 所有异步工作完成，一次性批量更新 state（React 18 自动合并为单次渲染）──
      // 仅当主要数据（balance）获取成功时才更新，避免 API 失败时清空已有数据
      if (balanceData !== null) {
        const newPositions = [...spotResults, ...(contractResults as any[])]
        const newOrders = orders.slice(0, 10)

        setBalance(balanceData)
        setMarginRatio(newMarginRatio)
        setAccountImr(newAccountImr)
        setAccountMmr(newAccountMmr)
        setAccountAdjEq(newAccountAdjEq)
        setAccountNotionalUsd(newAccountNotionalUsd)
        setDailyPnlBaseline(newDailyPnlBaseline)
        setMaxDrawdown(newMaxDrawdown)
        setMaxDrawdownPct(newMaxDrawdownPct)
        setPositionsWithPrice(newPositions)
        setRunningStrategiesWithRef(running)
        setRecentOrders(newOrders)
        hasLoadedRef.current = true

        // 写入缓存，下次挂载时立即还原，消除空数据闪烁
        writeCache({
          balance: balanceData,
          positions: newPositions,
          strategies: running,
          recentOrders: newOrders,
          marginRatio: newMarginRatio,
          accountImr: newAccountImr,
          accountMmr: newAccountMmr,
          accountAdjEq: newAccountAdjEq,
          accountNotionalUsd: newAccountNotionalUsd,
          dailyPnlBaseline: newDailyPnlBaseline,
          maxDrawdown: newMaxDrawdown,
          maxDrawdownPct: newMaxDrawdownPct,
        })
      }
    } catch (error) {
      message.error((error as Error).message || t('dashboard.fetchDataFailed'))
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    fetchDashboardData()
    // 定时刷新：hasLoadedRef.current=true 后自动静默，不触发 loading
    const timer = setInterval(fetchDashboardData, 30000)

    const timeUpdateTimer = setInterval(() => {
      setCurrentTime(new Date())
    }, 1000)

    wsService.subscribeAllStrategies()
    setWsConnected(wsService.isConnected())

    const unsubscribeConnect = wsService.onConnect(() => {
      setWsConnected(true)
      setLastUpdateTime(new Date())
    })

    const unsubscribeDisconnect = wsService.onDisconnect(() => {
      setWsConnected(false)
    })

    const unsubscribeUpdate = wsService.onStrategyUpdate((data: StrategyUpdateData) => {
      setLastUpdateTime(new Date())
      setRunningStrategies((prev) =>
        prev.map((s) =>
          s.id === data.strategy_id
            ? {
                ...s,
                total_profit: data.total_profit,
                total_trades: data.total_trades,
                win_rate: data.win_rate,
              }
            : s,
        ),
      )
    })

    const unsubscribeStats = wsService.onStrategyStats((data: StrategyStatsData) => {
      setLastUpdateTime(new Date())
      setRunningStrategies((prev) =>
        prev.map((s) => (s.id === data.strategy_id ? { ...s, _realtime_stats: data } : s)),
      )
    })

    const unsubscribeOrder = wsService.onOrderUpdate((orderData: OrderUpdateData) => {
      setLastUpdateTime(new Date())
      const sideText = orderData.side === 'buy' ? '买入' : '卖出'
      const strategyName =
        runningStrategiesRef.current.find((s) => s.id === orderData.strategy_id)?.name ||
        `策略${orderData.strategy_id}`

      if (orderData.event === 'filled') {
        message.success({
          content: `[${strategyName}] ${sideText}订单已成交: ${orderData.symbol} @ ${formatPrice(orderData.price)}`,
          duration: 3,
        })
      } else if (orderData.event === 'partially_filled') {
        message.info({
          content: `[${strategyName}] ${sideText}订单部分成交: ${orderData.symbol} (${orderData.filled}/${orderData.amount})`,
          duration: 3,
        })
      }
    })

    // 监听余额更新，提取保证金率
    const unsubscribeBalance = wsService.onBalanceUpdate((data: BalanceUpdateData) => {
      setLastUpdateTime(new Date())
      setBalance({
        totalEq: data.total_equity.toString(),
        availBal: data.available_balance.toString(),
        total_upl: data.unrealized_pnl.toString(),
        adjEq: data.adjusted_equity?.toString(),
        imr: data.imr?.toString(),
        mmr: data.mmr?.toString(),
        notionalUsd: data.notional_usd?.toString(),
        details: data.details,
      })
      // OKX mgnRatio 是 adjEq / mmr，数值越大越安全。
      if (data.margin_ratio != null && isFinite(data.margin_ratio)) {
        setMarginRatio(data.margin_ratio)
      }
      setAccountAdjEq(data.adjusted_equity || 0)
      setAccountImr(data.imr || 0)
      setAccountMmr(data.mmr || 0)
      setAccountNotionalUsd(data.notional_usd || 0)
    })

    const unsubscribePositions = wsService.onPositionsUpdate(async (data: PositionsUpdateData) => {
      setLastUpdateTime(new Date())

      const contractPositions = await Promise.all(
        data.positions.map(async (pos) => {
          try {
            const currentPrice = pos.current_price || pos.last_price || 0
            // 优先使用OKX返回的notional_usd（持仓美元价值），这是准确的价值
            // 如果没有则回退到 size * currentPrice（可能不准确，因为SWAP合约张数≠币数）
            const positionValue = pos.notional_usd || pos.size * currentPrice
            const imr =
              pos.imr || estimateInitialMargin(positionValue, pos.leverage || 0, pos.margin || 0)

            return {
              key: `contract-${pos.pos_id || `${pos.symbol}-${pos.pos_side || pos.side || 'net'}`}`,
              type: pos.inst_type || 'SWAP',
              side: pos.side || (pos.size > 0 ? 'long' : 'short'),
              symbol: pos.symbol,
              amount: pos.size,
              avgPrice: pos.avg_price,
              currentPrice: currentPrice,
              profit: pos.unrealized_pnl,
              profitPercent: pos.unrealized_pnl_pct,
              value: positionValue,
              margin: pos.margin || 0,
              imr,
              mmr: pos.mmr || 0,
              mgnRatio: pos.mgn_ratio || 0,
              leverage: pos.leverage || 0,
              posId: pos.pos_id,
              posSide: pos.pos_side,
              mgnMode: pos.mgn_mode,
            }
          } catch (error) {
            const positionValue = pos.notional_usd || pos.size * pos.current_price
            const imr =
              pos.imr || estimateInitialMargin(positionValue, pos.leverage || 0, pos.margin || 0)
            return {
              key: `contract-${pos.pos_id || `${pos.symbol}-${pos.pos_side || pos.side || 'net'}`}`,
              type: pos.inst_type || 'SWAP',
              side: pos.side || (pos.size > 0 ? 'long' : 'short'),
              symbol: pos.symbol,
              amount: pos.size,
              avgPrice: pos.avg_price,
              currentPrice: pos.current_price,
              profit: pos.unrealized_pnl,
              profitPercent: pos.unrealized_pnl_pct,
              value: positionValue,
              margin: pos.margin || 0,
              imr,
              mmr: pos.mmr || 0,
              mgnRatio: pos.mgn_ratio || 0,
              leverage: pos.leverage || 0,
              posId: pos.pos_id,
              posSide: pos.pos_side,
              mgnMode: pos.mgn_mode,
            }
          }
        }),
      )

      setPositionsWithPrice((prev) => {
        const spotPositions = prev.filter((p) => p.type === 'SPOT')
        return [...spotPositions, ...contractPositions]
      })
    })

    return () => {
      clearInterval(timer)
      clearInterval(timeUpdateTimer)
      unsubscribeConnect()
      unsubscribeDisconnect()
      unsubscribeUpdate()
      unsubscribeStats()
      unsubscribeOrder()
      unsubscribeBalance()
      unsubscribePositions()
      wsService.unsubscribeAllStrategies()
    }
  }, [])

  // ─── 计算统计数据 ────────────────────────────────────────────────────────────

  const totalAssets = balance ? parseFloat(balance.totalEq || '0') : 0
  const totalUpl = positionsWithPrice.reduce((sum, pos) => sum + (pos.profit || 0), 0)
  const uplPercent = totalAssets > 0 ? (totalUpl / totalAssets) * 100 : 0
  const totalPositionValue = positionsWithPrice.reduce((sum, pos) => sum + (pos.value || 0), 0)

  // 今日净值变化 = 当前净值 - 今日基线净值。充值/划转也会影响该值。
  const dailyPnl = dailyPnlBaseline != null ? totalAssets - dailyPnlBaseline : null
  const dailyPnlPct =
    dailyPnlBaseline != null && dailyPnlBaseline > 0
      ? ((totalAssets - dailyPnlBaseline) / dailyPnlBaseline) * 100
      : null

  // 保证金占用比 = 初始保证金 / 总净值，优先使用 OKX 账户级 imr。
  const totalMarginUsed = positionsWithPrice
    .filter((p) => p.type === 'SWAP')
    .reduce((sum, pos) => {
      const imr =
        pos.imr || estimateInitialMargin(pos.value || 0, pos.leverage || 0, pos.margin || 0)
      return sum + imr
    }, 0)
  const effectiveMarginUsed = accountImr || totalMarginUsed
  const marginUsagePct = totalAssets > 0 ? (effectiveMarginUsed / totalAssets) * 100 : 0

  // 保证金风险率 = 维持保证金 / 有效保证金。OKX mgnRatio = adjEq / mmr，越大越安全。
  const effectiveAdjEq = accountAdjEq || totalAssets
  const effectiveMmr =
    accountMmr ||
    positionsWithPrice
      .filter((p) => p.type === 'SWAP')
      .reduce((sum, pos) => sum + (pos.mmr || 0), 0)
  const marginRiskPct = effectiveAdjEq > 0 ? (effectiveMmr / effectiveAdjEq) * 100 : 0

  // 账户综合杠杆 = 合约持仓总价值 / 总净值
  const calculatedContractPositionValue = positionsWithPrice
    .filter((p) => p.type === 'SWAP')
    .reduce((sum, pos) => sum + (pos.value || 0), 0)
  const contractPositionValue = accountNotionalUsd || calculatedContractPositionValue
  const accountLeverage = totalAssets > 0 ? contractPositionValue / totalAssets : 0

  // 策略总盈亏
  const totalStrategyProfit = runningStrategies.reduce((sum, s) => sum + (s.total_profit || 0), 0)

  // 风险健康度 (0–100分)
  // 扣分规则：维持保证金风险率(最多-40)、账户杠杆(最多-30)、最大回撤(最多-30)
  const riskHealth = Math.max(
    0,
    Math.min(
      100,
      (() => {
        let score = 100
        if (marginRiskPct > 0) {
          score -= Math.min(40, (marginRiskPct / 100) * 40)
        }
        if (accountLeverage > 1) {
          score -= Math.min(30, ((accountLeverage - 1) / 9) * 30)
        }
        if (maxDrawdownPct > 0) {
          score -= Math.min(30, (maxDrawdownPct / 30) * 30)
        }
        return score
      })(),
    ),
  )

  // 连续亏损 - 从运行中策略的实时统计中取最大值
  const worstLossStreak = runningStrategies.reduce<{
    count: number
    name: string
    history: number[]
  }>(
    (worst, s) => {
      const count: number = s._realtime_stats?.consecutive_losses ?? 0
      if (count > worst.count) {
        return {
          count,
          name: s.name ?? '',
          history: (s._realtime_stats?.trade_pnl_history ?? []) as number[],
        }
      }
      return worst
    },
    { count: 0, name: '', history: [] },
  )

  const getRiskHealthColor = (score: number) => {
    if (score >= 75) return '#22c55e'
    if (score >= 50) return '#f59e0b'
    return '#ef4444'
  }

  const getRiskHealthLabel = (score: number) => {
    if (score >= 75) return '健康'
    if (score >= 50) return '警惕'
    return '高风险'
  }

  // ─── Loading ─────────────────────────────────────────────────────────────────

  if (loading && !balance) {
    return (
      <div style={{ textAlign: 'center', padding: '100px 0' }}>
        <Spin size="large" tip={t('common.loading')}>
          <div style={{ minHeight: 100 }} />
        </Spin>
      </div>
    )
  }

  // ─── 持仓表格列定义 ──────────────────────────────────────────────────────────

  const positionColumns: ColumnsType<any> = [
    {
      title: '方向',
      dataIndex: 'side',
      key: 'side',
      width: 56,
      render: (side, record) => {
        if (record.type === 'SPOT') return null
        const isLong = side === 'long'
        return (
          <Tag
            style={{
              margin: 0,
              fontSize: 10,
              padding: '1px 6px',
              fontWeight: 700,
              border: 'none',
              background: isLong ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)',
              color: isLong ? '#22c55e' : '#ef4444',
            }}
          >
            {isLong ? '多' : '空'}
          </Tag>
        )
      },
    },
    {
      title: t('dashboard.type').toUpperCase(),
      dataIndex: 'type',
      key: 'type',
      width: 70,
      render: (text) => (
        <Tag
          style={{
            margin: 0,
            fontSize: 10,
            padding: '1px 6px',
            fontWeight: 600,
            border: 'none',
            background: text === 'SPOT' ? 'rgba(24, 144, 255, 0.15)' : 'rgba(245, 158, 11, 0.15)',
            color: text === 'SPOT' ? '#1890ff' : '#f59e0b',
          }}
        >
          {text}
        </Tag>
      ),
    },
    {
      title: t('dashboard.symbol').toUpperCase(),
      dataIndex: 'symbol',
      key: 'symbol',
      width: 140,
      render: (text) => <span style={{ fontWeight: 600 }}>{text}</span>,
    },
    {
      title: t('dashboard.amount').toUpperCase(),
      dataIndex: 'amount',
      key: 'amount',
      width: 120,
      align: 'right',
      render: (value, record) => (
        <span className="font-mono" style={{ fontSize: 13 }}>
          {formatQuantityDisplay(value)}
          {record.type === 'SWAP' && (
            <span style={{ fontSize: 10, color: '#737373', marginLeft: 2 }}>张</span>
          )}
        </span>
      ),
    },
    {
      title: t('dashboard.avgPrice').toUpperCase(),
      dataIndex: 'avgPrice',
      key: 'avgPrice',
      width: 130,
      align: 'right',
      render: (value) => (
        <span className="font-mono" style={{ fontSize: 13, color: '#a3a3a3' }}>
          ${formatPrice(value)}
        </span>
      ),
    },
    {
      title: t('dashboard.currentPrice').toUpperCase(),
      dataIndex: 'currentPrice',
      key: 'currentPrice',
      width: 130,
      align: 'right',
      render: (value) => (
        <span className="font-mono" style={{ fontSize: 13, fontWeight: 600 }}>
          ${formatPrice(value)}
        </span>
      ),
    },
    {
      title: t('dashboard.value').toUpperCase(),
      dataIndex: 'value',
      key: 'value',
      width: 110,
      align: 'right',
      render: (value) => (
        <span className="font-mono" style={{ fontSize: 13 }}>
          ${formatAmount(value)}
        </span>
      ),
    },
    {
      title: t('dashboard.pnl').toUpperCase(),
      key: 'profit',
      width: 150,
      align: 'right',
      render: (_, record) => {
        const isProfit = record.profit >= 0
        return (
          <div
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4 }}
          >
            {isProfit ? (
              <TrendingUp size={12} style={{ color: '#22c55e' }} />
            ) : (
              <TrendingDown size={12} style={{ color: '#ef4444' }} />
            )}
            <span
              className={`font-mono ${isProfit ? 'text-up' : 'text-down'}`}
              style={{ fontSize: 13 }}
            >
              {isProfit ? '+' : ''}
              {formatAmount(record.profit)}
            </span>
            <span
              className={`font-mono ${isProfit ? 'text-up' : 'text-down'}`}
              style={{ fontSize: 12 }}
            >
              ({record.profitPercent >= 0 ? '+' : ''}
              {formatPercent(record.profitPercent)}%)
            </span>
          </div>
        )
      },
    },
  ]

  // ─── Render ──────────────────────────────────────────────────────────────────

  return (
    <div>
      {/* ── 第一排：主要财务指标 ── */}
      <Row gutter={[16, 16]}>
        {/* 总资产 */}
        <Col xs={24} sm={12} lg={6} xl={4} xxl={4}>
          <Card variant="borderless" size="small" style={{ height: '100%' }}>
            <div style={{ marginBottom: 8 }}>
              <div className="pro-card-header">{t('dashboard.totalEquity').toUpperCase()}</div>
            </div>
            <Statistic
              value={totalAssets}
              precision={2}
              prefix="$"
              valueStyle={{ fontSize: 28, fontWeight: 700, fontFamily: 'monospace' }}
            />
            <div style={{ marginTop: 8, fontSize: 11, color: '#737373' }}>
              <DollarSign size={11} style={{ marginRight: 4 }} />
              {t('dashboard.accountTotalEquity')}
            </div>
          </Card>
        </Col>

        {/* 未实现盈亏 */}
        <Col xs={24} sm={12} lg={6} xl={5} xxl={5}>
          <Card variant="borderless" size="small" style={{ height: '100%' }}>
            <div style={{ marginBottom: 8 }}>
              <div className="pro-card-header">{t('dashboard.unrealizedPnl').toUpperCase()}</div>
            </div>
            <Statistic
              value={totalUpl}
              precision={2}
              prefix={totalUpl >= 0 ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
              valueStyle={{
                fontSize: 28,
                fontWeight: 700,
                color: totalUpl >= 0 ? '#22c55e' : '#ef4444',
                fontFamily: 'monospace',
              }}
            />
            <div style={{ marginTop: 8 }}>
              <Progress
                percent={Math.abs(uplPercent)}
                strokeColor={uplPercent >= 0 ? '#22c55e' : '#ef4444'}
                showInfo={false}
                size="small"
              />
              <div style={{ fontSize: 11, color: '#737373', marginTop: 4 }}>
                {uplPercent >= 0 ? '+' : ''}
                {formatPercent(uplPercent)}% {t('dashboard.unrealizedPnlPercent')}
              </div>
            </div>
          </Card>
        </Col>

        {/* 今日净值变化 */}
        <Col xs={24} sm={12} lg={6} xl={5} xxl={5}>
          <Card variant="borderless" size="small" style={{ height: '100%' }}>
            <div style={{ marginBottom: 8 }}>
              <div className="pro-card-header">今日净值变化</div>
            </div>
            {dailyPnl != null ? (
              <>
                <Statistic
                  value={dailyPnl}
                  precision={2}
                  prefix={dailyPnl >= 0 ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
                  valueStyle={{
                    fontSize: 28,
                    fontWeight: 700,
                    color: dailyPnl >= 0 ? '#22c55e' : '#ef4444',
                    fontFamily: 'monospace',
                  }}
                />
                <div style={{ marginTop: 8, fontSize: 11, color: '#737373' }}>
                  {dailyPnlPct != null && (
                    <span className={dailyPnlPct >= 0 ? 'text-up' : 'text-down'}>
                      {dailyPnlPct >= 0 ? '+' : ''}
                      {formatPercent(dailyPnlPct)}%
                    </span>
                  )}
                  <span style={{ marginLeft: 4 }}>自今日0:00</span>
                </div>
              </>
            ) : (
              <>
                <div
                  style={{
                    fontSize: 28,
                    fontWeight: 700,
                    fontFamily: 'monospace',
                    color: '#737373',
                  }}
                >
                  --
                </div>
                <div style={{ marginTop: 8, fontSize: 11, color: '#737373' }}>等待首次快照生成</div>
              </>
            )}
          </Card>
        </Col>

        {/* 策略总盈亏 */}
        <Col xs={24} sm={12} lg={6} xl={5} xxl={5}>
          <Card variant="borderless" size="small" style={{ height: '100%' }}>
            <div style={{ marginBottom: 8 }}>
              <div className="pro-card-header">策略总盈亏</div>
            </div>
            <Statistic
              value={totalStrategyProfit}
              precision={2}
              prefix={
                totalStrategyProfit >= 0 ? <TrendingUp size={16} /> : <TrendingDown size={16} />
              }
              valueStyle={{
                fontSize: 28,
                fontWeight: 700,
                color: totalStrategyProfit >= 0 ? '#22c55e' : '#ef4444',
                fontFamily: 'monospace',
              }}
            />
            <div style={{ marginTop: 8, fontSize: 11, color: '#737373' }}>
              {runningStrategies.length} 个策略运行中
            </div>
          </Card>
        </Col>

        {/* 持仓总价值 */}
        <Col xs={24} sm={12} lg={6} xl={5} xxl={5}>
          <Card variant="borderless" size="small" style={{ height: '100%' }}>
            <div style={{ marginBottom: 8 }}>
              <div className="pro-card-header">{t('dashboard.positionValue').toUpperCase()}</div>
            </div>
            <Statistic
              value={totalPositionValue}
              precision={2}
              prefix="$"
              valueStyle={{ fontSize: 28, fontWeight: 700, fontFamily: 'monospace' }}
            />
            <div style={{ marginTop: 8, fontSize: 11, color: '#737373' }}>
              {positionsWithPrice.length} 个持仓
            </div>
          </Card>
        </Col>
      </Row>

      {/* ── 第二排：风险 & 杠杆指标 ── */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {/* 连续亏损次数 */}
        <Col xs={24} sm={12} lg={6} xl={4} xxl={4}>
          <Tooltip title="运行中所有策略里，当前连续亏损次数最多的策略。连续亏损 ≥ 3 次需关注，≥ 5 次建议暂停检查">
            <Card variant="borderless" size="small" style={{ height: '100%' }}>
              <div style={{ marginBottom: 8 }}>
                <div
                  className="pro-card-header"
                  style={{ display: 'flex', alignItems: 'center', gap: 4 }}
                >
                  <TrendingDown size={11} />
                  连续亏损次数
                </div>
              </div>
              {runningStrategies.length > 0 ? (
                <>
                  <div
                    style={{
                      fontSize: 28,
                      fontWeight: 700,
                      fontFamily: 'monospace',
                      color:
                        worstLossStreak.count === 0
                          ? '#22c55e'
                          : worstLossStreak.count < 3
                            ? '#f59e0b'
                            : '#ef4444',
                    }}
                  >
                    {worstLossStreak.count} 次
                  </div>
                  {/* 最近5笔盈亏色块条 */}
                  {worstLossStreak.history.length > 0 && (
                    <div style={{ display: 'flex', gap: 4, marginTop: 8, alignItems: 'center' }}>
                      {worstLossStreak.history.map((pnl, i) => (
                        <div
                          key={i}
                          title={`${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}`}
                          style={{
                            width: 10,
                            height: 10,
                            borderRadius: '50%',
                            backgroundColor: pnl >= 0 ? '#22c55e' : '#ef4444',
                            flexShrink: 0,
                          }}
                        />
                      ))}
                      <span style={{ fontSize: 10, color: '#525252', marginLeft: 2 }}>近5笔</span>
                    </div>
                  )}
                  <div style={{ marginTop: 6, fontSize: 11, color: '#737373' }}>
                    {worstLossStreak.count === 0
                      ? '暂无连续亏损'
                      : worstLossStreak.count < 3
                        ? `${worstLossStreak.name} · 正常范围`
                        : `⚠ ${worstLossStreak.name}`}
                  </div>
                </>
              ) : (
                <>
                  <div
                    style={{
                      fontSize: 28,
                      fontWeight: 700,
                      fontFamily: 'monospace',
                      color: '#737373',
                    }}
                  >
                    --
                  </div>
                  <div style={{ marginTop: 8, fontSize: 11, color: '#737373' }}>无运行中的策略</div>
                </>
              )}
            </Card>
          </Tooltip>
        </Col>

        {/* 保证金占用比 */}
        <Col xs={24} sm={12} lg={6} xl={5} xxl={5}>
          <Tooltip title="初始保证金 imr / 账户总净值。优先使用 OKX 账户级 imr，全仓和逐仓都能统一反映资金占用">
            <Card variant="borderless" size="small" style={{ height: '100%' }}>
              <div style={{ marginBottom: 8 }}>
                <div
                  className="pro-card-header"
                  style={{ display: 'flex', alignItems: 'center', gap: 4 }}
                >
                  <Activity size={11} />
                  保证金占用比
                </div>
              </div>
              <div
                style={{
                  fontSize: 28,
                  fontWeight: 700,
                  fontFamily: 'monospace',
                  color:
                    marginUsagePct < 30 ? '#22c55e' : marginUsagePct < 60 ? '#f59e0b' : '#ef4444',
                }}
              >
                {totalAssets > 0 ? `${formatPercent(marginUsagePct)}%` : '--'}
              </div>
              <div style={{ marginTop: 8 }}>
                <Progress
                  percent={Math.min(100, marginUsagePct)}
                  strokeColor={
                    marginUsagePct < 30 ? '#22c55e' : marginUsagePct < 60 ? '#f59e0b' : '#ef4444'
                  }
                  showInfo={false}
                  size="small"
                />
                <div style={{ fontSize: 11, color: '#737373', marginTop: 4 }}>
                  已用 ${formatAmount(effectiveMarginUsed)}
                  {marginRiskPct > 0 && (
                    <span style={{ marginLeft: 6 }}>维持风险 {formatPercent(marginRiskPct)}%</span>
                  )}
                </div>
              </div>
            </Card>
          </Tooltip>
        </Col>

        {/* 账户综合杠杆率 */}
        <Col xs={24} sm={12} lg={6} xl={5} xxl={5}>
          <Tooltip title="合约持仓总价值 / 账户总净值。代表当前整体杠杆倍数，建议保持在 3x 以内">
            <Card variant="borderless" size="small" style={{ height: '100%' }}>
              <div style={{ marginBottom: 8 }}>
                <div
                  className="pro-card-header"
                  style={{ display: 'flex', alignItems: 'center', gap: 4 }}
                >
                  <BarChart2 size={11} />
                  账户综合杠杆
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
                <div
                  style={{
                    fontSize: 28,
                    fontWeight: 700,
                    fontFamily: 'monospace',
                    color:
                      accountLeverage < 2 ? '#22c55e' : accountLeverage < 5 ? '#f59e0b' : '#ef4444',
                  }}
                >
                  {totalAssets > 0 ? formatPercent(accountLeverage, 2) : '--'}
                </div>
                {totalAssets > 0 && (
                  <span style={{ fontSize: 16, color: '#a3a3a3', fontWeight: 600 }}>x</span>
                )}
              </div>
              <div style={{ marginTop: 8 }}>
                <Progress
                  percent={Math.min(100, (accountLeverage / 10) * 100)}
                  strokeColor={
                    accountLeverage < 2 ? '#22c55e' : accountLeverage < 5 ? '#f59e0b' : '#ef4444'
                  }
                  showInfo={false}
                  size="small"
                />
                <div style={{ fontSize: 11, color: '#737373', marginTop: 4 }}>
                  合约价值 ${formatAmount(contractPositionValue)}
                </div>
              </div>
            </Card>
          </Tooltip>
        </Col>

        {/* 最大回撤 (7天) */}
        <Col xs={24} sm={12} lg={6} xl={5} xxl={5}>
          <Tooltip title="近7天账户净值从峰值到谷值的最大跌幅。系统启动后每小时自动记录一次净值快照">
            <Card variant="borderless" size="small" style={{ height: '100%' }}>
              <div style={{ marginBottom: 8 }}>
                <div
                  className="pro-card-header"
                  style={{ display: 'flex', alignItems: 'center', gap: 4 }}
                >
                  <AlertTriangle size={11} />
                  最大回撤 (7d)
                </div>
              </div>
              {maxDrawdownPct > 0 ? (
                <>
                  <div
                    style={{
                      fontSize: 28,
                      fontWeight: 700,
                      fontFamily: 'monospace',
                      color:
                        maxDrawdownPct < 5
                          ? '#22c55e'
                          : maxDrawdownPct < 15
                            ? '#f59e0b'
                            : '#ef4444',
                    }}
                  >
                    -{formatPercent(maxDrawdownPct)}%
                  </div>
                  <div style={{ marginTop: 8 }}>
                    <Progress
                      percent={Math.min(100, (maxDrawdownPct / 30) * 100)}
                      strokeColor={
                        maxDrawdownPct < 5 ? '#22c55e' : maxDrawdownPct < 15 ? '#f59e0b' : '#ef4444'
                      }
                      showInfo={false}
                      size="small"
                    />
                    <div style={{ fontSize: 11, color: '#737373', marginTop: 4 }}>
                      最大亏损 ${formatAmount(maxDrawdown)}
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div
                    style={{
                      fontSize: 28,
                      fontWeight: 700,
                      fontFamily: 'monospace',
                      color: '#22c55e',
                    }}
                  >
                    0%
                  </div>
                  <div style={{ marginTop: 8, fontSize: 11, color: '#737373' }}>暂无回撤记录</div>
                </>
              )}
            </Card>
          </Tooltip>
        </Col>

        {/* 风险健康度 */}
        <Col xs={24} sm={12} lg={6} xl={5} xxl={5}>
          <Tooltip title="综合评分：维持保证金风险率 mmr/adjEq(40%) + 账户杠杆(30%) + 最大回撤(30%)。OKX mgnRatio 是安全倍数，越大越安全">
            <Card variant="borderless" size="small" style={{ height: '100%' }}>
              <div style={{ marginBottom: 8 }}>
                <div
                  className="pro-card-header"
                  style={{ display: 'flex', alignItems: 'center', gap: 4 }}
                >
                  <ShieldAlert size={11} />
                  风险健康度
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                <div
                  style={{
                    fontSize: 28,
                    fontWeight: 700,
                    fontFamily: 'monospace',
                    color: getRiskHealthColor(riskHealth),
                  }}
                >
                  {Math.round(riskHealth)}
                </div>
                <span style={{ fontSize: 14, color: '#737373' }}>/100</span>
              </div>
              <div style={{ marginTop: 8 }}>
                <Progress
                  percent={riskHealth}
                  strokeColor={getRiskHealthColor(riskHealth)}
                  showInfo={false}
                  size="small"
                />
                <div
                  style={{
                    fontSize: 11,
                    color: getRiskHealthColor(riskHealth),
                    marginTop: 4,
                    fontWeight: 600,
                  }}
                >
                  {getRiskHealthLabel(riskHealth)}
                  {marginRatio > 0 && (
                    <span style={{ color: '#737373', fontWeight: 400, marginLeft: 6 }}>
                      安全 {formatAmount(marginRatio)}x
                    </span>
                  )}
                </div>
              </div>
            </Card>
          </Tooltip>
        </Col>
      </Row>

      {/* ── 持仓列表 ── */}
      <Card
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div className="pro-card-header" style={{ margin: 0 }}>
              {t('dashboard.positions').toUpperCase()}
            </div>
            <Tag
              style={{
                margin: 0,
                fontSize: 10,
                padding: '1px 6px',
                fontWeight: 600,
                border: 'none',
                background: 'rgba(24, 144, 255, 0.15)',
                color: '#1890ff',
              }}
            >
              {positionsWithPrice.length}
            </Tag>
          </div>
        }
        extra={
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  backgroundColor: wsConnected ? '#22c55e' : '#ef4444',
                  animation: wsConnected
                    ? 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite'
                    : 'none',
                }}
              />
              <Wifi size={12} style={{ color: wsConnected ? '#22c55e' : '#ef4444' }} />
              <span style={{ fontSize: 11, color: '#a3a3a3' }}>
                {wsConnected ? '实时推送' : '已断线'}
              </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <Clock size={11} style={{ color: '#a3a3a3' }} />
              <span style={{ fontSize: 11, color: '#a3a3a3' }}>
                {getRelativeTime(lastUpdateTime)}
              </span>
            </div>

            <Button
              type="text"
              size="small"
              icon={<RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />}
              onClick={fetchDashboardData}
              style={{ color: '#a3a3a3' }}
            >
              {t('common.refresh')}
            </Button>
          </div>
        }
        variant="borderless"
        size="small"
        style={{ marginTop: 16 }}
      >
        <Table
          columns={positionColumns}
          dataSource={positionsWithPrice}
          loading={loading && balance === null}
          pagination={false}
          size="small"
          scroll={{ x: 800 }}
          locale={{
            emptyText: (
              <div style={{ padding: '40px 0', color: '#737373' }}>
                <div style={{ fontSize: 48, marginBottom: 8 }}>📊</div>
                <div>{t('dashboard.noPositions')}</div>
              </div>
            ),
          }}
        />
      </Card>

      {/* ── 策略状态 + 最近交易 ── */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} md={12}>
          <Card
            title={
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div className="pro-card-header" style={{ margin: 0 }}>
                  {t('strategy.strategies').toUpperCase()}
                </div>
                <Tag
                  style={{
                    margin: 0,
                    fontSize: 10,
                    padding: '1px 6px',
                    fontWeight: 600,
                    border: 'none',
                    background: 'rgba(34, 197, 94, 0.15)',
                    color: '#22c55e',
                  }}
                >
                  {runningStrategies.length} RUNNING
                </Tag>
              </div>
            }
            variant="borderless"
            size="small"
          >
            {runningStrategies.length === 0 ? (
              <div style={{ padding: '20px 0', textAlign: 'center', color: '#737373' }}>
                <div style={{ fontSize: 32, marginBottom: 8 }}>⚡</div>
                <div>{t('dashboard.noRunningStrategies')}</div>
              </div>
            ) : (
              <div>
                {runningStrategies.map((strategy: any) => (
                  <div
                    key={strategy.id}
                    style={{
                      padding: '12px',
                      marginBottom: 8,
                      background: '#1a1a1a',
                      borderRadius: 4,
                      border: '1px solid #2a2a2a',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'start',
                        marginBottom: 8,
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 600, marginBottom: 4 }}>{strategy.name}</div>
                        <div style={{ fontSize: 12, color: '#737373' }}>
                          {strategy.symbol} · {strategy.type.toUpperCase()}
                        </div>
                      </div>
                      <Tag
                        style={{
                          margin: 0,
                          fontSize: 10,
                          padding: '2px 8px',
                          fontWeight: 600,
                          border: 'none',
                          background: 'rgba(34, 197, 94, 0.15)',
                          color: '#22c55e',
                        }}
                      >
                        RUNNING
                      </Tag>
                    </div>
                    <Row gutter={8}>
                      <Col span={12}>
                        <div style={{ fontSize: 11, color: '#737373' }}>盈亏</div>
                        <div
                          className={`font-mono ${(strategy.total_profit || 0) >= 0 ? 'text-up' : 'text-down'}`}
                          style={{ fontSize: 14, fontWeight: 600 }}
                        >
                          {(strategy.total_profit || 0) >= 0 ? '+' : ''}$
                          {formatAmount(strategy.total_profit || 0)}
                        </div>
                      </Col>
                      <Col span={12}>
                        <div style={{ fontSize: 11, color: '#737373' }}>交易次数</div>
                        <div className="font-mono" style={{ fontSize: 14, fontWeight: 600 }}>
                          {strategy.total_trades || 0}
                        </div>
                      </Col>
                    </Row>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </Col>

        <Col xs={24} md={12}>
          <Card
            title={
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div className="pro-card-header" style={{ margin: 0 }}>
                  {t('dashboard.recentTrades').toUpperCase()}
                </div>
                <Tag
                  style={{
                    margin: 0,
                    fontSize: 10,
                    padding: '1px 6px',
                    fontWeight: 600,
                    border: 'none',
                    background: 'rgba(34, 197, 94, 0.15)',
                    color: '#22c55e',
                  }}
                >
                  {recentOrders.length}
                </Tag>
              </div>
            }
            variant="borderless"
            size="small"
          >
            {recentOrders.length > 0 ? (
              <div style={{ maxHeight: 300, overflowY: 'auto' }}>
                {recentOrders.map((order: any, index: number) => (
                  <div
                    key={order.id || index}
                    style={{
                      padding: '8px 0',
                      borderBottom: index < recentOrders.length - 1 ? '1px solid #2a2a2a' : 'none',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <div style={{ flex: 1 }}>
                      <div
                        style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}
                      >
                        <Tag
                          color={order.side === 'buy' ? 'green' : 'red'}
                          style={{ margin: 0, fontSize: 11, padding: '0 4px' }}
                        >
                          {order.side === 'buy' ? '买入' : '卖出'}
                        </Tag>
                        <span style={{ fontSize: 13, fontWeight: 500 }}>{order.symbol}</span>
                        {order.strategy_name && (
                          <Tag style={{ margin: 0, fontSize: 10, padding: '0 4px' }}>
                            {order.strategy_name}
                          </Tag>
                        )}
                      </div>
                      <div style={{ fontSize: 11, color: '#a3a3a3' }}>
                        {new Date(order.created_at).toLocaleString('zh-CN', {
                          month: '2-digit',
                          day: '2-digit',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>
                        {formatPrice(order.avg_price || order.price)}
                      </div>
                      <div style={{ fontSize: 11, color: '#a3a3a3' }}>
                        {formatQuantityDisplay(order.filled_size || order.size || order.amount)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ padding: '20px 0', textAlign: 'center', color: '#737373' }}>
                <div style={{ fontSize: 32, marginBottom: 8 }}>📈</div>
                <div>{t('dashboard.noRecentTrades')}</div>
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default Dashboard
