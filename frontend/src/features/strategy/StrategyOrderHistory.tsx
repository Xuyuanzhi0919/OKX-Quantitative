import { Table, Tag, Empty, Spin } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { ORDERS_API } from '@/config/api'
import dayjs from 'dayjs'
import { formatPriceDisplay, formatQuantityDisplay, formatPercent } from '@/utils/format'
import { wsService, OrderUpdateData } from '@/services/websocket'

interface Order {
  id: string
  order_id: string
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

interface StrategyOrderHistoryProps {
  strategyId: number
}

const StrategyOrderHistory = ({ strategyId }: StrategyOrderHistoryProps) => {
  const queryClient = useQueryClient()

  // 查询该策略的订单
  const { data: orders = [], isLoading } = useQuery({
    queryKey: ['strategy-orders', strategyId],
    queryFn: async () => {
      const params = new URLSearchParams()
      params.append('strategy_id', strategyId.toString())
      params.append('limit', '100')

      const response = await fetch(`${ORDERS_API.list}?${params}`)
      if (!response.ok) throw new Error('获取订单历史失败')
      return response.json()
    },
    refetchInterval: 10000, // 每10秒刷新
  })

  // 订阅WebSocket订单更新
  useEffect(() => {
    // 订阅该策略的订单更新
    const unsubscribe = wsService.onSingleOrderUpdate(strategyId, (orderData: OrderUpdateData) => {
      // 订单状态发生变化，立即刷新订单列表
      queryClient.invalidateQueries({ queryKey: ['strategy-orders', strategyId] })
    })

    return () => {
      unsubscribe()
    }
  }, [strategyId, queryClient])

  const columns: ColumnsType<Order> = [
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
      render: (type: string) => {
        const typeMap: Record<string, string> = {
          limit: '限价',
          market: '市价',
          post_only: '限价-只挂单',
          fok: '限价-FOK',
          ioc: '限价-IOC',
          stop_limit: '止损限价',
          stop_market: '止损市价',
        }
        return <Tag color="blue">{typeMap[type] || type}</Tag>
      },
    },
    {
      title: '价格',
      dataIndex: 'price',
      key: 'price',
      width: 120,
      align: 'right',
      render: (price: number) => {
        if (!price) return '-'
        return formatPriceDisplay(price)
      },
    },
    {
      title: '数量',
      dataIndex: 'size',
      key: 'size',
      width: 100,
      align: 'right',
      render: (size: number) => formatQuantityDisplay(size),
    },
    {
      title: '已成交',
      dataIndex: 'filled_size',
      key: 'filled_size',
      width: 100,
      align: 'right',
      render: (filled: number, record: Order) => (
        <div>
          <div>{formatQuantityDisplay(filled)}</div>
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
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 160,
      render: (time: string) => (time ? dayjs(time).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
  ]

  // 统计数据
  const stats = {
    total: orders.length,
    pending: orders.filter((o: Order) => o.status === 'pending' || o.status === 'partially_filled')
      .length,
    filled: orders.filter((o: Order) => o.status === 'filled').length,
    canceled: orders.filter((o: Order) => o.status === 'canceled').length,
  }

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: '40px' }}>
        <Spin size="large" tip="加载订单历史...">
          <div style={{ minHeight: 60 }} />
        </Spin>
      </div>
    )
  }

  if (orders.length === 0) {
    return (
      <Empty
        description="该策略暂无订单记录"
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        style={{ padding: '40px' }}
      />
    )
  }

  return (
    <div>
      {/* 统计信息 */}
      <div
        style={{
          display: 'flex',
          gap: 16,
          marginBottom: 16,
          padding: 16,
          background: '#fafafa',
          borderRadius: 8,
        }}
      >
        <div>
          <span style={{ color: '#737373' }}>总订单: </span>
          <span style={{ fontWeight: 600, fontSize: 16 }}>{stats.total}</span>
        </div>
        <div>
          <span style={{ color: '#737373' }}>待成交: </span>
          <span style={{ fontWeight: 600, fontSize: 16, color: '#1890ff' }}>{stats.pending}</span>
        </div>
        <div>
          <span style={{ color: '#737373' }}>已成交: </span>
          <span style={{ fontWeight: 600, fontSize: 16, color: '#22c55e' }}>{stats.filled}</span>
        </div>
        <div>
          <span style={{ color: '#737373' }}>已撤销: </span>
          <span style={{ fontWeight: 600, fontSize: 16, color: '#737373' }}>{stats.canceled}</span>
        </div>
      </div>

      {/* 订单表格 */}
      <Table
        columns={columns}
        dataSource={orders}
        rowKey="id"
        pagination={{
          pageSize: 10,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 条`,
        }}
        scroll={{ x: 1000 }}
        size="small"
      />
    </div>
  )
}

export default StrategyOrderHistory
