import { useEffect, useState } from 'react'
import { Card, Row, Col, Spin, Button } from 'antd'
import { TrendingUp, TrendingDown, RotateCw } from 'lucide-react'
import { wsService } from '@/services/websocket'
import type { TickerData } from '@/services/websocket'
import { useTranslation } from 'react-i18next'
import {
  formatPrice,
  formatPriceDisplay,
  formatPercentDisplay,
  formatQuantityDisplay,
} from '@/utils/format'

interface MarketTickerProps {
  symbol: string
  autoRefresh?: boolean
  refreshInterval?: number
}

export default function MarketTicker({ symbol }: MarketTickerProps) {
  const { t } = useTranslation()
  const [ticker, setTicker] = useState<TickerData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // 订阅WebSocket数据
    wsService.subscribe(symbol)

    // 监听ticker数据
    const unsubscribe = wsService.onTicker(symbol, (data) => {
      setTicker(data)
      setLoading(false)
    })

    // 清理函数
    return () => {
      unsubscribe()
      wsService.unsubscribe(symbol)
    }
  }, [symbol])

  if (loading && !ticker) {
    return (
      <Card variant="borderless" size="small">
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Spin size="large" tip={t('trading.connecting')}>
            <div style={{ minHeight: 100 }} />
          </Spin>
        </div>
      </Card>
    )
  }

  if (!ticker) return null

  // 计算涨跌
  const last = ticker.last
  const open24h = ticker.open24h
  const change24h = last - open24h
  const changePercent = open24h > 0 ? (change24h / open24h) * 100 : 0
  const isUp = change24h >= 0

  const priceColor = isUp ? '#22c55e' : '#ef4444'
  const PriceIcon = isUp ? TrendingUp : TrendingDown

  // 格式化时间
  const updateTime = new Date(ticker.ts).toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })

  return (
    <Card
      title={
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div className="pro-card-header" style={{ margin: 0 }}>
              {ticker.symbol}
            </div>
            {/* 实时标识 */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                padding: '2px 8px',
                background: 'rgba(34, 197, 94, 0.15)',
                borderRadius: 3,
              }}
            >
              <div
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: '#22c55e',
                  animation: 'pulse 2s infinite',
                }}
              />
              <span style={{ fontSize: 10, color: '#22c55e', fontWeight: 600 }}>
                {t('trading.live').toUpperCase()}
              </span>
            </div>
          </div>
          <div style={{ fontSize: 11, color: '#737373', fontFamily: 'monospace' }}>
            {updateTime}
          </div>
        </div>
      }
      variant="borderless"
      size="small"
    >
      {/* 主要价格信息 */}
      <div
        style={{
          padding: '16px 0',
          borderBottom: '1px solid #2a2a2a',
          marginBottom: 16,
        }}
      >
        <Row gutter={[16, 16]} align="middle">
          <Col xs={24} md={12}>
            <div style={{ marginBottom: 4 }}>
              <span style={{ fontSize: 11, color: '#737373', textTransform: 'uppercase' }}>
                {t('trading.lastPrice').toUpperCase()}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span
                className="font-mono"
                style={{
                  fontSize: 32,
                  fontWeight: 700,
                  color: priceColor,
                  lineHeight: 1,
                }}
              >
                ${formatPrice(last)}
              </span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <PriceIcon size={14} style={{ color: priceColor }} />
                <span
                  className="font-mono"
                  style={{ fontSize: 16, fontWeight: 600, color: priceColor }}
                >
                  {changePercent >= 0 ? '+' : ''}
                  {formatPercentDisplay(changePercent)}
                </span>
              </div>
            </div>
          </Col>

          <Col xs={24} md={12}>
            <Row gutter={[12, 12]}>
              <Col span={12}>
                <div style={{ marginBottom: 4 }}>
                  <span style={{ fontSize: 10, color: '#737373', textTransform: 'uppercase' }}>
                    {t('trading.24hChange').toUpperCase()}
                  </span>
                </div>
                <span
                  className="font-mono"
                  style={{ fontSize: 16, fontWeight: 600, color: priceColor }}
                >
                  {change24h >= 0 ? '+' : ''}
                  {formatPriceDisplay(change24h)}
                </span>
              </Col>
              <Col span={12}>
                <div style={{ marginBottom: 4 }}>
                  <span style={{ fontSize: 10, color: '#737373', textTransform: 'uppercase' }}>
                    {t('trading.24hVolume').toUpperCase()}
                  </span>
                </div>
                <span className="font-mono" style={{ fontSize: 16, fontWeight: 600 }}>
                  {ticker.vol24h.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </span>
              </Col>
            </Row>
          </Col>
        </Row>
      </div>

      {/* 详细数据网格 */}
      <Row gutter={[16, 12]}>
        <Col xs={12} sm={8} md={6}>
          <DataItem
            label={t('trading.24hHigh').toUpperCase()}
            value={`$${formatPrice(ticker.high24h)}`}
            color="#22c55e"
          />
        </Col>
        <Col xs={12} sm={8} md={6}>
          <DataItem
            label={t('trading.24hLow').toUpperCase()}
            value={`$${formatPrice(ticker.low24h)}`}
            color="#ef4444"
          />
        </Col>
        <Col xs={12} sm={8} md={6}>
          <DataItem
            label={t('trading.24hOpen').toUpperCase()}
            value={`$${formatPrice(ticker.open24h)}`}
            color="#a3a3a3"
          />
        </Col>
        <Col xs={12} sm={8} md={6}>
          <DataItem
            label={t('trading.volCcyUsdt').toUpperCase()}
            value={ticker.volCcy24h.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            color="#1890ff"
          />
        </Col>
        <Col xs={12} sm={8} md={6}>
          <DataItem
            label={t('trading.bid').toUpperCase()}
            value={`$${formatPrice(ticker.bidPx)}`}
            subValue={formatQuantityDisplay(ticker.bidSz)}
            color="#22c55e"
          />
        </Col>
        <Col xs={12} sm={8} md={6}>
          <DataItem
            label={t('trading.ask').toUpperCase()}
            value={`$${formatPrice(ticker.askPx)}`}
            subValue={formatQuantityDisplay(ticker.askSz)}
            color="#ef4444"
          />
        </Col>
      </Row>
    </Card>
  )
}

// 数据项组件
function DataItem({
  label,
  value,
  subValue,
  color = '#e5e5e5',
}: {
  label: string
  value: string
  subValue?: string
  color?: string
}) {
  return (
    <div>
      <div style={{ marginBottom: 4 }}>
        <span
          style={{
            fontSize: 10,
            color: '#737373',
            textTransform: 'uppercase',
            fontWeight: 600,
          }}
        >
          {label}
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
        <span className="font-mono" style={{ fontSize: 14, fontWeight: 600, color }}>
          {value}
        </span>
        {subValue && (
          <span className="font-mono" style={{ fontSize: 11, color: '#737373' }}>
            ({subValue})
          </span>
        )}
      </div>
    </div>
  )
}
