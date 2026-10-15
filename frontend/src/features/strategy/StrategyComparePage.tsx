import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Alert, Card, Col, Empty, Row, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { strategyApi } from '@/services/api'
import type { Strategy, StrategyEvent } from '@/types'

const { Text, Title } = Typography

type StrategyStats = {
  strategy_id: number
  is_running: boolean
  realized_pnl?: number
  total_trades?: number
  signal_status?: Record<string, any>
  position_status?: Record<string, any>
  risk_status?: Record<string, any>
  health_status?: Record<string, any>
}

type CompareRow = {
  strategy: Strategy
  stats?: StrategyStats
  events: StrategyEvent[]
}

const fmtPct = (value?: number) => {
  if (value === undefined || value === null || Number.isNaN(value)) return '-'
  return `${value.toFixed(2)}%`
}

const fmtUsd = (value?: number) => {
  if (value === undefined || value === null || Number.isNaN(value)) return '$0'
  return `$${value.toFixed(2)}`
}

const shortName = (name: string) => {
  if (name.includes('优化版')) return '优化版'
  return '原版'
}

const signalText = (stats?: StrategyStats) => {
  const message = stats?.signal_status?.message
  if (!message) return '等待扫描'
  if (message.includes('等待下一根')) return '等待下一根小时K'
  if (message.includes('已扫描')) return '已扫描，暂无候选'
  if (message.includes('过滤')) return '市场过滤中'
  return message
}

const candidateText = (stats?: StrategyStats) => {
  const candidates = stats?.signal_status?.candidates
  if (!Array.isArray(candidates) || candidates.length === 0) return '无'
  return candidates
    .slice(0, 2)
    .map((item: any) => item.symbol || item.instId || '-')
    .join('、')
}

const lastEventText = (events: StrategyEvent[]) => {
  const event = events[0]
  if (!event) return '暂无'
  return event.title || event.event_type || '事件'
}

