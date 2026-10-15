import { useMemo, useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  Bot,
  RefreshCw,
  Search,
  ShieldCheck,
  Activity,
  Wallet,
} from 'lucide-react'

const { Text, Title } = Typography

const TRADEKIT_BASE_URL = (import.meta as any).env?.VITE_TRADEKIT_BASE_URL || '/tradekit-api'

type TradeKitHealth = {
  service: string
  okx_cli: {
    installed: boolean
    path?: string
    version?: {
      ok: boolean
      stdout?: string
      stderr?: string
    }
  }
  policy: {
    mode: string
    require_human_confirm: boolean
    limits?: {
      max_order_notional_usdt?: number
      max_daily_notional_usdt?: number
      max_leverage?: number
    }
    allowed_modules?: string[]
  }
}

type OkkOverview = {
  status: {
    connected: boolean
    health: any
    base_url: string
    user_id: number
  }
  strategy_count: number
  running_strategy_count: number
  strategies: any[]
  balance: any
  swap_positions: any[]
  health_report?: {
    risk_level: 'low' | 'medium' | 'high'
    summary: string
    total_equity: number
    position_notional: number
    notional_to_equity: number
    unrealized_pnl: number
    pnl_to_equity: number
    max_leverage: number
    min_margin_ratio: number
    orphan_position_count: number
    unresolved_orphan_position_count: number
    manual_position_count: number
    unmatched_position_count: number
    checks: Array<{ code: string; level: 'low' | 'medium' | 'high'; message: string }>
    suggested_actions: string[]
  }
  copilot_notes: string[]
}

type ProposalReview = {
  approved_for_execution: boolean
  mode: string
  require_human_confirm: boolean
  violations: Array<{ code: string; message: string }>
  warnings: string[]
  next_action: string
}

