import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { Card, Empty } from 'antd'
import { formatAmount, formatPercent } from '@/utils/format'

interface EquityCurveProps {
  /**
   * 资金曲线数据
   * 格式: [{ timestamp: number, equity: number, drawdown: number }, ...]
   */
  data?: Array<{ timestamp: number; equity: number; drawdown?: number }>
  /**
   * 初始资金
   */
  initialCapital: number
  /**
   * 图表高度
   */
  height?: number
}

const EquityCurve = ({ data, initialCapital, height = 400 }: EquityCurveProps) => {
  const option = useMemo(() => {
    if (!data || data.length === 0) {
      return null
    }

    // 提取数据
    const timestamps = data.map((item) => item.timestamp)
    const equities = data.map((item) => item.equity)
    const drawdowns = data.map((item) => (item.drawdown || 0) * 100) // 转换为百分比

    // 计算最大值和最小值用于Y轴范围
    const maxEquity = Math.max(...equities)
    const minEquity = Math.min(...equities)
    const equityRange = maxEquity - minEquity
    const equityPadding = equityRange * 0.1

    return {
      title: {
        text: '资金曲线',
        left: 'center',
        textStyle: {
          color: '#e5e5e5',
          fontSize: 16,
          fontWeight: 600,
        },
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(26, 26, 26, 0.95)',
        borderColor: '#2a2a2a',
        textStyle: {
          color: '#e5e5e5',
        },
        axisPointer: {
          type: 'cross',
          crossStyle: {
            color: '#737373',
          },
        },
        formatter: (params: any) => {
          if (!params || params.length === 0) return ''

          const timestamp = params[0].data[0] // [timestamp, value] 格式
          const equity = params[0].data[1]
          const drawdown = params[1]?.data?.[1] || 0
          const profit = equity - initialCapital
          const profitRate = ((equity - initialCapital) / initialCapital) * 100

          return `
            <div style="padding: 8px;">
              <div style="margin-bottom: 8px; font-weight: 600;">
                ${dayjs(timestamp).format('YYYY-MM-DD HH:mm')}
              </div>
              <div style="margin-bottom: 4px;">
                资金: <span style="color: #1890ff; font-weight: 600;">${formatAmount(equity)} USDT</span>
              </div>
              <div style="margin-bottom: 4px;">
                盈亏: <span style="color: ${profit >= 0 ? '#52c41a' : '#ff4d4f'}; font-weight: 600;">
                  ${profit >= 0 ? '+' : ''}${formatAmount(profit)} USDT (${profit >= 0 ? '+' : ''}${formatPercent(profitRate)}%)
                </span>
              </div>
              <div>
                回撤: <span style="color: #ff4d4f; font-weight: 600;">${formatPercent(Math.abs(drawdown))}%</span>
              </div>
            </div>
          `
        },
      },
      legend: {
        data: ['资金', '回撤'],
        top: 30,
        textStyle: {
          color: '#a3a3a3',
        },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '10%',
        top: '20%',
        containLabel: true,
      },
      xAxis: {
        type: 'time',
        boundaryGap: false,
        axisLabel: {
          color: '#737373',
          formatter: (value: number) => {
            // 使用dayjs格式化时间戳
            return dayjs(value).format('MM-DD HH:mm')
          },
          rotate: 30,
          hideOverlap: true,
        },
        axisLine: {
          lineStyle: {
            color: '#2a2a2a',
          },
        },
      },
      yAxis: [
        {
          type: 'value',
          name: '资金 (USDT)',
          position: 'left',
          min: minEquity - equityPadding,
          max: maxEquity + equityPadding,
          axisLabel: {
            color: '#737373',
            formatter: (value: number) => Math.round(value).toString(),
          },
          axisLine: {
            lineStyle: {
              color: '#2a2a2a',
            },
          },
          splitLine: {
            lineStyle: {
              color: '#2a2a2a',
              type: 'dashed',
            },
          },
          nameTextStyle: {
            color: '#a3a3a3',
          },
        },
        {
          type: 'value',
          name: '回撤 (%)',
          position: 'right',
          min: 0,
          max: Math.max(...drawdowns) * 1.2 || 10,
          axisLabel: {
            color: '#737373',
            formatter: (value: number) => `-${formatPercent(value, 1)}%`,
          },
          axisLine: {
            lineStyle: {
              color: '#2a2a2a',
            },
          },
          splitLine: {
            show: false,
          },
          nameTextStyle: {
            color: '#a3a3a3',
          },
        },
      ],
      series: [
        {
          name: '资金',
          type: 'line',
          data: equities.map((equity, index) => [timestamps[index], equity]),
          smooth: true,
          symbol: 'none',
          lineStyle: {
            color: '#1890ff',
            width: 2,
          },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                {
                  offset: 0,
                  color: 'rgba(24, 144, 255, 0.3)',
                },
                {
                  offset: 1,
                  color: 'rgba(24, 144, 255, 0.05)',
                },
              ],
            },
          },
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: {
              color: '#52c41a',
              type: 'dashed',
              width: 1,
            },
            label: {
              color: '#52c41a',
              formatter: '初始资金',
            },
            data: [
              {
                yAxis: initialCapital,
              },
            ],
          },
        },
        {
          name: '回撤',
          type: 'line',
          yAxisIndex: 1,
          data: drawdowns.map((drawdown, index) => [timestamps[index], drawdown]),
          smooth: true,
          symbol: 'none',
          lineStyle: {
            color: '#ff4d4f',
            width: 2,
          },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                {
                  offset: 0,
                  color: 'rgba(255, 77, 79, 0.2)',
                },
                {
                  offset: 1,
                  color: 'rgba(255, 77, 79, 0.05)',
                },
              ],
            },
          },
        },
      ],
      dataZoom: [
        {
          type: 'inside',
          start: 0,
          end: 100,
        },
        {
          type: 'slider',
          start: 0,
          end: 100,
          height: 20,
          bottom: 10,
          textStyle: {
            color: '#737373',
          },
          borderColor: '#2a2a2a',
          fillerColor: 'rgba(24, 144, 255, 0.15)',
          handleStyle: {
            color: '#1890ff',
          },
          moveHandleStyle: {
            color: '#1890ff',
          },
        },
      ],
      backgroundColor: 'transparent',
    }
  }, [data, initialCapital])

  if (!data || data.length === 0) {
    return (
      <Card title="资金曲线">
        <Empty description="暂无数据" />
      </Card>
    )
  }

  return (
    <Card title="资金曲线" styles={{ body: { padding: '16px' } }}>
      <ReactECharts option={option} style={{ height: `${height}px` }} notMerge={true} />
    </Card>
  )
}

export default EquityCurve
