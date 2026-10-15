import { Card, Table, Button, Tag, Space, App, Input, Select, Row, Col, Dropdown, Radio } from 'antd'
import {
  Play,
  Pause,
  Trash2,
  Eye,
  AlertCircle,
  BarChart3,
  Plus,
  Search,
  Copy,
  Edit3,
} from 'lucide-react'
import type { ColumnsType } from 'antd/es/table'
import { StrategyStatus, Strategy } from '@/types'
import { useState, useEffect, useMemo } from 'react'
import StrategyDetailModal from './StrategyDetailModal'
import StrategyPerformanceModal from './StrategyPerformanceModal'
import StrategyCreateModal from './StrategyCreateModal'
import { safetyApi, strategyApi } from '@/services/api'
import { useTranslation } from 'react-i18next'
import { wsService, StrategyUpdateData } from '@/services/websocket'
import { formatPrice, formatPercent } from '@/utils/format'

const { Search: AntSearch } = Input

const apiErrorMessage = (error: any, fallback: string) => {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail.message === 'string') return detail.message
  return error?.response?.data?.message || fallback
}

// 常用 OKX 合约交易对（USDT 本位永续）
const SYMBOL_OPTIONS = [
  'BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP', 'BNB-USDT-SWAP',
  'XRP-USDT-SWAP', 'DOGE-USDT-SWAP', 'ADA-USDT-SWAP', 'AVAX-USDT-SWAP',
  'LINK-USDT-SWAP', 'DOT-USDT-SWAP', 'MATIC-USDT-SWAP', 'UNI-USDT-SWAP',
  'LTC-USDT-SWAP', 'ATOM-USDT-SWAP', 'ETC-USDT-SWAP', 'FIL-USDT-SWAP',
  'ARB-USDT-SWAP', 'OP-USDT-SWAP', 'APT-USDT-SWAP', 'NEAR-USDT-SWAP',
  'SUI-USDT-SWAP', 'TRX-USDT-SWAP', 'TON-USDT-SWAP', 'KSM-USDT-SWAP',
  'WLD-USDT-SWAP', 'INJ-USDT-SWAP', 'TIA-USDT-SWAP', 'JTO-USDT-SWAP',
  'SEI-USDT-SWAP', 'ORDI-USDT-SWAP', 'STX-USDT-SWAP', 'MEME-USDT-SWAP',
  'PEPE-USDT-SWAP', 'SHIB-USDT-SWAP', 'FLOKI-USDT-SWAP', 'BONK-USDT-SWAP',
].map(s => ({ label: s, value: s }))

// 策略类型中文标签（用于表格展示已有历史策略）
const STRATEGY_TYPE_LABELS: Record<string, string> = {
  grid: '网格策略',
  swing_long: '波段做多',
  swing_short: '波段做空',
  ai_swing_long: 'AI波段做多',
  martin: '马丁格尔',
  trend: '趋势跟踪',
  dual_side: '双向持仓',
  adaptive_grid_trend: '自适应趋势网格',
  arbitrage: '套利',
  top_gainers_momentum: '涨幅榜前三15m动量',
  explosive_momentum_chaser: '爆量急拉追涨',
  custom: '自定义',
}

// 可用实盘策略过滤选项
const STRATEGY_TYPE_OPTIONS: { label: string; value: string }[] = [
  { label: '自适应趋势网格', value: 'adaptive_grid_trend' },
  { label: '现货-永续套利', value: 'arbitrage' },
  { label: '涨幅榜前三15m动量', value: 'top_gainers_momentum' },
  { label: '爆量急拉追涨', value: 'explosive_momentum_chaser' },
]

// 状态选项
const STATUS_OPTIONS = [
  { label: '运行中', value: StrategyStatus.RUNNING },
  { label: '已停止', value: StrategyStatus.STOPPED },
  { label: '已暂停', value: StrategyStatus.PAUSED },
  { label: '错误', value: StrategyStatus.ERROR },
]

// 创建策略下拉菜单（与 STRATEGY_TYPES 保持一致）
const CREATE_MENU_ITEMS = [
  { key: 'adaptive_grid_trend', label: '自适应趋势网格' },
  { key: 'arbitrage', label: '现货-永续套利' },
  { key: 'top_gainers_momentum', label: '涨幅榜前三15m动量' },
  { key: 'explosive_momentum_chaser', label: '爆量急拉追涨' },
]

