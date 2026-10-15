import { useEffect, useState } from 'react'
import { Spin } from 'antd'
import { wsService, OrderBookData } from '@/services/websocket'
import {
  formatPrice,
  formatQuantityDisplay,
  formatAmount,
  formatPriceDisplay,
} from '@/utils/format'

interface OrderBookProps {
  symbol: string
  maxDepth?: number
}

export default function OrderBook({ symbol, maxDepth = 10 }: OrderBookProps) {
  const [orderbook, setOrderbook] = useState<OrderBookData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // 订阅WebSocket数据
    wsService.subscribe(symbol)

    // 监听orderbook数据
    const unsubscribe = wsService.onOrderBook(symbol, (data) => {
      setOrderbook(data)
      setLoading(false)
    })

    // 清理函数
    return () => {
      unsubscribe()
      wsService.unsubscribe(symbol)
    }
  }, [symbol])

  if (loading && !orderbook) {
    return (
      <div style={{ padding: '40px 0', textAlign: 'center' }}>
        <Spin tip="Loading...">
          <div style={{ minHeight: 60 }} />
        </Spin>
      </div>
    )
  }

  if (!orderbook) return null

  // 限制显示深度
  const asks = orderbook.asks.slice(0, maxDepth).reverse()
  const bids = orderbook.bids.slice(0, maxDepth)

  // 计算最大数量用于进度条
  const maxAmount = Math.max(...asks.map((a) => a[1]), ...bids.map((b) => b[1]))

  return (
    <div style={{ fontSize: 12 }}>
      {/* 表头 */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr 1fr',
          padding: '8px 12px',
          borderBottom: '1px solid #2a2a2a',
          fontSize: 10,
          fontWeight: 600,
          color: '#737373',
          textTransform: 'uppercase',
        }}
      >
        <div style={{ textAlign: 'left' }}>Price (USDT)</div>
        <div style={{ textAlign: 'right' }}>Amount</div>
        <div style={{ textAlign: 'right' }}>Total</div>
      </div>

      {/* 卖单 (Asks) - 红色 */}
      <div>
        {asks.map((ask, index) => {
          const [price, amount] = ask
          const total = price * amount
          const percentage = (amount / maxAmount) * 100

          return (
            <div
              key={`ask-${price}-${index}`}
              style={{
                position: 'relative',
                display: 'grid',
                gridTemplateColumns: '1fr 1fr 1fr',
                padding: '4px 12px',
                fontFamily: 'monospace',
                fontSize: 11,
                cursor: 'pointer',
                transition: 'background 0.15s',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(239, 68, 68, 0.1)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'transparent'
              }}
            >
              {/* 背景进度条 */}
              <div
                style={{
                  position: 'absolute',
                  right: 0,
                  top: 0,
                  bottom: 0,
                  width: `${percentage}%`,
                  background: 'rgba(239, 68, 68, 0.08)',
                  pointerEvents: 'none',
                }}
              />

              <div style={{ position: 'relative', color: '#ef4444', fontWeight: 600 }}>
                {formatPrice(price)}
              </div>
              <div style={{ position: 'relative', textAlign: 'right', color: '#e5e5e5' }}>
                {formatQuantityDisplay(amount)}
              </div>
              <div style={{ position: 'relative', textAlign: 'right', color: '#a3a3a3' }}>
                {formatAmount(total)}
              </div>
            </div>
          )
        })}
      </div>

      {/* 最新价格 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '12px',
          borderTop: '1px solid #2a2a2a',
          borderBottom: '1px solid #2a2a2a',
          margin: '8px 0',
          background: '#0d0d0d',
        }}
      >
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 10, color: '#737373', marginBottom: 4 }}>SPREAD</div>
          <div style={{ fontFamily: 'monospace', fontSize: 14, fontWeight: 700, color: '#1890ff' }}>
            {bids.length > 0 && asks.length > 0
              ? `$${formatPriceDisplay(asks[asks.length - 1][0] - bids[0][0])}`
              : '-'}
          </div>
        </div>
      </div>

      {/* 买单 (Bids) - 绿色 */}
      <div>
        {bids.map((bid, index) => {
          const [price, amount] = bid
          const total = price * amount
          const percentage = (amount / maxAmount) * 100

          return (
            <div
              key={`bid-${price}-${index}`}
              style={{
                position: 'relative',
                display: 'grid',
                gridTemplateColumns: '1fr 1fr 1fr',
                padding: '4px 12px',
                fontFamily: 'monospace',
                fontSize: 11,
                cursor: 'pointer',
                transition: 'background 0.15s',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(34, 197, 94, 0.1)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'transparent'
              }}
            >
              {/* 背景进度条 */}
              <div
                style={{
                  position: 'absolute',
                  right: 0,
                  top: 0,
                  bottom: 0,
                  width: `${percentage}%`,
                  background: 'rgba(34, 197, 94, 0.08)',
                  pointerEvents: 'none',
                }}
              />

              <div style={{ position: 'relative', color: '#22c55e', fontWeight: 600 }}>
                {formatPrice(price)}
              </div>
              <div style={{ position: 'relative', textAlign: 'right', color: '#e5e5e5' }}>
                {formatQuantityDisplay(amount)}
              </div>
              <div style={{ position: 'relative', textAlign: 'right', color: '#a3a3a3' }}>
                {formatAmount(total)}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
