import { Modal, Descriptions, Statistic, Row, Col, Card, Tag, Space, Spin, Tabs, Progress, Timeline, Empty } from 'antd'
import { TrendingUp, TrendingDown, List, BarChart3, ScrollText } from 'lucide-react'
import { Strategy, StrategyEvent } from '@/types'
import { useTranslation } from 'react-i18next'
import { useState, useEffect } from 'react'
import { strategyApi } from '@/services/api'
import { wsService, StrategyStatsData, StrategyUpdateData, OrderUpdateData } from '@/services/websocket'
import { formatAmount, formatPrice, formatQuantityDisplay, formatPercent } from '@/utils/format'
import StrategyOrderHistory from './StrategyOrderHistory'

interface StrategyDetailModalProps {
  open: boolean
  strategy: Strategy | null
  onCancel: () => void
}

export default function StrategyDetailModal({ open, strategy, onCancel }: StrategyDetailModalProps) {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [strategyDetail, setStrategyDetail] = useState<any>(null)
  const [pnlData, setPnlData] = useState<any>(null)
  const [events, setEvents] = useState<StrategyEvent[]>([])

  // 获取策略实时统计数据
  const fetchStrategyStats = async () => {
    if (!strategy) return

    try {
      setLoading(true)
      const stats = await strategyApi.getStats(strategy.id)
      setStrategyDetail(stats)
    } catch (error) {
      // 处理错误
    } finally {
      setLoading(false)
    }
  }

  // 获取策略盈亏数据
  const fetchPnlData = async () => {
    if (!strategy) return

    try {
      const pnl = await strategyApi.getPnl(strategy.id)
      const raw = (pnl as any)?.data ?? pnl
      setPnlData({
        ...raw,
        total_pnl: raw?.total_pnl ?? raw?.total_profit,
        realized_pnl: raw?.realized_pnl ?? raw?.realized_profit,
        unrealized_pnl: raw?.unrealized_pnl ?? raw?.unrealized_profit,
        pnl_rate: raw?.pnl_rate ?? raw?.total_profit_rate,
      })
    } catch (error) {
      // 处理错误
    }
  }

  const fetchEvents = async () => {
    if (!strategy) return

    try {
      const data = await strategyApi.getEvents(strategy.id, 0, 100)
      setEvents(data.items || [])
    } catch (error) {
      // 事件流是辅助信息，失败时不打断详情页
    }
  }

  // 当Modal打开时获取初始数据并订阅WebSocket实时更新
  useEffect(() => {
    if (open && strategy) {
      // 初始数据加载
      fetchStrategyStats()
      fetchPnlData()
      fetchEvents()

      // 订阅该策略的实时更新
      wsService.subscribeStrategy(strategy.id)

      // 监听策略状态更新（每50秒数据库持久化时）
      const unsubscribeUpdate = wsService.onSingleStrategyUpdate(
        strategy.id,
        (data: StrategyUpdateData) => {
          // 可以在这里更新策略的基本信息
        }
      )

      // 监听策略实时统计（每5秒一次）
      const unsubscribeStats = wsService.onSingleStrategyStats(
        strategy.id,
        (data: StrategyStatsData) => {
          // 实时更新策略统计数据
          setStrategyDetail(data)
        }
      )

      // 监听订单更新
      const unsubscribeOrder = wsService.onSingleOrderUpdate(
        strategy.id,
        (orderData: OrderUpdateData) => {
          // 订单状态变化，立即刷新盈亏数据
          fetchPnlData()
          fetchEvents()
        }
      )

      // 定时刷新盈亏数据（每30秒一次）
      const pnlInterval = setInterval(() => {
        fetchPnlData()
        fetchEvents()
      }, 30000)

      return () => {
        unsubscribeUpdate()
        unsubscribeStats()
        unsubscribeOrder()
        wsService.unsubscribeStrategy(strategy.id)
        clearInterval(pnlInterval)
      }
    }
  }, [open, strategy])

  if (!strategy) return null

  // 合并真实数据和默认数据
  const displayData = strategyDetail || {
    is_running: false,
    position_size: 0,
    position_cost: 0,
    realized_pnl: 0,
    total_trades: 0,
    total_buy_volume: 0,
    total_sell_volume: 0,
    grid_orders: 0,
  }

  // 计算显示数据 - 优先使用PNL API返回的数据
  const realized_pnl = pnlData?.realized_pnl ?? displayData.realized_pnl ?? 0
  const unrealized_pnl = pnlData?.unrealized_pnl ?? displayData.unrealized_pnl ?? 0
  const total_pnl = pnlData?.total_pnl ?? (realized_pnl + unrealized_pnl)
  const pnl_rate = pnlData?.pnl_rate ?? 0
  const total_fee = pnlData?.total_fee ?? 0

  // 持仓信息 - 优先使用PNL API返回的精确数据
  const current_position = pnlData?.current_position ?? displayData.position_size ?? 0
  const position_value = pnlData?.position_value ?? displayData.position_cost ?? 0
  const avg_buy_price = pnlData?.avg_buy_price ?? 0
  const avg_sell_price = pnlData?.avg_sell_price ?? 0
  const avg_cost = current_position > 0 && position_value > 0
    ? position_value / current_position
    : avg_buy_price

  // 交易统计 - 优先使用PNL API返回的数据
  const buy_count = pnlData?.buy_count ?? displayData.buy_count ?? 0
  const sell_count = pnlData?.sell_count ?? displayData.sell_count ?? 0
  const total_trades = pnlData?.total_trades ?? displayData.total_trades ?? (buy_count + sell_count)
  const total_buy_amount = pnlData?.total_buy_amount ?? displayData.total_buy_volume ?? 0
  const total_sell_amount = pnlData?.total_sell_amount ?? displayData.total_sell_volume ?? 0
  const signalStatus = displayData.signal_status
  const positionStatus = displayData.position_status
  const riskStatus = displayData.risk_status
  const healthStatus = displayData.health_status

  const trendLabel: Record<string, string> = {
    bull: '多头趋势',
    bear: '空头趋势',
    flat: '震荡',
    position: '持仓中',
    cooldown: '冷却中',
    unknown: '初始化',
  }

  const waitingLabel: Record<string, string> = {
    long: '等回撤做多',
    short: '等反弹做空',
    exit: '等止盈/止损',
    cooldown: '冷却中',
    kline_data: '等K线数据',
    atr: '等ATR数据',
    flat: '等趋势',
    tick: '等行情',
  }

  const pctText = (value?: number | null) => (
    value == null || Number.isNaN(Number(value)) ? '-' : `${Number(value).toFixed(2)}%`
  )

  const inferPositionSide = (pos: any) => {
    if (pos?.side) return pos.side
    const entry = Number(pos?.entry_price || 0)
    const stop = Number(pos?.stop_px || 0)
    if (entry > 0 && stop > 0) return stop < entry ? 'long' : 'short'
    return ''
  }

  const distanceToStopPct = (pos: any) => {
    if (pos?.distance_to_stop_pct != null) return pos.distance_to_stop_pct
    const side = inferPositionSide(pos)
    const current = Number(pos?.current_price || 0)
    const stop = Number(pos?.stop_px || 0)
    if (!current || !stop) return null
    if (side === 'long') return (current - stop) / current * 100
    if (side === 'short') return (stop - current) / current * 100
    return null
  }

  const distanceToTakeProfitPct = (pos: any) => {
    if (pos?.distance_to_take_profit_pct != null) return pos.distance_to_take_profit_pct
    const side = inferPositionSide(pos)
    const current = Number(pos?.current_price || 0)
    const takeProfit = Number(pos?.take_profit_px || 0)
    if (!current || !takeProfit) return null
    if (side === 'long') return (takeProfit - current) / current * 100
    if (side === 'short') return (current - takeProfit) / current * 100
    return null
  }

  const sideText = (side?: string) => {
    if (side === 'long') return '做多'
    if (side === 'short') return '做空'
    return '-'
  }

  const moneyText = (value?: number | null) => (
    value == null || Number.isNaN(Number(value)) ? '-' : `${formatAmount(value)} USDT`
  )

  const eventTypeLabel: Record<string, string> = {
    start: '启动',
    signal: '信号',
    open_position: '开仓',
    close_position: '平仓',
    risk_pause: '风控',
    safety_pause: '安全暂停',
    near_exit_trigger: '临近提醒',
    stop: '停止',
    error: '异常',
  }

  const eventColor = (event: StrategyEvent) => {
    if (event.level === 'success') return 'green'
    if (event.level === 'warning') return 'orange'
    if (event.level === 'error') return 'red'
    if (event.event_type === 'signal') return 'blue'
    return 'gray'
  }

  const formatEventTime = (value?: string) => {
    if (!value) return '-'
    return new Date(value).toLocaleString()
  }

  const formatUnixTime = (value?: number | null) => {
    if (!value) return '-'
    return new Date(Number(value) * 1000).toLocaleString()
  }

  // Tab标签页配置
  const tabItems = [
    {
      key: 'stats',
      label: (
        <span>
          <BarChart3 size={14} />
          统计概览
        </span>
      ),
      children: (
        <div>
          {/* 盈亏统计 */}
          <Card title="实时盈亏" variant="borderless" style={{ marginBottom: 16 }}>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={6}>
                <Statistic
                  title="总盈亏"
                  value={total_pnl}
                  precision={2}
                  valueStyle={{
                    color: total_pnl >= 0 ? '#22c55e' : '#ef4444',
                    fontWeight: 600,
                    fontSize: 20,
                  }}
                  prefix={total_pnl >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                  suffix="USDT"
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="收益率"
                  value={pnl_rate}
                  precision={2}
                  valueStyle={{
                    color: pnl_rate >= 0 ? '#22c55e' : '#ef4444',
                    fontWeight: 600,
                    fontSize: 20,
                  }}
                  prefix={pnl_rate >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                  suffix="%"
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title={t('strategy.realizedPnl')}
                  value={realized_pnl}
                  precision={2}
                  valueStyle={{
                    color: realized_pnl >= 0 ? '#22c55e' : '#ef4444',
                    fontSize: 18,
                  }}
                  prefix={realized_pnl >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                  suffix="USDT"
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title={t('strategy.unrealizedPnl')}
                  value={unrealized_pnl}
                  precision={2}
                  valueStyle={{
                    color: unrealized_pnl >= 0 ? '#22c55e' : '#ef4444',
                    fontSize: 18,
                  }}
                  prefix={unrealized_pnl >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                  suffix="USDT"
                />
              </Col>
            </Row>
            <Row gutter={16}>
              <Col span={6}>
                <Statistic
                  title="总手续费"
                  value={total_fee}
                  precision={2}
                  valueStyle={{
                    color: '#f59e0b',
                    fontSize: 16,
                  }}
                  suffix="USDT"
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="买入次数"
                  value={pnlData?.buy_count ?? 0}
                  valueStyle={{
                    color: '#22c55e',
                    fontSize: 16,
                  }}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="卖出次数"
                  value={pnlData?.sell_count ?? 0}
                  valueStyle={{
                    color: '#ef4444',
                    fontSize: 16,
                  }}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="成交次数"
                  value={(pnlData?.buy_count ?? 0) + (pnlData?.sell_count ?? 0)}
                  valueStyle={{
                    color: '#3b82f6',
                    fontSize: 16,
                  }}
                />
              </Col>
            </Row>
          </Card>

          {signalStatus && (
            <Card title="当前信号" variant="borderless" size="small" style={{ marginBottom: 16 }}>
              {signalStatus.top_symbols || signalStatus.symbol ? (
                <Descriptions column={3} size="small">
                  <Descriptions.Item label="动态涨幅榜" span={2}>
                    <Space wrap>
                      {(signalStatus.top_symbols || []).map((symbol: string) => (
                        <Tag key={symbol}>{symbol}</Tag>
                      ))}
                      {!signalStatus.top_symbols?.length && (signalStatus.symbol || '-')}
                    </Space>
                  </Descriptions.Item>
                  <Descriptions.Item label="策略方向">
                    <Tag color={signalStatus.direction === 'short' ? 'red' : signalStatus.direction === 'long' ? 'green' : 'blue'}>
                      {signalStatus.direction || signalStatus.side || '-'}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="最近信号">{signalStatus.status || '-'}</Descriptions.Item>
                  <Descriptions.Item label="动作">{signalStatus.action || '-'}</Descriptions.Item>
                  <Descriptions.Item label="信号方向">
                    <Tag color={signalStatus.side === 'short' ? 'red' : signalStatus.side === 'long' ? 'green' : 'default'}>
                      {signalStatus.side || '-'}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="价格">{signalStatus.last != null ? formatPrice(signalStatus.last) : '-'}</Descriptions.Item>
                  <Descriptions.Item label="RSI">{signalStatus.rsi != null ? Number(signalStatus.rsi).toFixed(2) : '-'}</Descriptions.Item>
                  <Descriptions.Item label="ATR占比">{pctText(signalStatus.atr_pct)}</Descriptions.Item>
                  <Descriptions.Item label="首轮观察">
                    {signalStatus.observe_first_scan == null ? '-' : signalStatus.observe_first_scan ? '开启' : '关闭'}
                  </Descriptions.Item>
                  <Descriptions.Item label="说明" span={3}>{signalStatus.message || '-'}</Descriptions.Item>
                </Descriptions>
              ) : (
                <Descriptions column={3} size="small">
                  <Descriptions.Item label="趋势">
                    <Tag color={
                      signalStatus.trend === 'bull' ? 'green'
                        : signalStatus.trend === 'bear' ? 'red'
                          : signalStatus.trend === 'position' ? 'blue'
                            : 'default'
                    }>
                      {trendLabel[signalStatus.trend] || signalStatus.trend || '-'}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="等待方向">
                    <Tag color={
                      signalStatus.waiting_for === 'long' ? 'green'
                        : signalStatus.waiting_for === 'short' ? 'red'
                          : 'default'
                    }>
                      {waitingLabel[signalStatus.waiting_for] || signalStatus.waiting_for || '-'}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="距离触发">
                    {signalStatus.distance_pct != null ? `${Number(signalStatus.distance_pct).toFixed(2)}%` : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="当前价">
                    {signalStatus.current_price != null ? formatPrice(signalStatus.current_price) : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="触发价">
                    {signalStatus.trigger_price != null ? formatPrice(signalStatus.trigger_price) : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="ATR">
                    {signalStatus.atr != null ? formatPrice(signalStatus.atr) : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="EMA快线">
                    {signalStatus.ema_fast != null ? formatPrice(signalStatus.ema_fast) : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="EMA慢线">
                    {signalStatus.ema_slow != null ? formatPrice(signalStatus.ema_slow) : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="原因" span={3}>
                    {signalStatus.message || '-'}
                  </Descriptions.Item>
                </Descriptions>
              )}
            </Card>
          )}

          {positionStatus && (
            <Card title="持仓止盈止损" variant="borderless" size="small" style={{ marginBottom: 16 }}>
              {positionStatus.dynamic ? (
                <>
                  <Descriptions column={3} size="small" style={{ marginBottom: 12 }}>
                    <Descriptions.Item label="状态">
                      <Tag color={positionStatus.in_position ? 'blue' : 'default'}>
                        {positionStatus.in_position ? `${positionStatus.open_positions} 个持仓` : '空仓'}
                      </Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="当前名义价值">
                      {positionStatus.current_notional_usd == null ? '-' : moneyText(positionStatus.current_notional_usd)}
                    </Descriptions.Item>
                    <Descriptions.Item label="浮动盈亏">
                      <span style={{ color: unrealized_pnl >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>
                        {moneyText(unrealized_pnl)}
                      </span>
                    </Descriptions.Item>
                  </Descriptions>
                  {(positionStatus.positions || []).length ? (
                    <Space direction="vertical" size={8} style={{ width: '100%' }}>
                      {positionStatus.positions.map((pos: any) => {
                        const inferredSide = inferPositionSide(pos)
                        return (
                        <Card key={pos.symbol} size="small" variant="borderless" style={{ background: '#fafafa' }}>
                          <Descriptions column={3} size="small">
                            <Descriptions.Item label="交易对">{pos.symbol}</Descriptions.Item>
                            <Descriptions.Item label="方向">
                              <Tag color={inferredSide === 'long' ? 'green' : inferredSide === 'short' ? 'red' : 'default'}>
                                {sideText(inferredSide)}
                              </Tag>
                            </Descriptions.Item>
                            <Descriptions.Item label="数量">{pos.qty ? formatQuantityDisplay(pos.qty) : '-'}</Descriptions.Item>
                            <Descriptions.Item label="开仓价">{pos.entry_price ? formatPrice(pos.entry_price) : '-'}</Descriptions.Item>
                            <Descriptions.Item label="当前价">{pos.current_price ? formatPrice(pos.current_price) : '-'}</Descriptions.Item>
                            <Descriptions.Item label="止损价">
                              <span style={{ color: '#ef4444', fontWeight: 600 }}>
                                {pos.stop_px ? formatPrice(pos.stop_px) : '-'}
                              </span>
                            </Descriptions.Item>
                            <Descriptions.Item label="距离止损">{pctText(distanceToStopPct(pos))}</Descriptions.Item>
                            <Descriptions.Item label="止盈价">
                              <span style={{ color: '#22c55e', fontWeight: 600 }}>
                                {pos.take_profit_px ? formatPrice(pos.take_profit_px) : '-'}
                              </span>
                            </Descriptions.Item>
                            <Descriptions.Item label="距离止盈">{pctText(distanceToTakeProfitPct(pos))}</Descriptions.Item>
                          </Descriptions>
                        </Card>
                      )})}
                    </Space>
                  ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无动态持仓" />}
                </>
              ) : (
                <Descriptions column={3} size="small">
                  <Descriptions.Item label="状态">
                    <Tag color={positionStatus.in_position ? 'blue' : 'default'}>
                      {positionStatus.in_position ? '持仓中' : '空仓'}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="方向">
                    <Tag color={
                      positionStatus.side === 'long' ? 'green'
                        : positionStatus.side === 'short' ? 'red'
                          : 'default'
                    }>
                      {sideText(positionStatus.side)}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="数量">
                    {positionStatus.qty ? formatQuantityDisplay(positionStatus.qty) : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="开仓价">
                    {positionStatus.entry_price ? formatPrice(positionStatus.entry_price) : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="当前价">
                    {positionStatus.current_price ? formatPrice(positionStatus.current_price) : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="浮动盈亏">
                    <span style={{ color: unrealized_pnl >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>
                      {moneyText(unrealized_pnl)}
                    </span>
                  </Descriptions.Item>
                  <Descriptions.Item label="止损价">
                    <span style={{ color: '#ef4444', fontWeight: 600 }}>
                      {positionStatus.stop_px ? formatPrice(positionStatus.stop_px) : '-'}
                    </span>
                  </Descriptions.Item>
                  <Descriptions.Item label="距离止损">
                    {pctText(distanceToStopPct(positionStatus))}
                  </Descriptions.Item>
                  <Descriptions.Item label="止盈价">
                    <span style={{ color: '#22c55e', fontWeight: 600 }}>
                      {positionStatus.take_profit_px ? formatPrice(positionStatus.take_profit_px) : '-'}
                    </span>
                  </Descriptions.Item>
                  <Descriptions.Item label="距离止盈">
                    {pctText(distanceToTakeProfitPct(positionStatus))}
                  </Descriptions.Item>
                </Descriptions>
              )}
            </Card>
          )}

          {riskStatus && (
            <Card title="运行风控" variant="borderless" size="small" style={{ marginBottom: 16 }}>
              <Descriptions column={3} size="small">
                <Descriptions.Item label="熔断状态">
                  <Tag color={riskStatus.enabled ? 'green' : 'default'}>
                    {riskStatus.enabled ? '已启用' : '未启用'}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="风控基准">
                  {moneyText(riskStatus.risk_base_usd)}
                </Descriptions.Item>
                <Descriptions.Item label="利润因子窗口">
                  最近 {riskStatus.profit_factor_window ?? '-'} 笔
                </Descriptions.Item>
                <Descriptions.Item label="连续亏损">
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    <span>{riskStatus.consecutive_losses ?? 0} / {riskStatus.max_consecutive_losses ?? '-'}</span>
                    <Progress
                      percent={
                        riskStatus.max_consecutive_losses
                          ? Math.min(100, (Number(riskStatus.consecutive_losses || 0) / Number(riskStatus.max_consecutive_losses)) * 100)
                          : 0
                      }
                      size="small"
                      showInfo={false}
                      strokeColor="#f59e0b"
                    />
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="今日亏损">
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    <span>
                      {moneyText(Math.min(0, Number(riskStatus.daily_realized_pnl || 0)))} / -{moneyText(riskStatus.daily_loss_limit_usd)}
                    </span>
                    <Progress
                      percent={
                        riskStatus.daily_loss_limit_usd
                          ? Math.min(100, Math.abs(Math.min(0, Number(riskStatus.daily_realized_pnl || 0))) / Number(riskStatus.daily_loss_limit_usd) * 100)
                          : 0
                      }
                      size="small"
                      showInfo={false}
                      strokeColor="#ef4444"
                    />
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="运行回撤">
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    <span>{moneyText(riskStatus.max_runtime_drawdown)} / {moneyText(riskStatus.max_drawdown_limit_usd)}</span>
                    <Progress
                      percent={
                        riskStatus.max_drawdown_limit_usd
                          ? Math.min(100, Number(riskStatus.max_runtime_drawdown || 0) / Number(riskStatus.max_drawdown_limit_usd) * 100)
                          : 0
                      }
                      size="small"
                      showInfo={false}
                      strokeColor="#ef4444"
                    />
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="利润因子">
                  {riskStatus.runtime_profit_factor == null ? '-' : Number(riskStatus.runtime_profit_factor).toFixed(2)}
                  {riskStatus.min_profit_factor != null ? ` / ${Number(riskStatus.min_profit_factor).toFixed(2)}` : ''}
                </Descriptions.Item>
              </Descriptions>
            </Card>
          )}

          {healthStatus && (
            <Card title="运行健康" variant="borderless" size="small" style={{ marginBottom: 16 }}>
              <Descriptions column={3} size="small">
                <Descriptions.Item label="账户模式">
                  <Tag color={healthStatus.exchange_simulated ? 'blue' : 'red'}>
                    {healthStatus.exchange_simulated ? '模拟盘' : '实盘'}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="最近行情">
                  {formatUnixTime(healthStatus.last_ticker_at)}
                </Descriptions.Item>
                <Descriptions.Item label="最近成功处理">
                  {formatUnixTime(healthStatus.last_tick_ok_at)}
                </Descriptions.Item>
                <Descriptions.Item label="最近异常">
                  {formatUnixTime(healthStatus.last_error_at)}
                </Descriptions.Item>
                <Descriptions.Item label="异常信息" span={2}>
                  {healthStatus.last_error_message || '-'}
                </Descriptions.Item>
              </Descriptions>
            </Card>
          )}

          {/* 持仓信息 */}
          <Card title={t('strategy.positionInfo')} variant="borderless" size="small" style={{ marginBottom: 16 }}>
            <Descriptions column={2} size="small">
              <Descriptions.Item label={t('strategy.positionSize')}>
                <span className="font-mono" style={{ fontWeight: 600 }}>
                  {formatQuantityDisplay(current_position) || '0'}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label={t('strategy.positionCost')}>
                <span className="font-mono" style={{ fontWeight: 600 }}>
                  ${position_value ? formatPrice(position_value) : '0.00'}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label={t('strategy.avgCost')}>
                <span className="font-mono" style={{ fontWeight: 600 }}>
                  ${formatPrice(avg_cost)}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label={t('strategy.winRate')}>
                <span style={{
                  fontWeight: 600,
                  color: (strategy.win_rate ?? 0) >= 50 ? '#22c55e' : '#ef4444'
                }}>
                  {formatPercent(strategy.win_rate ?? 0, 1)}%
                </span>
              </Descriptions.Item>
            </Descriptions>
          </Card>

          {/* 交易统计 */}
          <Card title={t('strategy.tradingStats')} variant="borderless" size="small" style={{ marginBottom: 16 }}>
            <Row gutter={16}>
              <Col span={6}>
                <Statistic title={t('strategy.totalTrades')} value={total_trades || 0} />
              </Col>
              <Col span={6}>
                <Statistic
                  title={t('strategy.buyVolume')}
                  value={total_buy_amount || 0}
                  precision={2}
                  valueStyle={{ color: '#22c55e' }}
                  suffix="USDT"
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title={t('strategy.sellVolume')}
                  value={total_sell_amount || 0}
                  precision={2}
                  valueStyle={{ color: '#ef4444' }}
                  suffix="USDT"
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title={t('strategy.gridOrders')}
                  value={displayData.grid_orders || 0}
                  suffix={
                    <span style={{ fontSize: '14px', marginLeft: '4px', whiteSpace: 'nowrap' }}>
                      {displayData.is_running ? t('strategy.active') : t('strategy.inactive')}
                    </span>
                  }
                  valueStyle={{ display: 'flex', alignItems: 'center' }}
                />
              </Col>
            </Row>
          </Card>

        </div>
      ),
    },
    {
      key: 'orders',
      label: (
        <span>
          <List size={14} />
          订单历史
        </span>
      ),
      children: <StrategyOrderHistory strategyId={strategy.id} />,
    },
    {
      key: 'events',
      label: (
        <span>
          <ScrollText size={14} />
          运行日志
        </span>
      ),
      children: (
        <Card variant="borderless">
          {events.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无运行日志，策略启动后会自动记录信号、开仓、平仓和风控事件"
            />
          ) : (
            <Timeline
              mode="left"
              items={events.map(event => ({
                color: eventColor(event),
                label: (
                  <span style={{ color: '#737373', fontSize: 12 }}>
                    {formatEventTime(event.created_at)}
                  </span>
                ),
                children: (
                  <div>
                    <Space size={8} wrap>
                      <Tag color={eventColor(event)}>
                        {eventTypeLabel[event.event_type] || event.event_type}
                      </Tag>
                      <span style={{ fontWeight: 600 }}>{event.title}</span>
                    </Space>
                    {event.message && (
                      <div style={{ marginTop: 6, color: '#a3a3a3' }}>
                        {event.message}
                      </div>
                    )}
                    {event.parameter_snapshot && Object.keys(event.parameter_snapshot).length > 0 && event.event_type === 'start' && (
                      <Descriptions column={3} size="small" style={{ marginTop: 8 }}>
                        <Descriptions.Item label="周期">
                          {event.parameter_snapshot.trend_timeframe || event.parameter_snapshot.timeframe || '-'}
                        </Descriptions.Item>
                        <Descriptions.Item label="杠杆">
                          {event.parameter_snapshot.leverage ? `${event.parameter_snapshot.leverage}x` : '-'}
                        </Descriptions.Item>
                        <Descriptions.Item label="方向">
                          {event.parameter_snapshot.direction || '-'}
                        </Descriptions.Item>
                        <Descriptions.Item label="EMA">
                          {event.parameter_snapshot.fast_period || '-'} / {event.parameter_snapshot.slow_period || '-'}
                        </Descriptions.Item>
                        <Descriptions.Item label="止损/止盈">
                          {event.parameter_snapshot.stop_atr_multiple || '-'} / {event.parameter_snapshot.take_profit_atr_multiple || '-'} ATR
                        </Descriptions.Item>
                        <Descriptions.Item label="最大仓位">
                          {event.parameter_snapshot.max_position_usd ? `${formatAmount(event.parameter_snapshot.max_position_usd)} USDT` : '-'}
                        </Descriptions.Item>
                      </Descriptions>
                    )}
                  </div>
                ),
              }))}
            />
          )}
        </Card>
      ),
    },
  ]

  return (
    <Modal
      title={
        <div className="pro-card-header" style={{ margin: 0 }}>
          {t('strategy.monitor').toUpperCase()} - {strategy.name}
        </div>
      }
      open={open}
      onCancel={onCancel}
      width={1000}
      footer={null}
    >
      <Spin spinning={loading}>
        <Tabs defaultActiveKey="stats" items={tabItems} />
      </Spin>
    </Modal>
  )
}
