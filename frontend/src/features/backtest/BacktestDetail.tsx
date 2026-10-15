import { useParams, useNavigate } from 'react-router-dom'
import {
  Card,
  Descriptions,
  Statistic,
  Row,
  Col,
  Table,
  Button,
  Tag,
  Spin,
  Empty,
  Space,
  App,
  Alert,
} from 'antd'
import { ArrowLeft, Rocket } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import EquityCurve from './components/EquityCurve'
import StrategyCreateModal from '@/features/strategy/StrategyCreateModal'
import { BACKTEST_API } from '@/config/api'
import {
  formatAmount,
  formatQuantityDisplay,
  formatFeeDisplay,
  formatPercent,
} from '@/utils/format'

interface BacktestDetail {
  id: number
  name: string
  description?: string
  strategy_type: string
  symbol: string
  interval: string
  status: string
  start_time: number
  end_time: number
  initial_capital: number
  final_capital?: number
  total_return?: number
  annualized_return?: number
  max_drawdown?: number
  sharpe_ratio?: number
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate?: number
  profit_factor?: number
  total_fee?: number
  equity_curve?: Array<{ timestamp: number; equity: number; drawdown?: number }>
  error_message?: string
  parameters?: Record<string, any>
  created_at: string
  completed_at?: string
}

interface Trade {
  timestamp: number
  side: string
  price: number
  amount: number
  fee: number
  pnl?: number
  pnl_percent?: number
}

