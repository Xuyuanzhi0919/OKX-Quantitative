import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card,
  Form,
  Input,
  InputNumber,
  Switch,
  Button,
  Row,
  Col,
  Space,
  Typography,
  Tag,
  Divider,
  Alert,
  Tooltip,
  Select,
  App,
} from 'antd'
import {
  ArrowLeftOutlined,
  InfoCircleOutlined,
  CheckCircleFilled,
  RiseOutlined,
} from '@ant-design/icons'
import { strategyApi } from '@/services/api'
import { useQuery } from '@tanstack/react-query'
import { API_BASE_URL } from '@/config/api'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

// ── 策略元信息（可扩展添加新策略）─────────────────────────────
const STRATEGY_META: Record<
  string,
  {
    label: string
    tag: string
    tagColor: string
    icon: React.ReactNode
    summary: string
    fixedParams: { label: string; value: string; tooltip: string }[]
    notes: string[]
  }
> = {
  trend: {
    label: 'EMA 趋势跟踪策略',
    tag: '已验证',
    tagColor: '#52c41a',
    icon: <RiseOutlined />,
    summary:
      '基于 EMA 双均线金叉/死叉产生做多信号，叠加 RSI 超买过滤，仅在 15m K 线时间周期有效。经 256 组参数网格搜索与 7 天交叉验证，最终收益 +7.75%，Profit Factor 3.90。',
    fixedParams: [
      {
        label: 'EMA 快线',
        value: '12 根',
        tooltip: '短期 EMA 周期，金叉/死叉的信号敏感度主要由此决定',
      },
      { label: 'EMA 慢线', value: '40 根', tooltip: '长期 EMA 周期，代表中期趋势方向' },
      { label: 'K 线周期', value: '15m', tooltip: '仅在 15 分钟 K 线上回测有效，1H/4H 无信号' },
      {
        label: '方向',
        value: 'Long-only（做多）',
        tooltip: '回测验证：空头信号在当前行情质量差，维持只做多',
      },
    ],
    notes: [
      '止损和止盈由实时 Ticker 价格触发，无需等待 K 线收盘',
      'RSI 过滤经验证可将收益从 +3.2% 提升到 +7.7%，强烈建议开启',
      '单次开仓资金≤50%，防止单笔交易风险过大',
    ],
  },
  dual_side: {
    label: '双向持仓策略',
    tag: '新策略',
    tagColor: '#1890ff',
    icon: <RiseOutlined />,
    summary:
      '支持多空双向交易的合约策略，基于 EMA 双均线判断趋势方向。金叉开多，死叉开空，趋势反转时自动平仓并反向开仓。支持3x-5x杠杆，适合波动较大的市场。',
    fixedParams: [
      { label: 'EMA 快线', value: '12 根', tooltip: '短期 EMA 周期' },
      { label: 'EMA 慢线', value: '40 根', tooltip: '长期 EMA 周期，代表中期趋势方向' },
      { label: '杠杆', value: '3x-5x', tooltip: '建议使用低杠杆，风险可控' },
      { label: '方向', value: '多空双向', tooltip: '金叉做多，死叉做空' },
    ],
    notes: [
      '支持移动止损，锁定盈利',
      '趋势反转时自动平仓并反向开仓',
      '建议使用3x-5x低杠杆，控制风险',
    ],
  },
}

// ── 交易对列表 ──────────────────────────────────────────────
const DEFAULT_SYMBOLS = [
  'BTC-USDT-SWAP',
  'ETH-USDT-SWAP',
  'SOL-USDT-SWAP',
  'BNB-USDT-SWAP',
  'XRP-USDT-SWAP',
  'DOGE-USDT-SWAP',
  'ADA-USDT-SWAP',
  'AVAX-USDT-SWAP',
  'LINK-USDT-SWAP',
  'DOT-USDT-SWAP',
  'LTC-USDT-SWAP',
  'ATOM-USDT-SWAP',
  'BTC-USDT',
  'ETH-USDT',
  'SOL-USDT',
]