export default function StrategyComparePage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['strategy-ab-compare'],
    refetchInterval: 10_000,
    queryFn: async (): Promise<CompareRow[]> => {
      const list = await strategyApi.getList()
      const targets = list.items
        .filter((item) => item.type === 'explosive_momentum_chaser')
        .filter(
          (item) => item.name.includes('爆量急拉') || item.symbol.includes('EXPLOSIVE-MOMENTUM'),
        )
        .sort((a, b) => a.id - b.id)

      return Promise.all(
        targets.map(async (strategy) => {
          const [statsResult, eventsResult] = await Promise.allSettled([
            strategyApi.getStats(strategy.id) as Promise<StrategyStats>,
            strategyApi.getEvents(strategy.id, 0, 1),
          ])
          return {
            strategy,
            stats: statsResult.status === 'fulfilled' ? statsResult.value : undefined,
            events: eventsResult.status === 'fulfilled' ? eventsResult.value.items : [],
          }
        }),
      )
    },
  })

  const rows = data || []

  const parameterRows = useMemo(() => {
    const items = [
      ['hold_hours', '持仓'],
      ['min_signal', '触发'],
      ['market_filter', '过滤'],
      ['max_leverage', '杠杆'],
      ['max_position_usd', '仓位'],
      ['risk_fuse.max_drawdown_pct', '熔断'],
    ]

    const getValue = (strategy: Strategy, key: string) => {
      const value = key.split('.').reduce<any>((acc, part) => acc?.[part], strategy.parameters)
      if (key === 'hold_hours') return `${value}h`
      if (key === 'min_signal' || key.includes('pct')) return fmtPct(Number(value) * 100)
      if (key === 'market_filter') return value === 'none' ? '无' : 'BTC过滤'
      if (key === 'max_position_usd') return fmtUsd(Number(value))
      return value ?? '-'
    }

    return items.map(([key, label]) => ({
      key,
      label,
      values: rows.map((row) => getValue(row.strategy, key)),
    }))
  }, [rows])

  const parameterColumns: ColumnsType<any> = [
    { title: '', dataIndex: 'label', key: 'label', width: 90 },
    ...rows.map((row, index) => ({
      title: shortName(row.strategy.name),
      key: String(row.strategy.id),
      render: (_: any, record: any) => {
        const different = new Set(record.values).size > 1
        return <Text type={different ? undefined : 'secondary'}>{record.values[index]}</Text>
      },
    })),
  ]

  return (
    <div>
      <Space
        align="center"
        style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }}
      >
        <div>
          <Title level={3} style={{ margin: 0 }}>
            策略对比
          </Title>
          <Text type="secondary">10 秒自动刷新</Text>
        </div>
        <Tag color="blue">{rows.length} 个策略</Tag>
      </Space>

      {error && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message="加载失败"
          description={String((error as any)?.message || error)}
        />
      )}

      {rows.length === 0 && !isLoading ? (
        <Card>
          <Empty description="暂无可对比策略" />
        </Card>
      ) : (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Row gutter={[16, 16]}>
            {rows.map((row) => {
              const open = row.stats?.position_status?.open_positions || 0
              const notional = row.stats?.position_status?.current_notional_usd || 0
              const risk = row.stats?.risk_status || {}
              const hasError = Boolean(row.stats?.health_status?.last_error_at)
              return (
                <Col xs={24} xl={12} key={row.strategy.id}>
                  <Card loading={isLoading} bodyStyle={{ padding: 18 }}>
                    <Space direction="vertical" size={14} style={{ width: '100%' }}>
                      <Space
                        align="center"
                        style={{ width: '100%', justifyContent: 'space-between' }}
                      >
                        <Space>
                          <Title level={4} style={{ margin: 0 }}>
                            {shortName(row.strategy.name)}
                          </Title>
                          <Tag color={row.strategy.status === 'running' ? 'green' : 'default'}>
                            {row.strategy.status === 'running' ? '运行中' : '已停止'}
                          </Tag>
                        </Space>
                        <Text type="secondary">ID {row.strategy.id}</Text>
                      </Space>

                      <div
                        style={{
                          padding: 14,
                          borderRadius: 10,
                          background: '#111827',
                          border: '1px solid #263244',
                        }}
                      >
                        <Text type="secondary">当前信号</Text>
                        <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>
                          {signalText(row.stats)}
                        </div>
                        <Text type="secondary">候选：{candidateText(row.stats)}</Text>
                      </div>

                      <Row gutter={12}>
                        <Col span={8}>
                          <Text type="secondary">持仓</Text>
                          <div style={{ fontSize: 18, fontWeight: 700 }}>
                            {open ? `${open}个` : '空仓'}
                          </div>
                        </Col>
                        <Col span={8}>
                          <Text type="secondary">仓位</Text>
                          <div style={{ fontSize: 18, fontWeight: 700 }}>{fmtUsd(notional)}</div>
                        </Col>
                        <Col span={8}>
                          <Text type="secondary">交易</Text>
                          <div style={{ fontSize: 18, fontWeight: 700 }}>
                            {row.stats?.total_trades || 0}
                          </div>
                        </Col>
                      </Row>

                      <Space wrap>
                        <Tag color={hasError ? 'red' : 'green'}>{hasError ? '异常' : '健康'}</Tag>
                        <Tag color="purple">回撤 {fmtPct(risk.max_runtime_drawdown)}</Tag>
                        <Tag color="orange">
                          连亏 {risk.consecutive_losses ?? 0}/{risk.max_consecutive_losses ?? '-'}
                        </Tag>
                        <Tag>{lastEventText(row.events)}</Tag>
                      </Space>
                    </Space>
                  </Card>
                </Col>
              )
            })}
          </Row>

          <Card title="参数差异" bodyStyle={{ paddingTop: 8 }}>
            <Table
              rowKey="key"
              dataSource={parameterRows}
              columns={parameterColumns}
              pagination={false}
              size="small"
            />
          </Card>
        </Space>
      )}
    </div>
  )
}
