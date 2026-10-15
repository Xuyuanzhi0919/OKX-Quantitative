import { useState } from 'react'
import { Card, Table, Tag, Space, Button, Input, Select, DatePicker, Row, Col, Tooltip } from 'antd'
import {
  History,
  Search,
  RotateCw,
  Download,
  Filter,
  XCircle,
  CheckCircle,
  Clock,
} from 'lucide-react'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useTranslation } from 'react-i18next'
import { formatPrice, formatQuantityDisplay, formatPercent, formatAmount } from '@/utils/format'

const { RangePicker } = DatePicker

interface OrderHistoryProps {
  symbol?: string
}

// 订单状态枚举
enum OrderStatus {
  LIVE = 'live',
  PARTIALLY_FILLED = 'partially_filled',
  FILLED = 'filled',
  CANCELED = 'canceled',
  FAILED = 'failed',
}

// 订单类型枚举
enum OrderType {
  LIMIT = 'limit',
  MARKET = 'market',
  POST_ONLY = 'post_only',
  FOK = 'fok',
  IOC = 'ioc',
}

export default function OrderHistory({ symbol }: OrderHistoryProps) {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [filterStatus, setFilterStatus] = useState<string>('all')
  const [filterSide, setFilterSide] = useState<string>('all')

  // TODO: 从API获取订单历史
  const orders: any[] = [
    {
      key: '1',
      ordId: 'ORD-2025-001234',
      symbol: 'BTC-USDT',
      side: 'buy',
      orderType: OrderType.LIMIT,
      status: OrderStatus.FILLED,
      price: 43250.5,
      avgPrice: 43248.2,
      amount: 0.05,
      filled: 0.05,
      total: 2162.41,
      fee: 2.16,
      time: Date.now() - 3600000,
    },
    {
      key: '2',
      ordId: 'ORD-2025-001233',
      symbol: 'ETH-USDT',
      side: 'sell',
      orderType: OrderType.MARKET,
      status: OrderStatus.FILLED,
      price: 0,
      avgPrice: 2280.5,
      amount: 1.2,
      filled: 1.2,
      total: 2736.6,
      fee: 2.74,
      time: Date.now() - 7200000,
    },
    {
      key: '3',
      ordId: 'ORD-2025-001232',
      symbol: 'BTC-USDT',
      side: 'buy',
      orderType: OrderType.LIMIT,
      status: OrderStatus.PARTIALLY_FILLED,
      price: 43100.0,
      avgPrice: 43098.5,
      amount: 0.1,
      filled: 0.05,
      total: 4310.0,
      fee: 2.15,
      time: Date.now() - 10800000,
    },
    {
      key: '4',
      ordId: 'ORD-2025-001231',
      symbol: 'SOL-USDT',
      side: 'sell',
      orderType: OrderType.LIMIT,
      status: OrderStatus.CANCELED,
      price: 98.5,
      avgPrice: 0,
      amount: 10,
      filled: 0,
      total: 985.0,
      fee: 0,
      time: Date.now() - 14400000,
    },
  ]

  // 状态配色和文本
  const statusConfig: Record<string, { bg: string; color: string; text: string; icon: any }> = {
    [OrderStatus.LIVE]: {
      bg: 'rgba(24, 144, 255, 0.15)',
      color: '#1890ff',
      text: 'LIVE',
      icon: <Clock size={14} />,
    },
    [OrderStatus.PARTIALLY_FILLED]: {
      bg: 'rgba(245, 158, 11, 0.15)',
      color: '#f59e0b',
      text: 'PARTIAL',
      icon: <Clock size={14} />,
    },
    [OrderStatus.FILLED]: {
      bg: 'rgba(34, 197, 94, 0.15)',
      color: '#22c55e',
      text: 'FILLED',
      icon: <CheckCircle size={14} />,
    },
    [OrderStatus.CANCELED]: {
      bg: 'rgba(115, 115, 115, 0.15)',
      color: '#737373',
      text: 'CANCELED',
      icon: <XCircle size={14} />,
    },
    [OrderStatus.FAILED]: {
      bg: 'rgba(239, 68, 68, 0.15)',
      color: '#ef4444',
      text: 'FAILED',
      icon: <XCircle size={14} />,
    },
  }

  // 订单类型文本
  const orderTypeText: Record<string, string> = {
    [OrderType.LIMIT]: 'LIMIT',
    [OrderType.MARKET]: 'MARKET',
    [OrderType.POST_ONLY]: 'POST ONLY',
    [OrderType.FOK]: 'FOK',
    [OrderType.IOC]: 'IOC',
  }

  const columns: ColumnsType<any> = [
    {
      title: t('trading.time').toUpperCase(),
      dataIndex: 'time',
      key: 'time',
      width: 160,
      render: (time) => (
        <div>
          <div className="font-mono" style={{ fontSize: 12, fontWeight: 600 }}>
            {dayjs(time).format('YYYY-MM-DD')}
          </div>
          <div className="font-mono" style={{ fontSize: 11, color: '#737373' }}>
            {dayjs(time).format('HH:mm:ss')}
          </div>
        </div>
      ),
    },
    {
      title: t('trading.orderId').toUpperCase(),
      dataIndex: 'ordId',
      key: 'ordId',
      width: 150,
      render: (text) => (
        <Tooltip title={text}>
          <span className="font-mono" style={{ fontSize: 11, color: '#a3a3a3' }}>
            {text}
          </span>
        </Tooltip>
      ),
    },
    {
      title: t('trading.symbol').toUpperCase(),
      dataIndex: 'symbol',
      key: 'symbol',
      width: 120,
      render: (text) => (
        <span className="font-mono" style={{ fontWeight: 600, fontSize: 13 }}>
          {text}
        </span>
      ),
    },
    {
      title: t('trading.side').toUpperCase(),
      dataIndex: 'side',
      key: 'side',
      width: 80,
      align: 'center',
      render: (side) => (
        <Tag
          style={{
            margin: 0,
            fontSize: 10,
            padding: '2px 8px',
            fontWeight: 600,
            border: 'none',
            background: side === 'buy' ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)',
            color: side === 'buy' ? '#22c55e' : '#ef4444',
          }}
        >
          {side.toUpperCase()}
        </Tag>
      ),
    },
    {
      title: t('trading.type').toUpperCase(),
      dataIndex: 'orderType',
      key: 'orderType',
      width: 100,
      render: (type) => (
        <Tag
          style={{
            margin: 0,
            fontSize: 10,
            padding: '2px 8px',
            fontWeight: 600,
            border: 'none',
            background: 'rgba(24, 144, 255, 0.15)',
            color: '#1890ff',
          }}
        >
          {orderTypeText[type]}
        </Tag>
      ),
    },
    {
      title: t('trading.status').toUpperCase(),
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (status) => {
        const config = statusConfig[status]
        return (
          <Tag
            icon={config.icon}
            style={{
              margin: 0,
              fontSize: 10,
              padding: '2px 8px',
              fontWeight: 600,
              border: 'none',
              background: config.bg,
              color: config.color,
            }}
          >
            {config.text}
          </Tag>
        )
      },
    },
    {
      title: t('trading.price').toUpperCase(),
      dataIndex: 'price',
      key: 'price',
      width: 110,
      align: 'right',
      render: (price, record) => (
        <span className="font-mono" style={{ fontSize: 13 }}>
          {record.orderType === OrderType.MARKET ? (
            <span style={{ color: '#737373' }}>{t('trading.market').toUpperCase()}</span>
          ) : (
            `$${formatPrice(price)}`
          )}
        </span>
      ),
    },
    {
      title: t('trading.avgPrice').toUpperCase(),
      dataIndex: 'avgPrice',
      key: 'avgPrice',
      width: 110,
      align: 'right',
      render: (price) => (
        <span className="font-mono" style={{ fontSize: 13, fontWeight: 600 }}>
          {price > 0 ? `$${formatPrice(price)}` : '-'}
        </span>
      ),
    },
    {
      title: t('trading.amount').toUpperCase(),
      dataIndex: 'amount',
      key: 'amount',
      width: 120,
      align: 'right',
      render: (amount) => (
        <span className="font-mono" style={{ fontSize: 13 }}>
          {formatQuantityDisplay(amount)}
        </span>
      ),
    },
    {
      title: t('trading.filled').toUpperCase(),
      key: 'filled',
      width: 120,
      align: 'right',
      render: (_, record) => {
        const fillPercent = (record.filled / record.amount) * 100
        return (
          <div>
            <div className="font-mono" style={{ fontSize: 13, marginBottom: 2 }}>
              {formatQuantityDisplay(record.filled)}
            </div>
            <div style={{ fontSize: 10, color: '#737373' }}>{formatPercent(fillPercent, 1)}%</div>
          </div>
        )
      },
    },
    {
      title: t('trading.total').toUpperCase(),
      dataIndex: 'total',
      key: 'total',
      width: 110,
      align: 'right',
      render: (total, record) => {
        const actualTotal = record.avgPrice > 0 ? record.filled * record.avgPrice : 0
        return (
          <span className="font-mono" style={{ fontSize: 13, fontWeight: 600 }}>
            ${actualTotal > 0 ? formatPrice(actualTotal) : '-'}
          </span>
        )
      },
    },
    {
      title: t('trading.fee').toUpperCase(),
      dataIndex: 'fee',
      key: 'fee',
      width: 90,
      align: 'right',
      render: (fee) => (
        <span className="font-mono" style={{ fontSize: 12, color: '#a3a3a3' }}>
          ${formatAmount(fee)}
        </span>
      ),
    },
  ]

  // 过滤订单
  const filteredOrders = orders.filter((order) => {
    const matchSearch =
      searchText === '' ||
      order.ordId.toLowerCase().includes(searchText.toLowerCase()) ||
      order.symbol.toLowerCase().includes(searchText.toLowerCase())

    const matchStatus = filterStatus === 'all' || order.status === filterStatus
    const matchSide = filterSide === 'all' || order.side === filterSide

    return matchSearch && matchStatus && matchSide
  })

  const handleRefresh = () => {
    setLoading(true)
    // TODO: 实际刷新订单数据
    setTimeout(() => setLoading(false), 1000)
  }

  const handleExport = () => {
    // TODO: 导出订单数据
  }

  return (
    <Card
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <History size={14} />
          <div className="pro-card-header" style={{ margin: 0 }}>
            {t('trading.orderHistory').toUpperCase()}
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
            {filteredOrders.length}
          </Tag>
        </div>
      }
      variant="borderless"
      size="small"
      extra={
        <Space size={8}>
          <Button
            type="text"
            size="small"
            icon={<RotateCw size={14} className={loading ? 'spin-animation' : ''} />}
            onClick={handleRefresh}
            style={{ color: '#a3a3a3' }}
          >
            {t('common.refresh')}
          </Button>
          <Button
            type="text"
            size="small"
            icon={<Download size={14} />}
            onClick={handleExport}
            style={{ color: '#a3a3a3' }}
          >
            {t('common.export')}
          </Button>
        </Space>
      }
    >
      {/* 过滤器 */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={12} md={8}>
          <Input
            size="large"
            placeholder={t('trading.searchByOrderIdOrSymbol')}
            prefix={<Search size={14} style={{ color: '#737373' }} />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            allowClear
          />
        </Col>
        <Col xs={12} sm={6} md={4}>
          <Select
            size="large"
            style={{ width: '100%' }}
            value={filterStatus}
            onChange={setFilterStatus}
            options={[
              { label: t('trading.allStatus').toUpperCase(), value: 'all' },
              { label: t('order.status.live').toUpperCase(), value: OrderStatus.LIVE },
              {
                label: t('order.status.partiallyFilled').toUpperCase(),
                value: OrderStatus.PARTIALLY_FILLED,
              },
              { label: t('order.status.filled').toUpperCase(), value: OrderStatus.FILLED },
              { label: t('order.status.canceled').toUpperCase(), value: OrderStatus.CANCELED },
              { label: t('order.status.failed').toUpperCase(), value: OrderStatus.FAILED },
            ]}
          />
        </Col>
        <Col xs={12} sm={6} md={4}>
          <Select
            size="large"
            style={{ width: '100%' }}
            value={filterSide}
            onChange={setFilterSide}
            options={[
              { label: t('trading.allSides').toUpperCase(), value: 'all' },
              { label: t('trading.buy').toUpperCase(), value: 'buy' },
              { label: t('trading.sell').toUpperCase(), value: 'sell' },
            ]}
          />
        </Col>
        <Col xs={24} sm={12} md={8}>
          <RangePicker
            size="large"
            style={{ width: '100%' }}
            format="YYYY-MM-DD"
            placeholder={[t('trading.startDate'), t('trading.endDate')]}
          />
        </Col>
      </Row>

      {/* 订单表格 */}
      <Table
        columns={columns}
        dataSource={filteredOrders}
        loading={loading}
        pagination={{
          pageSize: 20,
          showSizeChanger: true,
          showTotal: (total) => (
            <span style={{ fontSize: 12, color: '#737373' }}>
              {t('trading.totalOrders')}: {total}
            </span>
          ),
        }}
        scroll={{ x: 1400 }}
        size="small"
        locale={{
          emptyText: (
            <div style={{ padding: '40px 0', textAlign: 'center' }}>
              <History size={48} style={{ color: '#2a2a2a', marginBottom: 16 }} />
              <div style={{ color: '#737373', marginBottom: 8 }}>{t('trading.noOrderHistory')}</div>
              <div style={{ fontSize: 12, color: '#525252' }}>
                {t('trading.orderHistoryWillAppearHere')}
              </div>
            </div>
          ),
        }}
      />
    </Card>
  )
}