const BacktestDetail = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [createModalOpen, setCreateModalOpen] = useState(false)

  // 获取回测详情
  const { data: backtest, isLoading } = useQuery<BacktestDetail>({
    queryKey: ['backtest', id],
    queryFn: async () => {
      const response = await fetch(BACKTEST_API.detail(id!))
      if (!response.ok) throw new Error('获取回测详情失败')
      return response.json()
    },
  })

  // 获取交易记录
  const { data: trades, isLoading: tradesLoading } = useQuery<Trade[]>({
    queryKey: ['backtest-trades', id],
    queryFn: async () => {
      const response = await fetch(BACKTEST_API.trades(id!))
      if (!response.ok) throw new Error('获取交易记录失败')
      return response.json()
    },
  })

  const tradeColumns: ColumnsType<Trade> = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      key: 'timestamp',
      render: (ts: number) => dayjs(ts).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '方向',
      dataIndex: 'side',
      key: 'side',
      render: (side: string) => (
        <Tag color={side === 'buy' ? 'green' : 'red'}>{side === 'buy' ? '买入' : '卖出'}</Tag>
      ),
    },
    {
      title: '价格',
      dataIndex: 'price',
      key: 'price',
      render: (price: number) => formatAmount(price),
    },
    {
      title: '数量',
      dataIndex: 'amount',
      key: 'amount',
      render: (amount: number) => formatQuantityDisplay(amount),
    },
    {
      title: '手续费',
      dataIndex: 'fee',
      key: 'fee',
      render: (fee: number) => formatFeeDisplay(fee),
    },
    {
      title: '盈亏',
      dataIndex: 'pnl',
      key: 'pnl',
      render: (pnl?: number) => {
        if (pnl === undefined || pnl === null) return '-'
        const color = pnl >= 0 ? '#52c41a' : '#ff4d4f'
        return <span style={{ color }}>{formatAmount(pnl)}</span>
      },
    },
    {
      title: '盈亏比例',
      dataIndex: 'pnl_percent',
      key: 'pnl_percent',
      render: (percent?: number) => {
        if (percent === undefined || percent === null) return '-'
        const color = percent >= 0 ? '#52c41a' : '#ff4d4f'
        return <span style={{ color }}>{formatPercent(percent * 100)}%</span>
      },
    },
  ]

  if (isLoading) {
    return (
      <div style={{ padding: '24px', textAlign: 'center' }}>
        <Spin size="large" tip="加载中...">
          <div style={{ minHeight: 60 }} />
        </Spin>
      </div>
    )
  }

  if (!backtest) {
    return (
      <div style={{ padding: '24px' }}>
        <Empty description="回测不存在" />
      </div>
    )
  }

  return (
    <div style={{ padding: '24px' }}>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeft size={14} />} onClick={() => navigate('/backtest')}>
          返回列表
        </Button>
        {backtest.status === 'completed' && (
          <Button
            type="primary"
            icon={<Rocket size={14} />}
            onClick={() => setCreateModalOpen(true)}
          >
            创建实盘策略
          </Button>
        )}
      </Space>

      {/* 基本信息 */}
      <Card title="回测信息" style={{ marginBottom: 16 }}>
        <Descriptions column={2}>
          <Descriptions.Item label="名称">{backtest.name}</Descriptions.Item>
          <Descriptions.Item label="策略类型">
            {(() => {
              const names: Record<string, string> = {
                grid: '网格策略',
                grid_mm: '网格做市',
                ma_cross: '均线交叉',
                dual_ma_cross: '双均线(多空)',
                adaptive_grid_trend: '自适应趋势网格',
              }
              return names[backtest.strategy_type] || backtest.strategy_type
            })()}
          </Descriptions.Item>
          <Descriptions.Item label="交易对">{backtest.symbol}</Descriptions.Item>
          <Descriptions.Item label="K线周期">{backtest.interval}</Descriptions.Item>
          <Descriptions.Item label="开始时间">
            {dayjs(backtest.start_time).format('YYYY-MM-DD HH:mm:ss')}
          </Descriptions.Item>
          <Descriptions.Item label="结束时间">
            {dayjs(backtest.end_time).format('YYYY-MM-DD HH:mm:ss')}
          </Descriptions.Item>
          <Descriptions.Item label="初始资金">
            {formatAmount(backtest.initial_capital) || '0'} USDT
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag
              color={
                backtest.status === 'completed'
                  ? 'success'
                  : backtest.status === 'failed'
                    ? 'error'
                    : backtest.status === 'running'
                      ? 'processing'
                      : 'default'
              }
            >
              {backtest.status === 'completed'
                ? '已完成'
                : backtest.status === 'failed'
                  ? '失败'
                  : backtest.status === 'running'
                    ? '运行中'
                    : backtest.status}
            </Tag>
          </Descriptions.Item>
          {backtest.description && (
            <Descriptions.Item label="备注" span={2}>
              {backtest.description}
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      {/* 失败原因 */}
      {backtest.status === 'failed' && (
        <Alert
          type="error"
          showIcon
          message="回测执行失败"
          description={backtest.error_message || '未知错误，请查看后端日志'}
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 性能指标 */}
      {backtest.status === 'completed' && (
        <Card title="性能指标" style={{ marginBottom: 16 }}>
          <Row gutter={16}>
            <Col span={6}>
              <Statistic
                title="最终资金"
                value={backtest.final_capital}
                precision={2}
                suffix="USDT"
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="总收益率"
                value={(backtest.total_return || 0) * 100}
                precision={2}
                suffix="%"
                valueStyle={{
                  color: (backtest.total_return || 0) >= 0 ? '#52c41a' : '#ff4d4f',
                }}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="年化收益率"
                value={(backtest.annualized_return || 0) * 100}
                precision={2}
                suffix="%"
                valueStyle={{
                  color: (backtest.annualized_return || 0) >= 0 ? '#52c41a' : '#ff4d4f',
                }}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="最大回撤"
                value={(backtest.max_drawdown || 0) * 100}
                precision={2}
                suffix="%"
                valueStyle={{ color: '#ff4d4f' }}
              />
            </Col>
          </Row>
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={6}>
              <Statistic title="夏普比率" value={backtest.sharpe_ratio} precision={2} />
            </Col>
            <Col span={6}>
              <Statistic title="总交易次数" value={backtest.total_trades} />
            </Col>
            <Col span={6}>
              <Statistic
                title="胜率"
                value={(backtest.win_rate || 0) * 100}
                precision={2}
                suffix="%"
              />
            </Col>
            <Col span={6}>
              <Statistic title="盈亏比" value={backtest.profit_factor} precision={2} />
            </Col>
          </Row>
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={6}>
              <Statistic title="盈利次数" value={backtest.winning_trades} />
            </Col>
            <Col span={6}>
              <Statistic title="亏损次数" value={backtest.losing_trades} />
            </Col>
            <Col span={6}>
              <Statistic title="总手续费" value={backtest.total_fee} precision={4} suffix="USDT" />
            </Col>
          </Row>
        </Card>
      )}

      {/* 资金曲线 */}
      {backtest.status === 'completed' && backtest.equity_curve && (
        <EquityCurve
          data={backtest.equity_curve}
          initialCapital={backtest.initial_capital}
          height={450}
        />
      )}

      {/* 交易记录 */}
      <Card title={`交易记录 (${trades?.length || 0}笔)`} style={{ marginTop: 16 }}>
        <Table
          columns={tradeColumns}
          dataSource={trades?.map((t, i) => ({ ...t, _key: i }))}
          rowKey="_key"
          loading={tradesLoading}
          pagination={{
            pageSize: 20,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 笔交易`,
          }}
        />
      </Card>

      {/* 创建实盘策略模态框 */}
      <StrategyCreateModal
        open={createModalOpen}
        onCancel={() => setCreateModalOpen(false)}
        onSuccess={() => {
          setCreateModalOpen(false)
          message.success('策略创建成功，请前往策略列表启动')
          navigate('/strategy')
        }}
        backtestData={
          backtest
            ? {
                strategy_type: backtest.strategy_type,
                symbol: backtest.symbol,
                name: `${backtest.name}-实盘`,
                parameters: backtest.parameters || {},
              }
            : null
        }
      />
    </div>
  )
}

export default BacktestDetail
