import { Card, Table, Tag, Statistic, Row, Col, Empty, Spin } from 'antd'
import { TrendingUp, TrendingDown } from 'lucide-react'
import type { ColumnsType } from 'antd/es/table'
import { useQuery } from '@tanstack/react-query'
import { POSITIONS_API } from '@/config/api'
import dayjs from 'dayjs'
import { formatPrice, formatQuantity, formatAmount, formatPercent } from '@/utils/format'

interface Position {
  id: number
  strategy_id: number
  strategy_name: string
  symbol: string
  side: string
  size: number
  avg_price: number
  current_price: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  margin: number
  liquidation_price?: number
  created_at: string
  updated_at: string
}

const PositionList = () => {
  // 获取持仓列表
  const { data: positions = [], isLoading } = useQuery({
    queryKey: ['positions'],
    queryFn: async () => {
      const response = await fetch(POSITIONS_API.list)
      if (!response.ok) throw new Error('获取持仓列表失败')
      return response.json()
    },
    refetchInterval: 5000, // 每5秒刷新
  })

  const columns: ColumnsType<Position> = [
    {
      title: '策略',
      dataIndex: 'strategy_name',
      key: 'strategy_name',
      width: 150,
      render: (name) => <span style={{ fontWeight: 600 }}>{name}</span>,
    },
    {
      title: '交易对',
      dataIndex: 'symbol',
      key: 'symbol',
      width: 120,
    },
    {
      title: '方向',
      dataIndex: 'side',
      key: 'side',
      width: 80,
      render: (side: string) => (
        <Tag color={side === 'long' ? '#22c55e' : '#ef4444'}>{side === 'long' ? '多' : '空'}</Tag>
      ),
    },
    {
      title: '持仓量',
      dataIndex: 'size',
      key: 'size',
      width: 120,
      align: 'right',
      render: (size: number) => formatQuantity(size),
    },
    {
      title: '持仓均价',
      dataIndex: 'avg_price',
      key: 'avg_price',
      width: 120,
      align: 'right',
      render: (price: number) => formatPrice(price),
    },
    {
      title: '当前价格',
      dataIndex: 'current_price',
      key: 'current_price',
      width: 120,
      align: 'right',
      render: (price: number) => formatPrice(price),
    },
    {
      title: '未实现盈亏',
      key: 'unrealized_pnl',
      width: 150,
      align: 'right',
      render: (_: any, record: Position) => {
        const color = record.unrealized_pnl >= 0 ? '#22c55e' : '#ef4444'
        const icon =
          record.unrealized_pnl >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />
        return (
          <div style={{ color, fontWeight: 600 }}>
            <div>{formatAmount(record.unrealized_pnl)} USDT</div>
            <div style={{ fontSize: 12 }}>
              {icon} {formatPercent(record.unrealized_pnl_pct)}%
            </div>
          </div>
        )
      },
    },
    {
      title: '保证金',
      dataIndex: 'margin',
      key: 'margin',
      width: 120,
      align: 'right',
      render: (margin: number) => `${formatAmount(margin)} USDT`,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 180,
      render: (time: string) => {
        if (!time) return '-'
        // 兼容 OKX 返回的毫秒时间戳字符串（如 "1699000000000"）和 ISO 字符串两种格式
        const ts = Number(time)
        const d = isNaN(ts) ? dayjs(time) : dayjs(ts)
        return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : '-'
      },
    },
  ]

  // 计算总盈亏
  const totalPnl = positions.reduce((sum: number, p: Position) => sum + p.unrealized_pnl, 0)
  const totalMargin = positions.reduce((sum: number, p: Position) => sum + p.margin, 0)
  const avgPnlPct = totalMargin > 0 ? (totalPnl / totalMargin) * 100 : 0

  return (
    <div>
      {/* 持仓概览 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="持仓数量" value={positions.length} suffix="个" />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="总保证金" value={totalMargin} precision={2} suffix="USDT" />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="未实现盈亏"
              value={totalPnl}
              precision={2}
              suffix="USDT"
              valueStyle={{ color: totalPnl >= 0 ? '#22c55e' : '#ef4444' }}
              prefix={totalPnl >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="收益率"
              value={avgPnlPct}
              precision={2}
              suffix="%"
              valueStyle={{ color: avgPnlPct >= 0 ? '#22c55e' : '#ef4444' }}
              prefix={avgPnlPct >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
            />
          </Card>
        </Col>
      </Row>

      {/* 持仓列表 */}
      <Card title="持仓明细">
        <Spin spinning={isLoading}>
          {positions.length === 0 && !isLoading ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无持仓"
              style={{ padding: '40px 0' }}
            />
          ) : (
            <Table
              columns={columns}
              dataSource={positions}
              rowKey="id"
              pagination={{
                pageSize: 20,
                showSizeChanger: true,
                showTotal: (total) => `共 ${total} 条`,
              }}
              scroll={{ x: 1200 }}
            />
          )}
        </Spin>
      </Card>
    </div>
  )
}

export default PositionList