const StrategyList = () => {
  const { t } = useTranslation()
  const { message, modal } = App.useApp()
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [loading, setLoading] = useState(false)
  const [detailModalOpen, setDetailModalOpen] = useState(false)
  const [performanceModalOpen, setPerformanceModalOpen] = useState(false)
  const [selectedStrategy, setSelectedStrategy] = useState<Strategy | null>(null)
  const [actionLoading, setActionLoading] = useState<{ [key: number]: boolean }>({})
  const [emergencyLoading, setEmergencyLoading] = useState(false)
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [selectedCreateType, setSelectedCreateType] = useState<string>('')
  
  // 筛选状态
  const [searchText, setSearchText] = useState('')
  const [filterStatus, setFilterStatus] = useState<string | null>(null)
  const [filterType, setFilterType] = useState<string | null>(null)
  
  // 编辑/复制策略状态
  const [editModalOpen, setEditModalOpen] = useState(false)
  const [editingStrategy, setEditingStrategy] = useState<Strategy | null>(null)
  const [isCopyMode, setIsCopyMode] = useState(false)

  // 过滤后的策略列表
  const filteredStrategies = useMemo(() => {
    return strategies.filter(s => {
      // 搜索过滤
      if (searchText && !s.name.toLowerCase().includes(searchText.toLowerCase()) &&
          !s.symbol.toLowerCase().includes(searchText.toLowerCase())) {
        return false
      }
      // 状态过滤
      if (filterStatus && s.status !== filterStatus) {
        return false
      }
      // 类型过滤
      if (filterType && s.type !== filterType) {
        return false
      }
      return true
    })
  }, [strategies, searchText, filterStatus, filterType])

  const fetchStrategies = async (silent = false) => {
    try {
      if (!silent) setLoading(true)
      const response = await strategyApi.getList()
      // 处理响应数据
      const items = (response as any)?.data?.items || (response as any)?.items || []
      setStrategies(Array.isArray(items) ? items : [])
    } catch (error) {
      if (!silent) {
        message.error((error as Error).message || t('strategy.fetchStrategiesFailed'))
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStrategies()

    // 订阅策略更新
    const unsubscribe = wsService.onStrategyUpdate((data: StrategyUpdateData) => {
      fetchStrategies(true)
    })

    return () => {
      unsubscribe()
    }
  }, [])

  // 启动策略
  const handleStartStrategy = async (id: number) => {
    try {
      setActionLoading({ ...actionLoading, [id]: true })
      const preflight = await strategyApi.startPreflight(id)
      const warnings = preflight?.warnings || []
      const blockers = preflight?.blockers || []
      const checks = preflight?.checks || {}

      if (blockers.length > 0 || warnings.length > 0) {
        setActionLoading({ ...actionLoading, [id]: false })
        modal.confirm({
          title: blockers.length > 0 ? '启动前检查未通过' : '启动前安全确认',
          icon: <AlertCircle size={24} className={blockers.length > 0 ? 'text-red-500' : 'text-yellow-500'} />,
          width: 680,
          content: (
            <div>
              {checks.api_config && (
                <p>
                  API配置：
                  <Tag color={checks.api_config.is_simulated ? 'blue' : 'red'} style={{ marginLeft: 8 }}>
                    {checks.api_config.is_simulated ? '模拟盘' : '实盘'}
                  </Tag>
                  {checks.api_config.name}
                </p>
              )}
              {checks.account && <p>账户权益：{Number(checks.account.total_equity || 0).toFixed(2)} USDT</p>}
              {warnings.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <strong>风险提醒</strong>
                  <ul style={{ paddingLeft: 18 }}>
                    {warnings.map((item: string, idx: number) => <li key={idx}>{item}</li>)}
                  </ul>
                </div>
              )}
              {blockers.length > 0 && (
                <div style={{ marginTop: 8, color: '#ff4d4f' }}>
                  <strong>阻断项</strong>
                  <ul style={{ paddingLeft: 18 }}>
                    {blockers.map((item: string, idx: number) => <li key={idx}>{item}</li>)}
                  </ul>
                </div>
              )}
              {checks.existing_positions?.length > 0 && (
                <p style={{ color: '#faad14' }}>
                  检测到已有持仓，确认启动代表允许策略接管该交易对。
                </p>
              )}
            </div>
          ),
          okText: blockers.length > 0 ? '知道了' : '确认启动',
          cancelText: '取消',
          okType: blockers.length > 0 ? 'default' : 'danger',
          onOk: async () => {
            if (blockers.length > 0) return
            try {
              setActionLoading({ ...actionLoading, [id]: true })
              await strategyApi.start(id, true)
              await fetchStrategies(true)
            } catch (error) {
              message.error(apiErrorMessage(error, t('strategy.startStrategyFailed')))
            } finally {
              setActionLoading({ ...actionLoading, [id]: false })
            }
          },
        })
        return
      }

      await strategyApi.start(id)
      await fetchStrategies(true)
    } catch (error) {
      message.error(apiErrorMessage(error, t('strategy.startStrategyFailed')))
    } finally {
      setActionLoading({ ...actionLoading, [id]: false })
    }
  }

  const handleEmergencyStop = () => {
    let closePositions = false
    modal.confirm({
      title: '一键急停',
      icon: <AlertCircle size={24} className="text-red-500" />,
      width: 620,
      content: (
        <div>
          <p>急停会立即暂停所有运行中的策略，并撤销相关未成交订单。</p>
          <Radio.Group
            defaultValue={false}
            onChange={e => { closePositions = e.target.value }}
            style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
          >
            <Radio value={false}>仅暂停策略并撤单，保留当前持仓</Radio>
            <Radio value={true}>暂停策略、撤单并市价平仓</Radio>
          </Radio.Group>
        </div>
      ),
      okText: '执行急停',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          setEmergencyLoading(true)
          const result: any = await safetyApi.emergencyStop({
            action: closePositions ? 'close_all' : 'pause_all',
            cancel_orders: true,
            close_positions: closePositions,
          })
          message.success(result?.message || '急停执行完成')
          await fetchStrategies(true)
        } catch (error) {
          message.error((error as any)?.response?.data?.detail || '急停失败')
        } finally {
          setEmergencyLoading(false)
        }
      },
    })
  }

  // 停止策略
  const handleStopStrategy = (id: number, name: string) => {
    let closePosition = true  // 默认停止并平仓
    modal.confirm({
      title: '停止策略',
      icon: <AlertCircle size={24} className="text-yellow-500" />,
      content: (
        <div>
          <p style={{ marginBottom: 12 }}>确定要停止策略 <strong>{name}</strong> 吗？</p>
          <Radio.Group
            defaultValue={true}
            onChange={e => { closePosition = e.target.value }}
            style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
          >
            <Radio value={true}>
              <span>停止并平仓</span>
              <span style={{ color: '#8c8c8c', fontSize: 12, marginLeft: 6 }}>市价立即平掉当前持仓（推荐）</span>
            </Radio>
            <Radio value={false}>
              <span>仅停止策略</span>
              <span style={{ color: '#8c8c8c', fontSize: 12, marginLeft: 6 }}>保留持仓，可手动管理</span>
            </Radio>
          </Radio.Group>
        </div>
      ),
      okText: '确认停止',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          setActionLoading({ ...actionLoading, [id]: true })
          await strategyApi.stop(id, true, closePosition)
          await fetchStrategies(true)
        } catch (error) {
          message.error((error as any)?.response?.data?.message || t('strategy.stopStrategyFailed'))
        } finally {
          setActionLoading({ ...actionLoading, [id]: false })
        }
      },
    })
  }

  // 删除策略
  const handleDeleteStrategy = (id: number, name: string, isRunning: boolean) => {
    modal.confirm({
      title: '删除策略',
      icon: <AlertCircle size={24} className="text-red-500" />,
      content: isRunning ? (
        <div>
          <p style={{ marginBottom: 8 }}>确定要删除策略 <strong>{name}</strong> 吗？</p>
          <p style={{ color: '#ff4d4f', fontSize: 13, margin: 0 }}>
            ⚠️ 该策略正在运行，删除前将自动<strong>停止策略并市价平仓</strong>，请确认。
          </p>
        </div>
      ) : (
        <p>确定要删除策略 <strong>{name}</strong> 吗？此操作不可恢复。</p>
      ),
      okText: isRunning ? '平仓并删除' : '确定删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await strategyApi.delete(id)
          message.success('策略已删除')
          await fetchStrategies(true)
        } catch (error) {
          message.error((error as any)?.response?.data?.message || '删除策略失败')
        }
      },
    })
  }

  // 查看详情
  const handleViewDetail = (strategy: Strategy) => {
    setSelectedStrategy(strategy)
    setDetailModalOpen(true)
  }

  // 编辑策略
  const handleEditStrategy = (strategy: Strategy) => {
    setEditingStrategy(strategy)
    setIsCopyMode(false)
    setEditModalOpen(true)
  }

  // 复制策略
  const handleCopyStrategy = (strategy: Strategy) => {
    setEditingStrategy(strategy)
    setIsCopyMode(true)
    setEditModalOpen(true)
  }

  // 清空筛选
  const handleClearFilters = () => {
    setSearchText('')
    setFilterStatus(null)
    setFilterType(null)
    setDetailModalOpen(true)
  }

  // 查看绩效
  const handleViewPerformance = (strategy: Strategy) => {
    setSelectedStrategy(strategy)
    setPerformanceModalOpen(true)
  }

  const statusColorMap: Record<string, string> = {
    [StrategyStatus.RUNNING]: 'green',
    [StrategyStatus.STOPPED]: 'default',
    [StrategyStatus.PAUSED]: 'orange',
    [StrategyStatus.ERROR]: 'red',
  }
  const statusTextMap: Record<string, string> = {
    [StrategyStatus.RUNNING]: 'RUNNING',
    [StrategyStatus.STOPPED]: 'STOPPED',
    [StrategyStatus.PAUSED]: 'PAUSED',
    [StrategyStatus.ERROR]: 'ERROR',
  }

  const columns: ColumnsType<Strategy> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 180,
      render: (text) => <span style={{ fontWeight: 600 }}>{text}</span>,
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 100,
      render: (type) => <Tag>{STRATEGY_TYPE_LABELS[type] || String(type).toUpperCase()}</Tag>,
    },
    {
      title: '交易对',
      dataIndex: 'symbol',
      key: 'symbol',
      width: 130,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status) => (
        <Tag color={statusColorMap[status] || 'default'}>
          {statusTextMap[status] || status}
        </Tag>
      ),
    },
    {
      title: '总盈亏',
      dataIndex: 'total_profit',
      key: 'total_profit',
      width: 110,
      align: 'right',
      render: (profit) => {
        const value = profit || 0
        const color = value >= 0 ? '#22c55e' : '#ef4444'
        return (
          <span style={{ color, fontWeight: 600, fontFamily: 'monospace' }}>
            {value >= 0 ? '+' : ''}{formatPrice(value)} USDT
          </span>
        )
      },
    },
    {
      title: '总交易',
      dataIndex: 'total_trades',
      key: 'total_trades',
      width: 80,
      align: 'right',
      render: (trades) => trades || 0,
    },
    {
      title: '胜率',
      dataIndex: 'win_rate',
      key: 'win_rate',
      width: 70,
      align: 'right',
      render: (rate) => {
        const value = rate || 0
        const color = value >= 50 ? '#22c55e' : '#ef4444'
        return <span style={{ color }}>{formatPercent(value)}%</span>
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 280,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          {record.status === StrategyStatus.RUNNING ? (
            <Button
              type="text"
              size="small"
              icon={<Pause size={14} />}
              onClick={() => handleStopStrategy(record.id, record.name)}
              loading={actionLoading[record.id]}
              danger
            >
              {t('strategy.stop')}
            </Button>
          ) : (
            <Button
              type="text"
              size="small"
              icon={<Play size={14} />}
              onClick={() => handleStartStrategy(record.id)}
              loading={actionLoading[record.id]}
            >
              {t('strategy.start')}
            </Button>
          )}
          <Button
            type="text"
            size="small"
            icon={<Eye size={14} />}
            onClick={() => handleViewDetail(record)}
          >
            详情
          </Button>
          <Button
            type="text"
            size="small"
            icon={<BarChart3 size={14} />}
            onClick={() => handleViewPerformance(record)}
          >
            表现
          </Button>
          {record.status !== StrategyStatus.RUNNING && (
            <>
              <Button
                type="text"
                size="small"
                icon={<Edit3 size={14} />}
                onClick={() => handleEditStrategy(record)}
              >
                编辑
              </Button>
              <Button
                type="text"
                size="small"
                icon={<Copy size={14} />}
                onClick={() => handleCopyStrategy(record)}
              >
                复制
              </Button>
              <Button
                type="text"
                size="small"
                icon={<Trash2 size={14} />}
                onClick={() => handleDeleteStrategy(record.id, record.name, record.status === StrategyStatus.RUNNING)}
                danger
              >
                {t('common.delete')}
              </Button>
            </>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>{t('strategy.strategyList')}</span>
            <Space>
              <Button danger icon={<AlertCircle size={14} />} loading={emergencyLoading} onClick={handleEmergencyStop}>
                一键急停
              </Button>
              <Button onClick={() => fetchStrategies()}>
                {t('common.refresh')}
              </Button>
              <Dropdown
                trigger={['click']}
                menu={{
                  items: CREATE_MENU_ITEMS,
                  onClick: ({ key }) => {
                    setSelectedCreateType(key)
                    setCreateModalOpen(true)
                  },
                }}
                placement="bottomRight"
              >
                <Button type="primary" icon={<Plus size={14} />}>
                  创建策略
                </Button>
              </Dropdown>
            </Space>
          </div>
        }
      >
        {/* 筛选栏 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <AntSearch
              placeholder="搜索策略名称/交易对"
              allowClear
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onSearch={(v) => setSearchText(v)}
            />
          </Col>
          <Col span={6}>
            <Select
              style={{ width: '100%' }}
              placeholder="筛选状态"
              allowClear
              value={filterStatus}
              onChange={(v) => setFilterStatus(v)}
              options={STATUS_OPTIONS}
            />
          </Col>
          <Col span={6}>
            <Select
              style={{ width: '100%' }}
              placeholder="筛选策略类型"
              allowClear
              disabled={STRATEGY_TYPE_OPTIONS.length === 0}
              value={filterType}
              onChange={(v) => setFilterType(v)}
              options={STRATEGY_TYPE_OPTIONS}
            />
          </Col>
          <Col span={4}>
            <Button onClick={handleClearFilters} disabled={!searchText && !filterStatus && !filterType}>
              清空筛选
            </Button>
          </Col>
        </Row>

        <Table
          columns={columns}
          dataSource={filteredStrategies}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
          scroll={{ x: 1200 }}
          locale={{ emptyText: '暂无策略' }}
        />
      </Card>

      <StrategyDetailModal
        open={detailModalOpen}
        strategy={selectedStrategy}
        onCancel={() => {
          setDetailModalOpen(false)
          setSelectedStrategy(null)
        }}
      />

      <StrategyPerformanceModal
        open={performanceModalOpen}
        strategy={selectedStrategy}
        onCancel={() => {
          setPerformanceModalOpen(false)
          setSelectedStrategy(null)
        }}
      />

      {/* 创建策略 Modal */}
      <StrategyCreateModal
        open={createModalOpen}
        initialType={selectedCreateType}
        onCancel={() => { setCreateModalOpen(false); setSelectedCreateType('') }}
        onSuccess={() => {
          setCreateModalOpen(false)
          setSelectedCreateType('')
          fetchStrategies(true)
        }}
      />

      {/* 编辑/复制策略 Modal */}
      <StrategyCreateModal
        open={editModalOpen}
        onCancel={() => {
          setEditModalOpen(false)
          setEditingStrategy(null)
          setIsCopyMode(false)
        }}
        onSuccess={() => {
          setEditModalOpen(false)
          setEditingStrategy(null)
          setIsCopyMode(false)
          fetchStrategies(true)
        }}
        editStrategyId={!isCopyMode && editingStrategy ? editingStrategy.id : undefined}
        backtestData={editingStrategy ? {
          strategy_type: editingStrategy.type,
          symbol: editingStrategy.symbol,
          parameters: editingStrategy.parameters || {},
          name: isCopyMode ? `${editingStrategy.name} (副本)` : editingStrategy.name,
        } : null}
      />

    </div>
  )
}

export default StrategyList