const StrategyCreatePage: React.FC = () => {
  const { type = 'trend' } = useParams<{ type: string }>()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  const meta = STRATEGY_META[type]

  // 可用交易对
  const { data: availableSymbols } = useQuery({
    queryKey: ['available-symbols-create'],
    queryFn: async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/v1/backtest/symbols`)
        if (!res.ok) throw new Error()
        const symbols: string[] = await res.json()
        return [...new Set([...symbols, ...DEFAULT_SYMBOLS])]
      } catch {
        return DEFAULT_SYMBOLS
      }
    },
  })

  if (!meta) {
    return (
      <div style={{ padding: 32 }}>
        <Alert
          message={`未知策略类型: ${type}`}
          description="请从策略列表页重新进入"
          type="error"
          showIcon
          action={<Button onClick={() => navigate('/strategies')}>返回列表</Button>}
        />
      </div>
    )
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setLoading(true)

      const parameters: Record<string, any> = {}
      if (type === 'trend') {
        parameters.position_ratio = (values.position_ratio ?? 40) / 100
        parameters.stop_loss = (values.stop_loss ?? 1) / 100
        parameters.take_profit = (values.take_profit ?? 8) / 100
        parameters.use_rsi_filter = values.use_rsi_filter ?? true
      }

      await strategyApi.create({
        name: values.name,
        type: type as any,
        symbol: values.symbol,
        timeframe: type === 'trend' ? '15m' : '1H',
        parameters,
        description: values.description,
      } as any)

      message.success('策略创建成功')
      navigate('/strategies')
    } catch (err: any) {
      if (err?.errorFields) return
      message.error('创建失败，请检查参数')
    } finally {
      setLoading(false)
    }
  }

  const labelStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  }

  const tipIcon = (text: string) => (
    <Tooltip title={text}>
      <InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} />
    </Tooltip>
  )

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: '24px 24px 48px' }}>
      {/* ── 顶部导航 ── */}
      <Space style={{ marginBottom: 20 }}>
        <Button icon={<ArrowLeftOutlined />} type="text" onClick={() => navigate('/strategies')}>
          返回策略列表
        </Button>
      </Space>

      {/* ── 策略标题卡 ── */}
      <Card
        style={{
          marginBottom: 20,
          background: 'linear-gradient(135deg, #141414 0%, #1a1f2e 100%)',
          border: '1px solid #2a2f3d',
        }}
        styles={{ body: { padding: '24px 28px' } }}
      >
        <Row gutter={16} align="middle">
          <Col>
            <div
              style={{
                width: 52,
                height: 52,
                borderRadius: 12,
                background: '#1677ff22',
                border: '1px solid #1677ff55',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 22,
                color: '#1677ff',
              }}
            >
              {meta.icon}
            </div>
          </Col>
          <Col flex={1}>
            <Space align="center" style={{ marginBottom: 4 }}>
              <Title level={4} style={{ margin: 0, color: '#fff' }}>
                {meta.label}
              </Title>
              <Tag color={meta.tagColor} style={{ marginLeft: 4 }}>
                <CheckCircleFilled style={{ marginRight: 4 }} />
                {meta.tag}
              </Tag>
            </Space>
            <Paragraph style={{ margin: 0, color: '#8c8c8c', fontSize: 13 }}>
              {meta.summary}
            </Paragraph>
          </Col>
        </Row>

        {/* 固定参数展示 */}
        <Divider style={{ borderColor: '#2a2f3d', margin: '20px 0 16px' }} />
        <Row gutter={16}>
          {meta.fixedParams.map((p) => (
            <Col key={p.label} xs={12} sm={6}>
              <div style={{ textAlign: 'center', padding: '8px 0' }}>
                <Text style={{ display: 'block', color: '#8c8c8c', fontSize: 12, marginBottom: 4 }}>
                  {p.label}{' '}
                  <Tooltip title={p.tooltip}>
                    <InfoCircleOutlined style={{ fontSize: 11 }} />
                  </Tooltip>
                </Text>
                <Text strong style={{ color: '#1677ff', fontSize: 15 }}>
                  {p.value}
                </Text>
              </div>
            </Col>
          ))}
        </Row>
      </Card>

      {/* ── 注意事项 ── */}
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 20, fontSize: 13 }}
        description={
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {meta.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        }
      />

      {/* ── 参数表单 ── */}
      <Card
        title="策略配置"
        styles={{ body: { padding: '24px 28px' } }}
        style={{ border: '1px solid #2a2f3d' }}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            symbol: 'BTC-USDT-SWAP',
            position_ratio: 40,
            stop_loss: 1,
            take_profit: 8,
            use_rsi_filter: true,
          }}
        >
          {/* 基础信息 */}
          <Divider orientation="left" style={{ fontSize: 13, color: '#8c8c8c', marginTop: 0 }}>
            基础信息
          </Divider>
          <Row gutter={16}>
            <Col span={24}>
              <Form.Item
                name="name"
                label="策略名称"
                rules={[{ required: true, message: '请输入策略名称' }]}
              >
                <Input placeholder={`如：BTC EMA趋势 01`} size="large" />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item
                name="symbol"
                label={
                  <span style={labelStyle}>
                    交易对 {tipIcon('建议选择合约（SWAP），现货暂不支持做多杠杆')}
                  </span>
                }
                rules={[{ required: true, message: '请选择交易对' }]}
              >
                <Select
                  showSearch
                  size="large"
                  placeholder="选择或搜索交易对，如 BTC-USDT-SWAP"
                  filterOption={(input, option) =>
                    String(option?.value ?? '')
                      .toLowerCase()
                      .includes(input.toLowerCase())
                  }
                >
                  <Select.OptGroup label="合约（SWAP）">
                    {(availableSymbols ?? DEFAULT_SYMBOLS)
                      .filter((s) => s.endsWith('-SWAP'))
                      .map((s) => (
                        <Select.Option key={s} value={s}>
                          {s}
                        </Select.Option>
                      ))}
                  </Select.OptGroup>
                  <Select.OptGroup label="现货（SPOT）">
                    {(availableSymbols ?? DEFAULT_SYMBOLS)
                      .filter((s) => !s.endsWith('-SWAP'))
                      .map((s) => (
                        <Select.Option key={s} value={s}>
                          {s}
                        </Select.Option>
                      ))}
                  </Select.OptGroup>
                </Select>
              </Form.Item>
            </Col>
          </Row>

          {/* 风控参数 */}
          <Divider orientation="left" style={{ fontSize: 13, color: '#8c8c8c' }}>
            风控参数
          </Divider>
          <Row gutter={16}>
            <Col xs={24} sm={8}>
              <Form.Item
                name="position_ratio"
                label={
                  <span style={labelStyle}>
                    仓位比例（%）
                    {tipIcon('每次开仓时使用的可用余额占比。建议不超过 50%，降低单笔风险')}
                  </span>
                }
              >
                <InputNumber
                  min={5}
                  max={90}
                  step={5}
                  suffix="%"
                  size="large"
                  style={{ width: '100%' }}
                />
              </Form.Item>
            </Col>
            <Col xs={24} sm={8}>
              <Form.Item
                name="stop_loss"
                label={
                  <span style={labelStyle}>
                    止损（%）
                    {tipIcon('持仓亏损达到此比例时触发市价平仓（实时 Ticker 价格检测，5秒响应）')}
                  </span>
                }
              >
                <InputNumber
                  min={0.1}
                  max={20}
                  step={0.5}
                  suffix="%"
                  size="large"
                  style={{ width: '100%' }}
                />
              </Form.Item>
            </Col>
            <Col xs={24} sm={8}>
              <Form.Item
                name="take_profit"
                label={
                  <span style={labelStyle}>
                    止盈（%）
                    {tipIcon(
                      '持仓盈利达到此比例时触发市价平仓。回测最优值 8%，过低会被噪音触发，过高等不到',
                    )}
                  </span>
                }
              >
                <InputNumber
                  min={1}
                  max={50}
                  step={1}
                  suffix="%"
                  size="large"
                  style={{ width: '100%' }}
                />
              </Form.Item>
            </Col>
          </Row>

          {/* RSI 过滤 */}
          <Form.Item
            name="use_rsi_filter"
            label={
              <span style={labelStyle}>
                RSI 超买过滤
                {tipIcon(
                  '开启后，金叉信号出现时若 RSI14 ≥ 65（超买区），跳过本次开仓。回测验证将收益从 +3.2% 提升到 +7.7%，强烈建议开启',
                )}
              </span>
            }
            valuePropName="checked"
          >
            <Switch
              checkedChildren="开启（推荐）"
              unCheckedChildren="关闭"
              style={{ minWidth: 100 }}
            />
          </Form.Item>

          {/* 备注 */}
          <Divider orientation="left" style={{ fontSize: 13, color: '#8c8c8c' }}>
            备注
          </Divider>
          <Form.Item name="description">
            <TextArea placeholder="可选：描述策略目标、风控思路、注意事项等" rows={2} />
          </Form.Item>

          {/* 提交 */}
          <Row justify="end" style={{ marginTop: 8 }}>
            <Space>
              <Button size="large" onClick={() => navigate('/strategies')}>
                取消
              </Button>
              <Button type="primary" size="large" loading={loading} onClick={handleSubmit}>
                创建策略
              </Button>
            </Space>
          </Row>
        </Form>
      </Card>
    </div>
  )
}

export default StrategyCreatePage
