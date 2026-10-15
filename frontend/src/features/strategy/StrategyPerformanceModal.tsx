import { Modal, Card, Row, Col, Statistic, Spin, Empty, Alert, App } from 'antd'
import { TrendingUp, TrendingDown, Info } from 'lucide-react'
import { useState, useEffect } from 'react'
import ReactECharts from 'echarts-for-react'
import { strategyApi } from '@/services/api'
import type { Strategy, StrategyPerformance } from '@/types'
import { formatAmount } from '@/utils/format'

interface StrategyPerformanceModalProps {
  open: boolean
  strategy: Strategy | null
  onCancel: () => void
}

export default function StrategyPerformanceModal({
  open,
  strategy,
  onCancel,
}: StrategyPerformanceModalProps) {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [performance, setPerformance] = useState<StrategyPerformance | null>(null)

  useEffect(() => {
    if (open && strategy) {
      // 立即获取一次数据
      fetchPerformance()

      // 每30秒自动刷新性能数据
      const intervalId = setInterval(() => {
        fetchPerformance()
      }, 30000)

      // 清理定时器
      return () => clearInterval(intervalId)
    }
  }, [open, strategy])

  const fetchPerformance = async () => {
    if (!strategy) return

    try {
      setLoading(true)
      const data = await strategyApi.getPerformance(strategy.id)
      setPerformance(data)
    } catch (error) {
      message.error('获取策略性能失败')
    } finally {
      setLoading(false)
    }
  }

  // 累计收益曲线配置
  const getProfitChartOption = () => {
    if (!performance || performance.profit_history.length === 0) return {}

    return {
      title: {
        text: '累计收益曲线',
        left: 'center',
        textStyle: {
          color: '#e5e5e5',
          fontSize: 14,
          fontWeight: 600,
        },
      },
      backgroundColor: 'transparent',
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        top: '15%',
        containLabel: true,
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(0, 0, 0, 0.8)',
        borderColor: '#2a2a2a',
        textStyle: {
          color: '#e5e5e5',
        },
        formatter: (params: any) => {
          const data = params[0]
          return `
            <div style="font-size: 12px;">
              <div>${new Date(data.name).toLocaleString()}</div>
              <div style="margin-top: 4px;">
                <span style="color: ${data.value >= 0 ? '#22c55e' : '#ef4444'};">
                  盈亏: ${data.value >= 0 ? '+' : ''}${formatAmount(data.value)} USDT
                </span>
              </div>
            </div>
          `
        },
      },
      xAxis: {
        type: 'category',
        data: performance.profit_history.map((item) => item.timestamp),
        axisLabel: {
          color: '#a3a3a3',
          formatter: (value: string) => {
            const date = new Date(value)
            return `${date.getMonth() + 1}/${date.getDate()} ${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`
          },
        },
        axisLine: {
          lineStyle: {
            color: '#2a2a2a',
          },
        },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: '#a3a3a3',
          formatter: (value: number) => formatAmount(value),
        },
        axisLine: {
          lineStyle: {
            color: '#2a2a2a',
          },
        },
        splitLine: {
          lineStyle: {
            color: '#2a2a2a',
            type: 'dashed',
          },
        },
      },
      series: [
        {
          name: '累计盈亏',
          type: 'line',
          data: performance.profit_history.map((item) => item.cumulative_profit),
          smooth: true,
          lineStyle: {
            color: performance.total_profit >= 0 ? '#22c55e' : '#ef4444',
            width: 2,
          },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                {
                  offset: 0,
                  color:
                    performance.total_profit >= 0
                      ? 'rgba(34, 197, 94, 0.3)'
                      : 'rgba(239, 68, 68, 0.3)',
                },
                {
                  offset: 1,
                  color:
                    performance.total_profit >= 0
                      ? 'rgba(34, 197, 94, 0.05)'
                      : 'rgba(239, 68, 68, 0.05)',
                },
              ],
            },
          },
          itemStyle: {
            color: performance.total_profit >= 0 ? '#22c55e' : '#ef4444',
          },
        },
      ],
    }
  }

  // 每日盈亏柱状图配置
  const getDailyProfitChartOption = () => {
    if (!performance || performance.daily_profits.length === 0) return {}

    return {
      title: {
        text: '每日盈亏',
        left: 'center',
        textStyle: {
          color: '#e5e5e5',
          fontSize: 14,
          fontWeight: 600,
        },
      },
      backgroundColor: 'transparent',
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        top: '15%',
        containLabel: true,
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(0, 0, 0, 0.8)',
        borderColor: '#2a2a2a',
        textStyle: {
          color: '#e5e5e5',
        },
        formatter: (params: any) => {
          const data = params[0]
          return `
            <div style="font-size: 12px;">
              <div>${data.name}</div>
              <div style="margin-top: 4px;">
                <span style="color: ${data.value >= 0 ? '#22c55e' : '#ef4444'};">
                  ${data.value >= 0 ? '+' : ''}${formatAmount(data.value)} USDT
                </span>
              </div>
            </div>
          `
        },
      },
      xAxis: {
        type: 'category',
        data: performance.daily_profits.map((item) => item.date),
        axisLabel: {
          color: '#a3a3a3',
          formatter: (value: string) => {
            const parts = value.split('-')
            return `${parts[1]}/${parts[2]}`
          },
        },
        axisLine: {
          lineStyle: {
            color: '#2a2a2a',
          },
        },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: '#a3a3a3',
          formatter: (value: number) => formatAmount(value),
        },
        axisLine: {
          lineStyle: {
            color: '#2a2a2a',
          },
        },
        splitLine: {
          lineStyle: {
            color: '#2a2a2a',
            type: 'dashed',
          },
        },
      },
      series: [
        {
          name: '日盈亏',
          type: 'bar',
          data: performance.daily_profits.map((item) => item.profit),
          itemStyle: {
            color: (params: any) => {
              return params.value >= 0 ? '#22c55e' : '#ef4444'
            },
          },
        },
      ],
    }
  }

  const hasOpenPosition =
    Boolean(performance?.in_position) || Math.abs(performance?.unrealized_profit ?? 0) > 0
  const hasClosedTrades = (performance?.total_trades ?? 0) > 0
  const totalOrders = performance?.total_orders ?? performance?.total_trades ?? 0

  return (
    <Modal
      title={`策略性能监控 - ${strategy?.name || ''}`}
      open={open}
      onCancel={onCancel}
      width={1200}
      footer={null}
      styles={{
        body: {
          maxHeight: '70vh',
          overflowY: 'auto',
        },
      }}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <Spin size="large" />
        </div>
      ) : !performance ? (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <div style={{ color: '#a3a3a3' }}>
                <div style={{ fontSize: 14, marginBottom: 8 }}>暂无性能数据</div>
                <div style={{ fontSize: 12, color: '#666' }}>无法加载策略性能统计信息</div>
              </div>
            }
          />
        </div>
      ) : (
        <div>
          {/* 空状态提示 */}
          {!hasOpenPosition && !hasClosedTrades && (
            <Alert
              message="策略尚未产生交易"
              description={
                strategy?.status === 'running'
                  ? '策略正在运行中,订单成交后将显示实时性能数据'
                  : '启动策略后将开始收集性能数据,包括收益率、胜率、盈亏曲线等'
              }
              type="info"
              showIcon
              icon={<Info size={14} />}
              style={{ marginBottom: 24 }}
            />
          )}
          {hasOpenPosition && !hasClosedTrades && (
            <Alert
              message="策略已开仓，等待平仓统计"
              description="当前持仓已有未实现盈亏，平仓后将生成胜率、已实现盈亏和收益曲线。"
              type="info"
              showIcon
              icon={<Info size={14} />}
              style={{ marginBottom: 24 }}
            />
          )}

          {/* 核心指标卡片 */}
          <Row gutter={16} style={{ marginBottom: 24 }}>
            <Col span={6}>
              <Card>
                <Statistic
                  title="总收益"
                  value={performance.total_profit}
                  precision={2}
                  valueStyle={{ color: performance.total_profit >= 0 ? '#22c55e' : '#ef4444' }}
                  prefix={
                    performance.total_profit >= 0 ? (
                      <TrendingUp size={14} />
                    ) : (
                      <TrendingDown size={14} />
                    )
                  }
                  suffix="USDT"
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="收益率"
                  value={performance.total_profit_rate}
                  precision={2}
                  valueStyle={{ color: performance.total_profit_rate >= 0 ? '#22c55e' : '#ef4444' }}
                  prefix={
                    performance.total_profit_rate >= 0 ? (
                      <TrendingUp size={14} />
                    ) : (
                      <TrendingDown size={14} />
                    )
                  }
                  suffix="%"
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="胜率"
                  value={performance.win_rate}
                  precision={2}
                  valueStyle={{ color: '#1890ff' }}
                  suffix="%"
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic title="订单次数" value={totalOrders} valueStyle={{ color: '#e5e5e5' }} />
              </Card>
            </Col>
          </Row>

          <Row gutter={16} style={{ marginBottom: 24 }}>
            <Col span={6}>
              <Card>
                <Statistic
                  title="已实现盈亏"
                  value={performance.realized_profit}
                  precision={2}
                  valueStyle={{ color: performance.realized_profit >= 0 ? '#22c55e' : '#ef4444' }}
                  suffix="USDT"
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="未实现盈亏"
                  value={performance.unrealized_profit}
                  precision={2}
                  valueStyle={{ color: performance.unrealized_profit >= 0 ? '#22c55e' : '#ef4444' }}
                  suffix="USDT"
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="最大回撤"
                  value={performance.max_drawdown}
                  precision={2}
                  valueStyle={{ color: '#ef4444' }}
                  suffix="USDT"
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="手续费"
                  value={performance.total_fee}
                  precision={2}
                  valueStyle={{ color: '#a3a3a3' }}
                  suffix="USDT"
                />
              </Card>
            </Col>
          </Row>

          {/* 图表区域 */}
          {performance.profit_history.length > 0 && (
            <Row gutter={16}>
              <Col span={24} style={{ marginBottom: 24 }}>
                <Card>
                  <ReactECharts option={getProfitChartOption()} style={{ height: '300px' }} />
                </Card>
              </Col>
              {performance.daily_profits.length > 0 && (
                <Col span={24}>
                  <Card>
                    <ReactECharts
                      option={getDailyProfitChartOption()}
                      style={{ height: '300px' }}
                    />
                  </Card>
                </Col>
              )}
            </Row>
          )}

          {performance.profit_history.length === 0 && (
            <Card>
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  <div style={{ color: '#a3a3a3' }}>
                    <div style={{ fontSize: 14, marginBottom: 8 }}>
                      {hasOpenPosition ? '持仓尚未平仓' : '暂无交易记录'}
                    </div>
                    <div style={{ fontSize: 12, color: '#666' }}>
                      {hasOpenPosition
                        ? '当前持仓尚未平仓，平仓后将生成收益曲线'
                        : strategy?.status === 'running'
                          ? '策略正在运行中,请等待订单成交后查看性能数据'
                          : '策略尚未启动或未产生交易,启动策略后将自动生成性能分析'}
                    </div>
                  </div>
                }
              />
            </Card>
          )}
        </div>
      )}
    </Modal>
  )
}
