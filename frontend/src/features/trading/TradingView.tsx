import { useState, useEffect } from 'react'
import { Row, Col, Card, Select, Space, Tabs, Spin, Tag, Radio } from 'antd'
import { TrendingUp, List, Clock, Search } from 'lucide-react'
import MarketTicker from '@/features/market/MarketTicker'
import TradingPanel from './TradingPanel'
import OrderHistory from './OrderHistory'
import OrderBook from './OrderBook'
import RecentTrades from './RecentTrades'
import KLineChart from './KLineChart'
import { useTranslation } from 'react-i18next'
import { marketApi } from '@/services/api'
import type { Instrument } from '@/types'

const TradingView = () => {
  const { t } = useTranslation()
  const [currentSymbol, setCurrentSymbol] = useState('BTC-USDT-SWAP')
  const [instruments, setInstruments] = useState<Instrument[]>([])
  const [loading, setLoading] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [instType, setInstType] = useState<'SPOT' | 'SWAP'>('SWAP')

  // 获取交易产品列表
  useEffect(() => {
    const fetchInstruments = async () => {
      try {
        setLoading(true)
        const data = await marketApi.getInstruments({
          inst_type: instType,
          quote_ccy: 'USDT',
        })
        setInstruments(data)

        // 如果当前选择的交易对不在新列表中,切换到第一个
        if (data.length > 0 && !data.find((inst) => inst.instId === currentSymbol)) {
          setCurrentSymbol(data[0].instId)
        }
      } catch (error) {
        // 获取交易产品失败
      } finally {
        setLoading(false)
      }
    }

    fetchInstruments()
  }, [instType])

  // 过滤交易对
  const filteredInstruments = instruments.filter((inst) => {
    if (!searchText) return true
    const searchLower = searchText.toLowerCase()
    return (
      inst.instId.toLowerCase().includes(searchLower) ||
      inst.baseCcy?.toLowerCase().includes(searchLower)
    )
  })

  return (
    <div>
      {/* 顶部交易对选择 */}
      <Card variant="borderless" size="small" style={{ marginBottom: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 16,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <span className="pro-card-header">{t('trading.selectSymbol').toUpperCase()}</span>

            {/* 交易类型切换 */}
            <Radio.Group
              value={instType}
              onChange={(e) => setInstType(e.target.value)}
              size="small"
              buttonStyle="solid"
            >
              <Radio.Button value="SPOT">
                现货 ({instruments.filter((i) => i.instType === 'SPOT').length})
              </Radio.Button>
              <Radio.Button value="SWAP">
                <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  合约 ({instruments.filter((i) => i.instType === 'SWAP').length})
                  <Tag color="orange" style={{ margin: 0, fontSize: 10 }}>
                    杠杆
                  </Tag>
                </span>
              </Radio.Button>
            </Radio.Group>
          </div>

          {/* 交易对选择器 */}
          <Select
            value={currentSymbol}
            onChange={setCurrentSymbol}
            size="large"
            style={{ minWidth: 280 }}
            showSearch
            loading={loading}
            placeholder="搜索交易对..."
            suffixIcon={loading ? <Spin size="small" /> : <Search size={14} />}
            onSearch={setSearchText}
            filterOption={false}
            notFoundContent={loading ? <Spin size="small" /> : '暂无数据'}
            optionLabelProp="label"
          >
            {filteredInstruments.map((inst) => (
              <Select.Option
                key={inst.instId}
                value={inst.instId}
                label={
                  <span className="font-mono" style={{ fontWeight: 600 }}>
                    {inst.instId}
                  </span>
                }
              >
                <div
                  style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                >
                  <span className="font-mono" style={{ fontWeight: 600 }}>
                    {inst.instId}
                  </span>
                  <div style={{ display: 'flex', gap: 4 }}>
                    {inst.instType === 'SWAP' && (
                      <Tag color="orange" style={{ margin: 0, fontSize: 10 }}>
                        {inst.lever}x
                      </Tag>
                    )}
                    <Tag color="blue" style={{ margin: 0, fontSize: 10 }}>
                      {inst.instType}
                    </Tag>
                  </div>
                </div>
              </Select.Option>
            ))}
          </Select>
        </div>
      </Card>

      {/* 实时行情 */}
      <MarketTicker symbol={currentSymbol} autoRefresh refreshInterval={2000} />

      {/* 交易区域 */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {/* 左侧：图表和订单区域 */}
        <Col xs={24} lg={16}>
          {/* K线图区域 */}
          <Card
            title={
              <div className="pro-card-header" style={{ margin: 0 }}>
                {t('trading.chart').toUpperCase()}
              </div>
            }
            variant="borderless"
            size="small"
            style={{ marginBottom: 16 }}
          >
            <KLineChart symbol={currentSymbol} height={400} />
          </Card>

          {/* 订单簿和成交记录 */}
          <Card
            variant="borderless"
            size="small"
            style={{ height: 'calc(100% - 432px)', minHeight: 400 }}
          >
            <Tabs
              size="small"
              items={[
                {
                  key: 'orderbook',
                  label: (
                    <span style={{ fontSize: 12, fontWeight: 600 }}>
                      <List size={14} /> {t('trading.orderBook').toUpperCase()}
                    </span>
                  ),
                  children: (
                    <div style={{ height: 350, overflow: 'auto' }}>
                      <OrderBook symbol={currentSymbol} maxDepth={10} />
                    </div>
                  ),
                },
                {
                  key: 'trades',
                  label: (
                    <span style={{ fontSize: 12, fontWeight: 600 }}>
                      <Clock size={14} /> {t('trading.recentTrades').toUpperCase()}
                    </span>
                  ),
                  children: (
                    <div style={{ height: 350, overflow: 'auto' }}>
                      <RecentTrades symbol={currentSymbol} maxTrades={50} />
                    </div>
                  ),
                },
              ]}
            />
          </Card>
        </Col>

        {/* 右侧：交易面板 */}
        <Col xs={24} lg={8}>
          <TradingPanel
            defaultSymbol={currentSymbol}
            onOrderCreated={(order) => {
              // 订单创建成功
            }}
          />
        </Col>
      </Row>

      {/* 订单历史 */}
      <div style={{ marginTop: 16 }}>
        <OrderHistory symbol={currentSymbol} />
      </div>
    </div>
  )
}

export default TradingView
