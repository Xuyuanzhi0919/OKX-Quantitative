import { Card, Row, Col, Statistic, Progress, Tag, Spin } from 'antd'
import { TrendingUp, TrendingDown, Zap } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { STRATEGY_API } from '@/config/api'
import { useEffect } from 'react'
import { wsService } from '@/services/websocket'
import { formatAmount, formatQuantityDisplay } from '@/utils/format'

interface StrategyStatsCardProps {
  strategyId: number
  strategyName: string
  symbol: string
}

interface StrategyStats {
  strategy_id: number
  is_running: boolean
  position_size?: number
  position_cost?: number
  realized_pnl?: number
  total_trades?: number
  total_buy_volume?: number
  total_sell_volume?: number
  grid_orders?: number
}

const StrategyStatsCard = ({ strategyId, strategyName, symbol }: StrategyStatsCardProps) => {
  // 获取策略统计数据
  const {
    data: stats,
    isLoading,
    refetch,
  } = useQuery<StrategyStats>({
    queryKey: ['strategy-stats', strategyId],
    queryFn: async () => {
      const response = await fetch(STRATEGY_API.stats(strategyId))
      if (!response.ok) throw new Error('获取策略统计失败')
      return response.json()
    },
    refetchInterval: 5000, // 每5秒刷新一次
    enabled: true,
  })

  // 监听WebSocket策略更新
  useEffect(() => {
    const unsubscribe = wsService.onStrategyUpdate((data) => {
      if (data.strategy_id === strategyId) {
        refetch() // 收到策略更新时,刷新数据
      }
    })

    return () => {
      unsubscribe()
    }
  }, [strategyId, refetch])

  if (isLoading || !stats) {
    return (
      <Card>
        <Spin />
      </Card>
    )
  }

  const pnl = stats.realized_pnl || 0
  const positionSize = stats.position_size || 0
  const positionCost = stats.position_cost || 0
  const totalTrades = stats.total_trades || 0
  const gridOrders = stats.grid_orders || 0

  return (
    <Card
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Zap size={14} style={{ color: '#1890ff' }} />
          <span>{strategyName}</span>
          <Tag color={stats.is_running ? '#22c55e' : '#737373'}>
            {stats.is_running ? '运行中' : '已停止'}
          </Tag>
        </div>
      }
      extra={<span style={{ color: '#737373', fontSize: 14 }}>{symbol}</span>}
      size="small"
    >
      <Row gutter={[16, 16]}>
        <Col span={8}>
          <Statistic
            title="已实现盈亏"
            value={pnl}
            precision={2}
            suffix="USDT"
            valueStyle={{
              color: pnl >= 0 ? '#22c55e' : '#ef4444',
              fontSize: 20,
              fontWeight: 600,
            }}
            prefix={pnl >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
          />
        </Col>
        <Col span={8}>
          <Statistic
            title="持仓数量"
            value={positionSize}
            precision={8}
            valueStyle={{ fontSize: 18 }}
          />
          {positionCost > 0 && (
            <div style={{ marginTop: 4, fontSize: 12, color: '#737373' }}>
              成本: {formatAmount(positionCost)} USDT
            </div>
          )}
        </Col>
        <Col span={8}>
          <Statistic title="总交易次数" value={totalTrades} valueStyle={{ fontSize: 18 }} />
        </Col>
      </Row>

      {stats.is_running && gridOrders !== undefined && (
        <div style={{ marginTop: 16 }}>
          <div style={{ marginBottom: 8, fontSize: 12, color: '#a3a3a3' }}>
            活跃网格订单: {gridOrders}
          </div>
          <Progress
            percent={gridOrders > 0 ? 100 : 0}
            showInfo={false}
            strokeColor="#1890ff"
            size="small"
          />
        </div>
      )}

      {stats.total_buy_volume !== undefined && stats.total_sell_volume !== undefined && (
        <Row gutter={16} style={{ marginTop: 16 }}>
          <Col span={12}>
            <div style={{ fontSize: 12, color: '#a3a3a3', marginBottom: 4 }}>累计买入</div>
            <div style={{ fontSize: 14, color: '#22c55e', fontWeight: 600 }}>
              {formatQuantityDisplay(stats.total_buy_volume)}
            </div>
          </Col>
          <Col span={12}>
            <div style={{ fontSize: 12, color: '#a3a3a3', marginBottom: 4 }}>累计卖出</div>
            <div style={{ fontSize: 14, color: '#ef4444', fontWeight: 600 }}>
              {formatQuantityDisplay(stats.total_sell_volume)}
            </div>
          </Col>
        </Row>
      )}
    </Card>
  )
}

export default StrategyStatsCard
