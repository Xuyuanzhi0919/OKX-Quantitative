import { useState } from 'react'
import {
  Card,
  Form,
  Input,
  InputNumber,
  Button,
  Select,
  Radio,
  Space,
  Row,
  Col,
  Divider,
  App,
} from 'antd'
import { DollarSign, Tag } from 'lucide-react'
import { orderApi } from '@/services/api'
import { useTranslation } from 'react-i18next'
import { formatPrice, removeTrailingZeros } from '@/utils/format'

const { Option } = Select

interface TradingPanelProps {
  defaultSymbol?: string
  onOrderCreated?: (order: any) => void
}

export default function TradingPanel({
  defaultSymbol = 'BTC-USDT',
  onOrderCreated,
}: TradingPanelProps) {
  const { t } = useTranslation()
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [side, setSide] = useState<'buy' | 'sell'>('buy')
  const [orderType, setOrderType] = useState<string>('limit')

  const handleSubmit = async (values: any) => {
    try {
      setLoading(true)

      const orderData = {
        symbol: values.symbol,
        side: side,
        order_type: values.order_type,
        amount: values.amount,
        price: values.order_type === 'market' ? undefined : values.price,
        td_mode: values.td_mode || 'cash',
        cl_ord_id: values.cl_ord_id,
        tgt_ccy: values.order_type === 'market' ? values.tgt_ccy : undefined,
      }

      const result = await orderApi.create(orderData)
      message.success(t('trading.orderCreated'))
      form.resetFields(['amount', 'price', 'cl_ord_id'])

      if (onOrderCreated) {
        onOrderCreated(result)
      }
    } catch (error) {
      message.error((error as Error).message || t('trading.orderCreatedFailed'))
    } finally {
      setLoading(false)
    }
  }

  const calculateTotal = () => {
    const amount = form.getFieldValue('amount')
    const price = form.getFieldValue('price')

    if (orderType === 'limit' && amount && price) {
      const total = amount * price
      return formatPrice(total)
    }
    return '--'
  }

  const isBuy = side === 'buy'

  return (
    <div>
      <Card
        title={
          <div className="pro-card-header" style={{ margin: 0 }}>
            {t('trading.tradingPanel').toUpperCase()}
          </div>
        }
        variant="borderless"
        size="small"
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            symbol: defaultSymbol,
            order_type: 'limit',
            td_mode: 'cash',
            tgt_ccy: 'quote_ccy',
          }}
          onFinish={handleSubmit}
        >
          {/* 交易对和方向 */}
          <Row gutter={12}>
            <Col span={16}>
              <Form.Item
                label={<span className="pro-card-header">{t('trading.symbol').toUpperCase()}</span>}
                name="symbol"
                rules={[{ required: true, message: t('message.required') }]}
                style={{ marginBottom: 16 }}
              >
                <Select size="large">
                  <Option value="BTC-USDT">BTC-USDT</Option>
                  <Option value="ETH-USDT">ETH-USDT</Option>
                  <Option value="BNB-USDT">BNB-USDT</Option>
                  <Option value="SOL-USDT">SOL-USDT</Option>
                  <Option value="XRP-USDT">XRP-USDT</Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                label={<span className="pro-card-header">{t('trading.mode').toUpperCase()}</span>}
                name="td_mode"
                style={{ marginBottom: 16 }}
              >
                <Select size="large">
                  <Option value="cash">{t('trading.spot').toUpperCase()}</Option>
                  <Option value="isolated">{t('trading.isolated').toUpperCase()}</Option>
                  <Option value="cross">{t('trading.cross').toUpperCase()}</Option>
                </Select>
              </Form.Item>
            </Col>
          </Row>

          {/* 买卖方向 */}
          <Form.Item
            label={<span className="pro-card-header">{t('trading.side').toUpperCase()}</span>}
            style={{ marginBottom: 16 }}
          >
            <Radio.Group
              value={side}
              onChange={(e) => setSide(e.target.value)}
              buttonStyle="solid"
              size="large"
              style={{ width: '100%', display: 'flex' }}
            >
              <Radio.Button
                value="buy"
                style={{
                  flex: 1,
                  textAlign: 'center',
                  height: 48,
                  lineHeight: '48px',
                  fontSize: 16,
                  fontWeight: 600,
                  backgroundColor: side === 'buy' ? '#22c55e' : undefined,
                  borderColor: side === 'buy' ? '#22c55e' : undefined,
                  color: side === 'buy' ? '#fff' : undefined,
                }}
              >
                {t('trading.buy').toUpperCase()}
              </Radio.Button>
              <Radio.Button
                value="sell"
                style={{
                  flex: 1,
                  textAlign: 'center',
                  height: 48,
                  lineHeight: '48px',
                  fontSize: 16,
                  fontWeight: 600,
                  backgroundColor: side === 'sell' ? '#ef4444' : undefined,
                  borderColor: side === 'sell' ? '#ef4444' : undefined,
                  color: side === 'sell' ? '#fff' : undefined,
                }}
              >
                {t('trading.sell').toUpperCase()}
              </Radio.Button>
            </Radio.Group>
          </Form.Item>

          {/* 订单类型 */}
          <Form.Item
            label={<span className="pro-card-header">{t('trading.orderType').toUpperCase()}</span>}
            name="order_type"
            rules={[{ required: true }]}
            style={{ marginBottom: 16 }}
          >
            <Select size="large" onChange={(value) => setOrderType(value)}>
              <Option value="limit">{t('trading.limit').toUpperCase()}</Option>
              <Option value="market">{t('trading.market').toUpperCase()}</Option>
              <Option value="post_only">{t('trading.postOnly').toUpperCase()}</Option>
              <Option value="fok">{t('trading.fok').toUpperCase()}</Option>
              <Option value="ioc">{t('trading.ioc').toUpperCase()}</Option>
            </Select>
          </Form.Item>

          {/* 价格和数量 */}
          <Row gutter={12}>
            {orderType !== 'market' && (
              <Col span={12}>
                <Form.Item
                  label={
                    <span className="pro-card-header">{t('trading.price').toUpperCase()}</span>
                  }
                  name="price"
                  rules={[
                    { required: true, message: t('message.required') },
                    { type: 'number', min: 0 },
                  ]}
                  style={{ marginBottom: 16 }}
                >
                  <InputNumber
                    size="large"
                    style={{ width: '100%' }}
                    placeholder="0.00"
                    prefix={<DollarSign size={14} />}
                    precision={8}
                    step={0.00000001}
                    formatter={(value) => removeTrailingZeros(value)}
                    parser={(value) => (value ? parseFloat(value) : 0)}
                  />
                </Form.Item>
              </Col>
            )}
            <Col span={orderType !== 'market' ? 12 : 24}>
              <Form.Item
                label={<span className="pro-card-header">{t('trading.amount').toUpperCase()}</span>}
                name="amount"
                rules={[
                  { required: true, message: t('message.required') },
                  { type: 'number', min: 0 },
                ]}
                style={{ marginBottom: 16 }}
              >
                <InputNumber
                  size="large"
                  style={{ width: '100%' }}
                  placeholder="0.00000000"
                  prefix={<Tag size={14} />}
                  precision={8}
                />
              </Form.Item>
            </Col>
          </Row>

          {/* 市价单数量单位 */}
          {orderType === 'market' && (
            <Form.Item
              label={<span className="pro-card-header">{t('trading.unit').toUpperCase()}</span>}
              name="tgt_ccy"
              style={{ marginBottom: 16 }}
            >
              <Radio.Group size="large">
                <Radio value="quote_ccy">USDT</Radio>
                <Radio value="base_ccy">BTC</Radio>
              </Radio.Group>
            </Form.Item>
          )}

          {/* 订单总价预览 */}
          {orderType === 'limit' && (
            <div
              style={{
                background: 'rgba(24, 144, 255, 0.1)',
                border: '1px solid rgba(24, 144, 255, 0.2)',
                borderRadius: 4,
                padding: '12px 16px',
                marginBottom: 16,
              }}
            >
              <div
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
              >
                <span style={{ color: '#a3a3a3', fontSize: 12, fontWeight: 600 }}>
                  {t('trading.total').toUpperCase()}
                </span>
                <span
                  className="font-mono"
                  style={{ fontSize: 18, fontWeight: 700, color: '#1890ff' }}
                >
                  {calculateTotal()} USDT
                </span>
              </div>
            </div>
          )}

          <Divider style={{ margin: '16px 0', borderColor: '#2a2a2a' }} />

          {/* 提交按钮 */}
          <Form.Item style={{ marginBottom: 0 }}>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              size="large"
              style={{
                width: '100%',
                height: 56,
                fontSize: 16,
                fontWeight: 700,
                backgroundColor: isBuy ? '#22c55e' : '#ef4444',
                borderColor: isBuy ? '#22c55e' : '#ef4444',
                textTransform: 'uppercase',
              }}
            >
              {loading
                ? t('trading.submitting').toUpperCase()
                : `${(isBuy ? t('trading.buy') : t('trading.sell')).toUpperCase()} ${form.getFieldValue('symbol')}`}
            </Button>
          </Form.Item>
        </Form>
      </Card>

      {/* 风险提示 */}
      <Card
        variant="borderless"
        size="small"
        style={{
          marginTop: 16,
          background: 'rgba(245, 158, 11, 0.1)',
          border: '1px solid rgba(245, 158, 11, 0.2)',
        }}
      >
        <div style={{ display: 'flex', gap: 12 }}>
          <div style={{ color: '#f59e0b', fontSize: 16 }}>⚠️</div>
          <div>
            <div style={{ fontWeight: 600, marginBottom: 4, color: '#f59e0b', fontSize: 12 }}>
              {t('trading.riskWarning').toUpperCase()}
            </div>
            <div style={{ fontSize: 11, color: '#a3a3a3', lineHeight: 1.5 }}>
              {t('trading.riskWarningText')}
            </div>
          </div>
        </div>
      </Card>
    </div>
  )
}
