import { Card, Table, Tag, Button, Space, Select, Row, Col, Statistic, App } from 'antd'
import { RotateCw, Trash2, X, Eye, EyeOff } from 'lucide-react'
import type { ColumnsType } from 'antd/es/table'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ORDERS_API } from '@/config/api'
import dayjs from 'dayjs'
import { formatPrice, formatQuantity, formatPercent } from '@/utils/format'

const { Option } = Select

interface Order {
  id: string // 改为string类型以支持OKX订单ID
  order_id: string // OKX订单ID
  strategy_id?: number
  strategy_name?: string
  symbol: string
  side: string
  order_type: string
  price: number
  size: number
  filled_size: number
  status: string
  created_at: string
  updated_at: string
}

const OrderList = () => {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const [filters, setFilters] = useState({
    symbol: '',
    status: '',
    side: '',
  })
  const [hideCanceled, setHideCanceled] = useState(false)

  // 获取订单列表
  const {
    data: orders = [],
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ['orders', filters],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (filters.symbol) params.append('symbol', filters.symbol)
      if (filters.status) params.append('status', filters.status)
      if (filters.side) params.append('side', filters.side)

      const response = await fetch(`${ORDERS_API.list}?${params}`)
      if (!response.ok) throw new Error('获取订单列表失败')
      return response.json()
    },
    refetchInterval: 10000, // 每10秒刷新
  })

  // 单个撤单
  const cancelOrderMutation = useMutation({
    mutationFn: async ({ orderId, symbol }: { orderId: string; symbol: string }) => {
      const response = await fetch(ORDERS_API.cancel(orderId), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ symbol }),
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || '撤单失败')
      }
      return response.json()
    },
    onSuccess: () => {
      message.success('撤单成功')
      queryClient.invalidateQueries({ queryKey: ['orders'] })
    },
    onError: (error: Error) => {
      message.error(`撤单失败: ${error.message}`)
    },
  })

  // 一键撤单（批量撤销所有待成交订单）
  const cancelAllMutation = useMutation({
    mutationFn: async () => {
      const pendingOrders = orders.filter(
        (o: Order) => o.status === 'pending' || o.status === 'partially_filled',
      )

      if (pendingOrders.length === 0) {
        throw new Error('没有待撤销的订单')
      }

      const results = await Promise.allSettled(
        pendingOrders.map((order: Order) =>
          fetch(ORDERS_API.cancel(order.id), {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ symbol: order.symbol }),
          }).then(async (res) => {
            if (!res.ok) {
              const error = await res.json()
              throw new Error(error.detail || `撤销订单${order.id}失败`)
            }
            return res.json()
          }),
        ),
      )

      const failed = results.filter((r) => r.status === 'rejected')
      const succeeded = results.length - failed.length

      return { succeeded, failed: failed.length, total: results.length }
    },
    onSuccess: (result) => {
      if (result.failed > 0) {
        message.warning(`撤单完成: 成功${result.succeeded}个，失败${result.failed}个`)
      } else {
        message.success(`成功撤销${result.succeeded}个订单`)
      }
      queryClient.invalidateQueries({ queryKey: ['orders'] })
    },
    onError: (error: Error) => {
      message.error(error.message)
    },
  })

  const columns: ColumnsType<Order> = [
    {
      title: '策略',
      dataIndex: 'strategy_name',
      key: 'strategy_name',
      width: 120,
      render: (name) => name || '-',
    },
    {
      title: '交易对',
      dataIndex: 'symbol',
      key: 'symbol',
      width: 100,
    },
    {
      title: '方向',
      dataIndex: 'side',
      key: 'side',
      width: 70,
      render: (side: string) => (
        <Tag color={side === 'buy' ? '#22c55e' : '#ef4444'}>{side === 'buy' ? '买入' : '卖出'}</Tag>
      ),
    },
    {
      title: '类型',
      dataIndex: 'order_type',
      key: 'order_type',
      width: 80,
      render: (type: string) => <Tag color="blue">{type === 'limit' ? '限价' : '市价'}</Tag>,
    },
    {
      title: '价格',
      dataIndex: 'price',
      key: 'price',
      width: 100,
      align: 'right',
      render: (price: number) => formatPrice(price),
    },
    {
      title: '数量',
      dataIndex: 'size',
      key: 'size',
      width: 100,
      align: 'right',
      render: (size: number) => formatQuantity(size),
    },
    {
      title: '已成交',
      dataIndex: 'filled_size',
      key: 'filled_size',
      width: 100,
      align: 'right',
      render: (filled: number, record: Order) => (
        <div>
          <div>{formatQuantity(filled)}</div>
          <div style={{ fontSize: 12, color: '#737373' }}>
            {formatPercent((filled / record.size) * 100, 1)}%
          </div>
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const statusConfig: Record<string, { color: string; text: string }> = {
          pending: { color: 'default', text: '待成交' },
          partially_filled: { color: 'processing', text: '部分成交' },
          filled: { color: 'success', text: '已成交' },
          canceled: { color: 'default', text: '已撤销' },
          failed: { color: 'error', text: '失败' },
        }
        const config = statusConfig[status] || { color: 'default', text: status }
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (time: string) => dayjs(time).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      fixed: 'right',
      render: (_: any, record: Order) =>
        record.status === 'pending' || record.status === 'partially_filled' ? (
          <Button
            type="link"
            size="small"
            danger
            loading={cancelOrderMutation.isPending}
            onClick={() => {
              modal.confirm({
                title: '确认撤单',
                content: `确定要撤销订单吗?`,
                onOk: () =>
                  cancelOrderMutation.mutate({ orderId: record.id, symbol: record.symbol }),
              })
            }}
          >
            撤单
          </Button>
        ) : null,
    },
  ]

  // 根据hideCanceled状态过滤订单
  const filteredOrders = hideCanceled
    ? orders.filter((o: Order) => o.status !== 'canceled')
    : orders

  // 统计数据
  const stats = {
    total: filteredOrders.length,
    pending: filteredOrders.filter(
      (o: Order) => o.status === 'pending' || o.status === 'partially_filled',
    ).length,
    filled: filteredOrders.filter((o: Order) => o.status === 'filled').length,
    canceled: filteredOrders.filter((o: Order) => o.status === 'canceled').length,
  }

  return (
    <div>
      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="总订单" value={stats.total} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="待成交" value={stats.pending} valueStyle={{ color: '#1890ff' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="已成交" value={stats.filled} valueStyle={{ color: '#22c55e' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="已撤销" value={stats.canceled} valueStyle={{ color: '#737373' }} />
          </Card>
        </Col>
      </Row>

      {/* 订单列表 */}
      <Card
        title="订单列表"
        extra={
          <Space>
            <Select
              placeholder="选择交易对"
              style={{ width: 120 }}
              allowClear
              value={filters.symbol || undefined}
              onChange={(value) => setFilters({ ...filters, symbol: value || '' })}
            >
              <Option value="BTC-USDT">BTC-USDT</Option>
              <Option value="ETH-USDT">ETH-USDT</Option>
            </Select>
            <Select
              placeholder="选择状态"
              style={{ width: 120 }}
              allowClear
              value={filters.status || undefined}
              onChange={(value) => setFilters({ ...filters, status: value || '' })}
            >
              <Option value="pending">待成交</Option>
              <Option value="filled">已成交</Option>
              <Option value="canceled">已撤销</Option>
            </Select>
            <Select
              placeholder="买卖方向"
              style={{ width: 100 }}
              allowClear
              value={filters.side || undefined}
              onChange={(value) => setFilters({ ...filters, side: value || '' })}
            >
              <Option value="buy">买入</Option>
              <Option value="sell">卖出</Option>
            </Select>
            <Button
              icon={hideCanceled ? <EyeOff size={14} /> : <Eye size={14} />}
              type={hideCanceled ? 'primary' : 'default'}
              onClick={() => setHideCanceled(!hideCanceled)}
            >
              {hideCanceled ? '已隐藏撤销' : '显示全部'}
            </Button>
            <Button
              type="primary"
              danger
              icon={<X size={14} />}
              loading={cancelAllMutation.isPending}
              disabled={stats.pending === 0}
              onClick={() => {
                modal.confirm({
                  title: '确认一键撤单',
                  content: `确定要撤销所有待成交订单吗? (共${stats.pending}个)`,
                  okText: '确认撤单',
                  cancelText: '取消',
                  okButtonProps: { danger: true },
                  onOk: () => cancelAllMutation.mutate(),
                })
              }}
            >
              一键撤单 ({stats.pending})
            </Button>
            <Button icon={<RotateCw size={14} />} onClick={() => refetch()}>
              刷新
            </Button>
          </Space>
        }
      >
        <Table
          columns={columns}
          dataSource={filteredOrders}
          rowKey="id"
          loading={isLoading}
          pagination={{
            pageSize: 20,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
          }}
          scroll={{ x: 1200 }}
        />
      </Card>
    </div>
  )
}

export default OrderList
