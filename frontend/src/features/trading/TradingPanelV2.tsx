/**
 * 优化版交易面板组件 - 更符合用户购买逻辑
 */
import { useState, useEffect } from 'react'
import {
  Card,
  Tabs,
  Form,
  InputNumber,
  Button,
  Space,
  Divider,
  Alert,
  Row,
  Col,
  Switch,
  App,
} from 'antd'
import { ShoppingCart, DollarSign, Info } from 'lucide-react'
import { orderApi, marketApi, accountApi } from '@/services/api'
import { formatAmount, formatQuantityDisplay, formatPriceDisplay } from '@/utils/format'

interface TradingPanelV2Props {
  defaultSymbol?: string
  onOrderCreated?: (order: any) => void
}

export default function TradingPanelV2({
  defaultSymbol = 'BTC-USDT',
  onOrderCreated,
}: TradingPanelV2Props) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<'buy' | 'sell'>('buy')
  const [currentPrice, setCurrentPrice] = useState(0)
  const [balance, setBalance] = useState<any>(null)
  const [useMarketPrice, setUseMarketPrice] = useState(true)

  // 获取当前价格
  useEffect(() => {
    const fetchPrice = async () => {
      try {
        const ticker = await marketApi.getTicker(defaultSymbol)
        const price = parseFloat((ticker as any)?.last || '0')
        setCurrentPrice(price)

        if (useMarketPrice) {
          form.setFieldsValue({ price })
        }
      } catch (error) {
        // 价格获取失败
      }
    }

    fetchPrice()
    const timer = setInterval(fetchPrice, 3000)
    return () => clearInterval(timer)
  }, [defaultSymbol, useMarketPrice])

  // 获取账户余额
  useEffect(() => {
    const fetchBalance = async () => {
      try {
        const data = await accountApi.getBalance()
        setBalance(data)
      } catch (error) {
        // 余额获取失败
      }
    }

    fetchBalance()
  }, [])

  // 计算预计花费 / 预计获得
  const calculateTotal = () => {
    const amount = form.getFieldValue('amount') || 0
    const price = form.getFieldValue('price') || currentPrice
    return formatAmount(amount * price)
  }

  // 计算可用余额
  const getAvailableBalance = () => {
    if (!balance) return 0

    if (activeTab === 'buy') {
      // 买入时显示 USDT 余额
      const details = balance.details || []
      const usdtBalance = details.find((d: any) => d.ccy === 'USDT')
      return parseFloat(usdtBalance?.availBal || '0')
    } else {
      // 卖出时显示 BTC 余额
      const coin = defaultSymbol.split('-')[0] // BTC-USDT => BTC
      const details = balance.details || []
      const coinBalance = details.find((d: any) => d.ccy === coin)
      return parseFloat(coinBalance?.availBal || '0')
    }
  }

  // 快速填充数量 (按可用余额的百分比)
  const quickFill = (percent: number) => {
    const available = getAvailableBalance()
    const price = form.getFieldValue('price') || currentPrice

    let amount = 0
    if (activeTab === 'buy') {
      // 买入: 可用余额 * 百分比 / 价格
      amount = (available * percent) / 100 / price
    } else {
      // 卖出: 可用余额 * 百分比
      amount = (available * percent) / 100
    }

    form.setFieldsValue({ amount: formatQuantityDisplay(amount) })
  }

  const handleSubmit = async (values: any) => {
    try {
      setLoading(true)

      const orderData = {
        symbol: defaultSymbol,
        side: activeTab,
        order_type: (useMarketPrice ? 'market' : 'limit') as 'market' | 'limit',
        amount: values.amount,
        price: useMarketPrice ? undefined : values.price,
        td_mode: 'cash' as 'cash',
        tgt_ccy: useMarketPrice ? ('quote_ccy' as 'quote_ccy') : undefined,
      }

      const result = await orderApi.create(orderData)

      message.success(`${activeTab === 'buy' ? '买入' : '卖出'}订单创建成功!`)
      form.resetFields(['amount'])

      if (onOrderCreated) {
        onOrderCreated(result)
      }
    } catch (error) {
      message.error((error as Error).message || '创建订单失败')
    } finally {
      setLoading(false)
    }
  }

  const tabItems = [
    {
      key: 'buy',
      label: <span style={{ color: '#00c087', fontWeight: 600 }}>买入</span>,
      children: (
        <Form
          form={form}
          layout="vertical"
          initialValues={{ price: currentPrice }}
          onFinish={handleSubmit}
        >
          {/* 可用余额 */}
          <Alert
            message={
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <span style={{ fontSize: 12, color: '#9ca3af' }}>可用余额</span>
                <span style={{ fontSize: 20, fontWeight: 'bold', color: '#e5e7eb' }}>
                  {formatAmount(getAvailableBalance())} USDT
                </span>
              </Space>
            }
            type="info"
            style={{ marginBottom: 16, background: '#1f2937' }}
          />

          {/* 当前价格 */}
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={18}>
              <div style={{ fontSize: 12, color: '#9ca3af', marginBottom: 4 }}>当前价格</div>
              <div style={{ fontSize: 24, fontWeight: 'bold', color: '#e5e7eb' }}>
                ${formatPriceDisplay(currentPrice)}
              </div>
            </Col>
            <Col span={6} style={{ display: 'flex', alignItems: 'center' }}>
              <Space direction="vertical" size={0}>
                <span style={{ fontSize: 12, color: '#9ca3af' }}>市价</span>
                <Switch
                  checked={useMarketPrice}
                  onChange={setUseMarketPrice}
                  style={{ backgroundColor: useMarketPrice ? '#00c087' : undefined }}
                />
              </Space>
            </Col>
          </Row>

          {/* 买入价格 */}
          {!useMarketPrice && (
            <Form.Item
              label="买入价格 (USDT)"
              name="price"
              rules={[
                { required: true, message: '请输入买入价格' },
                { type: 'number', min: 0, message: '价格必须大于0' },
              ]}
            >
              <InputNumber
                size="large"
                style={{ width: '100%' }}
                placeholder="请输入价格"
                prefix={<DollarSign size={14} />}
                precision={2}
              />
            </Form.Item>
          )}

          {/* 买入数量 */}
          <Form.Item
            label={`买入数量 (${defaultSymbol.split('-')[0]})`}
            name="amount"
            rules={[
              { required: true, message: '请输入买入数量' },
              { type: 'number', min: 0.00000001, message: '数量必须大于0' },
            ]}
          >
            <InputNumber
              size="large"
              style={{ width: '100%' }}
              placeholder="请输入数量"
              precision={8}
            />
          </Form.Item>

          {/* 快速填充按钮 */}
          <Space style={{ width: '100%', marginBottom: 16 }}>
            {[25, 50, 75, 100].map((percent) => (
              <Button
                key={percent}
                size="small"
                onClick={() => quickFill(percent)}
                style={{ flex: 1 }}
              >
                {percent}%
              </Button>
            ))}
          </Space>

          {/* 预计花费 */}
          <Alert
            message={
              <Row>
                <Col span={12}>
                  <span style={{ color: '#9ca3af' }}>预计花费</span>
                </Col>
                <Col span={12} style={{ textAlign: 'right' }}>
                  <span style={{ fontSize: 18, fontWeight: 'bold', color: '#3b82f6' }}>
                    {calculateTotal()} USDT
                  </span>
                </Col>
              </Row>
            }
            type="info"
            style={{ marginBottom: 16 }}
          />

          <Divider style={{ margin: '16px 0' }} />

          {/* 买入按钮 */}
          <Form.Item style={{ marginBottom: 0 }}>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              style={{
                width: '100%',
                height: 48,
                fontSize: 16,
                fontWeight: 600,
                backgroundColor: '#00c087',
                borderColor: '#00c087',
              }}
            >
              {loading ? '提交中...' : `买入 ${defaultSymbol.split('-')[0]}`}
            </Button>
          </Form.Item>
        </Form>
      ),
    },
    {
      key: 'sell',
      label: <span style={{ color: '#ef5350', fontWeight: 600 }}>卖出</span>,
      children: (
        <Form
          form={form}
          layout="vertical"
          initialValues={{ price: currentPrice }}
          onFinish={handleSubmit}
        >
          {/* 可用余额 */}
          <Alert
            message={
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <span style={{ fontSize: 12, color: '#9ca3af' }}>可用余额</span>
                <span style={{ fontSize: 20, fontWeight: 'bold', color: '#e5e7eb' }}>
                  {formatQuantityDisplay(getAvailableBalance())} {defaultSymbol.split('-')[0]}
                </span>
              </Space>
            }
            type="warning"
            style={{ marginBottom: 16, background: '#1f2937' }}
          />

          {/* 当前价格 */}
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={18}>
              <div style={{ fontSize: 12, color: '#9ca3af', marginBottom: 4 }}>当前价格</div>
              <div style={{ fontSize: 24, fontWeight: 'bold', color: '#e5e7eb' }}>
                ${formatPriceDisplay(currentPrice)}
              </div>
            </Col>
            <Col span={6} style={{ display: 'flex', alignItems: 'center' }}>
              <Space direction="vertical" size={0}>
                <span style={{ fontSize: 12, color: '#9ca3af' }}>市价</span>
                <Switch
                  checked={useMarketPrice}
                  onChange={setUseMarketPrice}
                  style={{ backgroundColor: useMarketPrice ? '#ef5350' : undefined }}
                />
              </Space>
            </Col>
          </Row>

          {/* 卖出价格 */}
          {!useMarketPrice && (
            <Form.Item
              label="卖出价格 (USDT)"
              name="price"
              rules={[
                { required: true, message: '请输入卖出价格' },
                { type: 'number', min: 0, message: '价格必须大于0' },
              ]}
            >
              <InputNumber
                size="large"
                style={{ width: '100%' }}
                placeholder="请输入价格"
                prefix={<DollarSign size={14} />}
                precision={2}
              />
            </Form.Item>
          )}

          {/* 卖出数量 */}
          <Form.Item
            label={`卖出数量 (${defaultSymbol.split('-')[0]})`}
            name="amount"
            rules={[
              { required: true, message: '请输入卖出数量' },
              { type: 'number', min: 0.00000001, message: '数量必须大于0' },
            ]}
          >
            <InputNumber
              size="large"
              style={{ width: '100%' }}
              placeholder="请输入数量"
              precision={8}
            />
          </Form.Item>

          {/* 快速填充按钮 */}
          <Space style={{ width: '100%', marginBottom: 16 }}>
            {[25, 50, 75, 100].map((percent) => (
              <Button
                key={percent}
                size="small"
                onClick={() => quickFill(percent)}
                style={{ flex: 1 }}
              >
                {percent}%
              </Button>
            ))}
          </Space>

          {/* 预计获得 */}
          <Alert
            message={
              <Row>
                <Col span={12}>
                  <span style={{ color: '#9ca3af' }}>预计获得</span>
                </Col>
                <Col span={12} style={{ textAlign: 'right' }}>
                  <span style={{ fontSize: 18, fontWeight: 'bold', color: '#3b82f6' }}>
                    {calculateTotal()} USDT
                  </span>
                </Col>
              </Row>
            }
            type="info"
            style={{ marginBottom: 16 }}
          />

          <Divider style={{ margin: '16px 0' }} />

          {/* 卖出按钮 */}
          <Form.Item style={{ marginBottom: 0 }}>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              style={{
                width: '100%',
                height: 48,
                fontSize: 16,
                fontWeight: 600,
                backgroundColor: '#ef5350',
                borderColor: '#ef5350',
              }}
            >
              {loading ? '提交中...' : `卖出 ${defaultSymbol.split('-')[0]}`}
            </Button>
          </Form.Item>
        </Form>
      ),
    },
  ]

  return (
    <Card
      title={
        <Space>
          <ShoppingCart size={14} />
          <span>现货交易</span>
        </Space>
      }
      extra={
        <span style={{ fontSize: 14, fontWeight: 600, color: '#3b82f6' }}>{defaultSymbol}</span>
      }
    >
      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as 'buy' | 'sell')}
        items={tabItems}
        centered
      />

      {/* 风险提示 */}
      <Alert
        message="风险提示"
        description="数字货币交易有风险,投资需谨慎。请确保您了解市场风险。"
        type="warning"
        showIcon
        icon={<Info size={14} />}
        style={{ marginTop: 16, fontSize: 12 }}
      />
    </Card>
  )
}
