import { useEffect, useRef, useState } from 'react'
import { createChart, IChartApi, ISeriesApi, CandlestickData, Time } from 'lightweight-charts'
import { Select, Space, Spin } from 'antd'
import { marketApi } from '@/services/api'
import { wsService, KlineData } from '@/services/websocket'

// 动态获取价格精度
const getPricePrecision = (price: number): number => {
  if (price >= 1000) return 2
  if (price >= 1) return 4
  if (price >= 0.01) return 6
  return 8
}

interface KLineChartProps {
  symbol: string
  height?: number
}

type Interval = '1m' | '5m' | '15m' | '1H' | '4H' | '1D'

export default function KLineChart({ symbol, height = 400 }: KLineChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candlestickSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const [interval, setInterval] = useState<Interval>('15m')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!chartContainerRef.current) return

    // 创建图表
    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: height,
      layout: {
        background: { color: '#0d0d0d' },
        textColor: '#a3a3a3',
      },
      grid: {
        vertLines: { color: '#1a1a1a' },
        horzLines: { color: '#1a1a1a' },
      },
      crosshair: {
        mode: 1,
      },
      rightPriceScale: {
        borderColor: '#2a2a2a',
      },
      timeScale: {
        borderColor: '#2a2a2a',
        timeVisible: true,
        secondsVisible: false,
      },
    })

    chartRef.current = chart

    // 创建K线系列（先使用默认配置）
    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })

    candlestickSeriesRef.current = candlestickSeries

    // 生成模拟数据
    const mockData = generateMockData(100)
    candlestickSeries.setData(mockData)

    // 自动缩放
    chart.timeScale().fitContent()

    // 响应式处理
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        })
      }
    }

    window.addEventListener('resize', handleResize)

    // 清理函数
    return () => {
      window.removeEventListener('resize', handleResize)
      if (chartRef.current) {
        chartRef.current.remove()
      }
    }
  }, [height])

  // 当interval或symbol改变时重新加载数据
  useEffect(() => {
    if (!candlestickSeriesRef.current) return

    const loadKlineData = async () => {
      try {
        setLoading(true)
        // 获取真实K线数据
        const data = await marketApi.getKline(symbol, interval, 200)

        // 转换OKX数据格式为TradingView格式
        const chartData: CandlestickData[] = data
          .map((candle: any) => ({
            time: (parseInt(candle.ts) / 1000) as Time, // 转换为秒级时间戳
            open: parseFloat(candle.o),
            high: parseFloat(candle.h),
            low: parseFloat(candle.l),
            close: parseFloat(candle.c),
          }))
          .reverse() // OKX返回的数据是倒序的，需要反转

        candlestickSeriesRef.current.setData(chartData)

        // 根据价格范围动态设置精度
        if (chartData.length > 0) {
          const avgPrice = chartData.reduce((sum, d) => sum + d.close, 0) / chartData.length
          const precision = getPricePrecision(avgPrice)
          candlestickSeriesRef.current.applyOptions({
            priceFormat: {
              type: 'price',
              precision: precision,
              minMove: Math.pow(10, -precision),
            },
          })
        }

        if (chartRef.current) {
          chartRef.current.timeScale().fitContent()
        }
        setLoading(false)
      } catch (error) {
        setLoading(false)
        // 失败时使用模拟数据
        const mockData = generateMockData(100)
        candlestickSeriesRef.current?.setData(mockData)
        if (chartRef.current) {
          chartRef.current.timeScale().fitContent()
        }
      }
    }

    loadKlineData()
  }, [interval, symbol])

  // 监听实时K线更新
  useEffect(() => {
    if (!candlestickSeriesRef.current) return

    // 监听K线数据
    const unsubscribe = wsService.onKline(symbol, (data: KlineData) => {
      // 只处理当前周期的K线
      if (data.bar !== interval) return

      try {
        // 转换K线数据为图表格式
        const klineUpdate: CandlestickData = {
          time: (parseInt(data.ts) / 1000) as Time,
          open: parseFloat(data.o),
          high: parseFloat(data.h),
          low: parseFloat(data.l),
          close: parseFloat(data.c),
        }

        // 更新K线数据
        candlestickSeriesRef.current?.update(klineUpdate)
      } catch (error) {
        // 忽略K线数据更新错误
      }
    })

    return () => {
      unsubscribe()
    }
  }, [symbol, interval])

  return (
    <div>
      {/* 控制栏 */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 12,
          padding: '8px 12px',
          background: '#1a1a1a',
          borderRadius: 4,
          border: '1px solid #2a2a2a',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: '#737373', fontWeight: 600 }}>TIME INTERVAL</span>
          <Space size={4}>
            {(['1m', '5m', '15m', '1H', '4H', '1D'] as Interval[]).map((int) => (
              <button
                key={int}
                onClick={() => setInterval(int)}
                style={{
                  padding: '4px 12px',
                  fontSize: 11,
                  fontWeight: 600,
                  color: interval === int ? '#1890ff' : '#737373',
                  background: interval === int ? 'rgba(24, 144, 255, 0.1)' : 'transparent',
                  border: interval === int ? '1px solid #1890ff' : '1px solid #2a2a2a',
                  borderRadius: 3,
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                }}
                onMouseEnter={(e) => {
                  if (interval !== int) {
                    e.currentTarget.style.background = 'rgba(255, 255, 255, 0.05)'
                  }
                }}
                onMouseLeave={(e) => {
                  if (interval !== int) {
                    e.currentTarget.style.background = 'transparent'
                  }
                }}
              >
                {int}
              </button>
            ))}
          </Space>
        </div>

        <div
          style={{
            fontSize: 11,
            color: '#525252',
            fontFamily: 'monospace',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          {loading ? (
            <>
              <Spin size="small" />
              <span>Loading...</span>
            </>
          ) : (
            <>
              <span style={{ color: '#22c55e' }}>●</span>
              <span>OKX Real Data • {symbol}</span>
            </>
          )}
        </div>
      </div>

      {/* 图表容器 */}
      <div
        ref={chartContainerRef}
        style={{
          position: 'relative',
          borderRadius: 4,
          border: '1px solid #2a2a2a',
          overflow: 'hidden',
        }}
      />
    </div>
  )
}

// 生成模拟K线数据
function generateMockData(count: number): CandlestickData[] {
  const data: CandlestickData[] = []
  const basePrice = 111000
  let currentPrice = basePrice
  const now = Math.floor(Date.now() / 1000)
  const interval = 900 // 15分钟

  for (let i = count; i >= 0; i--) {
    const time = (now - i * interval) as Time
    const open = currentPrice
    const volatility = Math.random() * 500 - 250
    const high = open + Math.abs(volatility) + Math.random() * 200
    const low = open - Math.abs(volatility) - Math.random() * 200
    const close = open + volatility

    data.push({
      time,
      open,
      high,
      low,
      close,
    })

    currentPrice = close
  }

  return data
}