async function tradeKitFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${TRADEKIT_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers || {}),
    },
  })

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`)
  }

  return response.json()
}

function formatCliVersion(health?: TradeKitHealth) {
  return health?.okx_cli?.version?.stdout?.split('\n')[0] || '--'
}

function getTotalEq(balance: any) {
  const value = balance?.data?.totalEq || balance?.totalEq
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function getPositionNotional(positions?: any[]) {
  return (positions || []).reduce((sum, item) => sum + Number(item.notional_usd || item.notionalUsd || 0), 0)
}

function riskTagColor(level?: string) {
  if (level === 'high') return 'red'
  if (level === 'medium') return 'gold'
  return 'green'
}

function riskAlertType(level?: string): 'success' | 'info' | 'warning' | 'error' {
  if (level === 'high') return 'error'
  if (level === 'medium') return 'warning'
  return 'success'
}

const TradeKitPage = () => {
  const [tickerSymbol, setTickerSymbol] = useState('BTC-USDT')
  const [tickerOutput, setTickerOutput] = useState('等待查询')
  const [reviewOutput, setReviewOutput] = useState<ProposalReview | null>(null)
  const [form] = Form.useForm()

  const healthQuery = useQuery({
    queryKey: ['tradekit-health'],
    queryFn: () => tradeKitFetch<TradeKitHealth>('/health'),
    refetchInterval: 30000,
  })

  const overviewQuery = useQuery({
    queryKey: ['tradekit-okk-overview'],
    queryFn: () => tradeKitFetch<OkkOverview>('/okk/overview'),
    refetchInterval: 30000,
  })

  const tickerMutation = useMutation({
    mutationFn: (symbol: string) => tradeKitFetch<any>(`/market/ticker/${encodeURIComponent(symbol)}`),
    onSuccess: (data) => {
      setTickerOutput(data.stdout || JSON.stringify(data, null, 2))
    },
    onError: (error: Error) => {
      setTickerOutput(error.message)
      message.error(`行情查询失败: ${error.message}`)
    },
  })

  const reviewMutation = useMutation({
    mutationFn: (values: any) => tradeKitFetch<ProposalReview>('/proposal/review', {
      method: 'POST',
      body: JSON.stringify({
        inst_id: values.inst_id,
        side: values.side,
        product_type: 'swap',
        notional_usdt: Number(values.notional_usdt),
        leverage: Number(values.leverage),
        order_type: 'market',
        reason: values.reason || '',
        source: 'okk-frontend',
      }),
    }),
    onSuccess: (data) => {
      setReviewOutput(data)
    },
    onError: (error: Error) => {
      message.error(`草稿评估失败: ${error.message}`)
    },
  })

  const attributionMutation = useMutation({
    mutationFn: ({ positionKey, values }: { positionKey: string; values: any }) =>
      tradeKitFetch(`/okk/position-attributions/${encodeURIComponent(positionKey)}`, {
        method: 'PUT',
        body: JSON.stringify(values),
      }),
    onSuccess: () => {
      message.success('持仓归因已保存')
      overviewQuery.refetch()
    },
    onError: (error: Error) => {
      message.error(`归因保存失败: ${error.message}`)
    },
  })

  const health = healthQuery.data
  const overview = overviewQuery.data
  const totalEq = useMemo(() => getTotalEq(overview?.balance), [overview?.balance])
  const positionNotional = useMemo(() => getPositionNotional(overview?.swap_positions), [overview?.swap_positions])

  const refreshAll = () => {
    healthQuery.refetch()
    overviewQuery.refetch()
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <Title level={3} style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
            <Bot size={22} />
            AI 副驾驶
          </Title>
          <Text type="secondary">TradeKit 只读实盘体检、策略建议草稿和风控预检</Text>
        </div>
        <Button icon={<RefreshCw size={15} />} onClick={refreshAll} loading={healthQuery.isFetching || overviewQuery.isFetching}>
          刷新
        </Button>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={12} xl={6}>
          <Card>
            <Statistic
              title="TradeKit"
              value={health?.okx_cli?.installed ? '可用' : '不可用'}
              prefix={<Activity size={18} />}
              valueStyle={{ color: health?.okx_cli?.installed ? '#22c55e' : '#ef4444', fontSize: 22 }}
            />
            <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>{formatCliVersion(health)}</Text>
          </Card>
        </Col>
        <Col xs={24} md={12} xl={6}>
          <Card>
            <Statistic
              title="OKK 后端"
              value={overview?.status?.connected ? '已连接' : '未连接'}
              prefix={<ShieldCheck size={18} />}
              valueStyle={{ color: overview?.status?.connected ? '#22c55e' : '#ef4444', fontSize: 22 }}
            />
            <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>{overview?.status?.base_url || '--'}</Text>
          </Card>
        </Col>
        <Col xs={24} md={12} xl={6}>
          <Card>
            <Statistic title="账户净值" value={totalEq} precision={2} suffix="USDT" prefix={<Wallet size={18} />} />
            <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>由 OKK 余额接口读取</Text>
          </Card>
        </Col>
        <Col xs={24} md={12} xl={6}>
          <Card>
            <Statistic title="SWAP 持仓" value={overview?.swap_positions?.length || 0} suffix="个" />
            <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>名义价值约 {positionNotional.toFixed(2)} USD</Text>
          </Card>
        </Col>
      </Row>

      {health?.policy && (
        <Card title="安全策略">
          <Space size={[8, 8]} wrap>
            <Tag color={health.policy.mode === 'read_only' ? 'blue' : 'orange'}>{health.policy.mode}</Tag>
            <Tag color={health.policy.require_human_confirm ? 'gold' : 'red'}>
              {health.policy.require_human_confirm ? '需要人工确认' : '无需人工确认'}
            </Tag>
            <Tag>单笔 {health.policy.limits?.max_order_notional_usdt ?? '--'} USDT</Tag>
            <Tag>日内 {health.policy.limits?.max_daily_notional_usdt ?? '--'} USDT</Tag>
            <Tag>杠杆 {health.policy.limits?.max_leverage ?? '--'}x</Tag>
            {(health.policy.allowed_modules || []).map((item) => <Tag key={item}>{item}</Tag>)}
          </Space>
        </Card>
      )}

      {overview?.health_report && (
        <Card
          title="实盘体检"
          extra={<Tag color={riskTagColor(overview.health_report.risk_level)}>{overview.health_report.risk_level}</Tag>}
        >
          <Alert
            type={riskAlertType(overview.health_report.risk_level)}
            showIcon
            message={overview.health_report.summary}
            style={{ marginBottom: 16 }}
          />
          <Row gutter={[16, 16]}>
            <Col xs={12} md={6}>
              <Statistic title="暴露倍数" value={overview.health_report.notional_to_equity} precision={2} suffix="x" />
            </Col>
            <Col xs={12} md={6}>
              <Statistic
                title="未实现盈亏"
                value={overview.health_report.unrealized_pnl}
                precision={2}
                valueStyle={{ color: overview.health_report.unrealized_pnl < 0 ? '#ef4444' : '#22c55e' }}
              />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="最高杠杆" value={overview.health_report.max_leverage} precision={1} suffix="x" />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="未归因持仓" value={overview.health_report.unresolved_orphan_position_count} suffix="个" />
            </Col>
          </Row>
          <Space direction="vertical" style={{ width: '100%', marginTop: 16 }}>
            {overview.health_report.checks.map((item) => (
              <Alert
                key={item.code}
                type={riskAlertType(item.level)}
                showIcon
                message={item.message}
              />
            ))}
            {overview.health_report.suggested_actions.map((item) => (
              <Alert key={item} type="info" showIcon message={item} />
            ))}
          </Space>
        </Card>
      )}

      <Card title="当前持仓归因">
        <Table
          size="small"
          rowKey={(record) => record.position_key || record.pos_id || record.id || record.symbol}
          dataSource={overview?.swap_positions || []}
          pagination={false}
          scroll={{ x: 960 }}
          locale={{ emptyText: '暂无 SWAP 持仓' }}
          columns={[
            {
              title: '标的',
              dataIndex: 'symbol',
              width: 160,
              render: (value, record) => value || record.inst_id || record.instId || '--',
            },
            {
              title: '方向',
              dataIndex: 'side',
              width: 90,
              render: (value, record) => <Tag>{value || record.pos_side || record.posSide || 'net'}</Tag>,
            },
            {
              title: '名义价值',
              dataIndex: 'notional_usd',
              width: 120,
              render: (value, record) => Number(value || record.notionalUsd || 0).toFixed(2),
            },
            {
              title: '未实现盈亏',
              dataIndex: 'unrealized_pnl',
              width: 120,
              render: (value, record) => {
                const pnl = Number(value || record.upl || 0)
                return <span style={{ color: pnl < 0 ? '#ef4444' : '#22c55e' }}>{pnl.toFixed(2)}</span>
              },
            },
            {
              title: '杠杆',
              dataIndex: 'leverage',
              width: 90,
              render: (value, record) => `${Number(value || record.lever || 0).toFixed(1)}x`,
            },
            {
              title: '当前归因',
              dataIndex: 'attribution',
              width: 140,
              render: (value) => {
                const kind = value?.kind || 'pending'
                const color = kind === 'manual' ? 'blue' : kind === 'strategy' ? 'green' : kind === 'ignored' ? 'default' : 'gold'
                const label = kind === 'manual' ? '手动仓位' : kind === 'strategy' ? '策略仓位' : kind === 'ignored' ? '忽略' : '待处理'
                return <Tag color={color}>{label}</Tag>
              },
            },
            {
              title: '操作',
              key: 'actions',
              width: 300,
              render: (_, record) => {
                const positionKey = record.position_key || `symbol:${record.symbol || record.inst_id || record.instId}:${record.side || record.pos_side || 'net'}`
                const save = (kind: string) => {
                  attributionMutation.mutate({
                    positionKey,
                    values: {
                      kind,
                      note: kind === 'manual' ? '用户确认的手动仓位' : '',
                      strategy_id: null,
                    },
                  })
                }
                return (
                  <Space wrap>
                    <Button size="small" onClick={() => save('manual')}>标手动</Button>
                    <Button size="small" onClick={() => save('strategy')}>标策略</Button>
                    <Button size="small" onClick={() => save('ignored')}>忽略</Button>
                    <Button size="small" onClick={() => save('pending')}>待处理</Button>
                  </Space>
                )
              },
            },
          ]}
        />
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={10}>
          <Card
            title="行情查询"
            extra={
              <Button
                size="small"
                icon={<Search size={14} />}
                onClick={() => tickerMutation.mutate(tickerSymbol)}
                loading={tickerMutation.isPending}
              >
                查询
              </Button>
            }
          >
            <Input value={tickerSymbol} onChange={(event) => setTickerSymbol(event.target.value)} />
            <pre className="font-mono" style={preStyle}>{tickerOutput}</pre>
          </Card>
        </Col>

        <Col xs={24} xl={14}>
          <Card title="交易草稿风控评估">
            <Form
              form={form}
              layout="vertical"
              initialValues={{
                inst_id: 'BTC-USDT-SWAP',
                side: 'long',
                notional_usdt: 100,
                leverage: 5,
                reason: 'momentum review',
              }}
              onFinish={(values) => reviewMutation.mutate(values)}
            >
              <Row gutter={12}>
                <Col xs={24} md={8}>
                  <Form.Item label="标的" name="inst_id" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                </Col>
                <Col xs={12} md={5}>
                  <Form.Item label="方向" name="side" rules={[{ required: true }]}>
                    <Select
                      options={['long', 'short', 'buy', 'sell', 'close'].map((value) => ({ label: value, value }))}
                    />
                  </Form.Item>
                </Col>
                <Col xs={12} md={5}>
                  <Form.Item label="金额" name="notional_usdt" rules={[{ required: true }]}>
                    <InputNumber min={1} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col xs={12} md={6}>
                  <Form.Item label="杠杆" name="leverage" rules={[{ required: true }]}>
                    <InputNumber min={1} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item label="理由" name="reason">
                <Input.TextArea rows={3} />
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={reviewMutation.isPending}>
                评估草稿
              </Button>
            </Form>

            {reviewOutput && (
              <div style={{ marginTop: 16 }}>
                <Alert
                  type={reviewOutput.approved_for_execution ? 'success' : 'warning'}
                  showIcon
                  message={reviewOutput.approved_for_execution ? '可进入执行网关' : '当前不可执行'}
                  description={`模式: ${reviewOutput.mode} · 下一步: ${reviewOutput.next_action}`}
                />
                <Space size={[8, 8]} wrap style={{ marginTop: 12 }}>
                  {reviewOutput.violations.map((item) => <Tag color="red" key={item.code}>{item.message}</Tag>)}
                  {reviewOutput.warnings.map((item) => <Tag color="gold" key={item}>{item}</Tag>)}
                </Space>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <Card title="策略副驾驶">
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={10}>
            <Space direction="vertical" style={{ width: '100%' }}>
              {(overview?.copilot_notes || []).map((note) => (
                <Alert key={note} type="info" showIcon message={note} />
              ))}
              {!overview?.copilot_notes?.length && <Empty description="暂无副驾驶提示" />}
            </Space>
          </Col>
          <Col xs={24} lg={14}>
            {overview?.strategies?.length ? (
              <Descriptions bordered size="small" column={1}>
                {overview.strategies.map((item) => (
                  <Descriptions.Item key={item.id} label={item.name || `策略 ${item.id}`}>
                    <Space wrap>
                      <Tag>{item.type}</Tag>
                      <Tag>{item.symbol}</Tag>
                      <Tag color={String(item.status).toLowerCase() === 'running' ? 'green' : 'default'}>{item.status}</Tag>
                    </Space>
                  </Descriptions.Item>
                ))}
              </Descriptions>
            ) : (
              <Empty description="暂无策略数据" />
            )}
          </Col>
        </Row>
      </Card>
    </div>
  )
}

const preStyle: React.CSSProperties = {
  marginTop: 12,
  minHeight: 132,
  maxHeight: 280,
  overflow: 'auto',
  padding: 12,
  border: '1px solid #2a2a2a',
  borderRadius: 4,
  background: '#0d0d0d',
  color: '#e5e5e5',
  whiteSpace: 'pre-wrap',
  fontSize: 12,
}

export default TradeKitPage
