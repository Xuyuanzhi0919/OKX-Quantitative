import { useState, useEffect } from 'react'
import {
  Card,
  Button,
  Table,
  Form,
  Select,
  DatePicker,
  Space,
  Modal,
  Tag,
  Spin,
  App,
  Alert,
  Divider,
} from 'antd'
import { RefreshCw, Trash2, CloudDownload, Database, Download, Info } from 'lucide-react'
import { useMutation } from '@tanstack/react-query'
import dayjs, { Dayjs } from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import { BACKTEST_API } from '@/config/api'

const { RangePicker } = DatePicker

interface DataRange {
  symbol: string
  interval: string
  start_time: number
  end_time: number
  count: number
  start_time_str: string
  end_time_str: string
}

interface FetchKlineRequest {
  symbol: string
  interval: string
  start_time: number
  end_time: number
}

interface FetchKlineFormData {
  symbol: string
  interval: string
  time_range: [Dayjs, Dayjs]
}

interface FetchKlineResponse {
  total: number
  new: number
  updated: number
  skipped: number
}

// 默认交易对：合约（SWAP）优先，后接现货（SPOT）
const DEFAULT_SYMBOLS = [
  // ── 合约（USDT 本位永续）──
  'BTC-USDT-SWAP',
  'ETH-USDT-SWAP',
  'SOL-USDT-SWAP',
  'BNB-USDT-SWAP',
  'XRP-USDT-SWAP',
  'DOGE-USDT-SWAP',
  'ADA-USDT-SWAP',
  'AVAX-USDT-SWAP',
  'LINK-USDT-SWAP',
  'DOT-USDT-SWAP',
  'LTC-USDT-SWAP',
  'ATOM-USDT-SWAP',
  'ETC-USDT-SWAP',
  'ARB-USDT-SWAP',
  'OP-USDT-SWAP',
  'APT-USDT-SWAP',
  'NEAR-USDT-SWAP',
  'SUI-USDT-SWAP',
  'TRX-USDT-SWAP',
  'KSM-USDT-SWAP',
  'INJ-USDT-SWAP',
  'SEI-USDT-SWAP',
  'ORDI-USDT-SWAP',
  'WLD-USDT-SWAP',
  'PEPE-USDT-SWAP',
  'SHIB-USDT-SWAP',
  // ── 现货（SPOT）──
  'BTC-USDT',
  'ETH-USDT',
  'SOL-USDT',
  'BNB-USDT',
  'XRP-USDT',
  'DOGE-USDT',
  'ADA-USDT',
  'AVAX-USDT',
  'LINK-USDT',
  'DOT-USDT',
  'LTC-USDT',
  'ATOM-USDT',
  'ETC-USDT',
  'ARB-USDT',
  'OP-USDT',
  'APT-USDT',
  'NEAR-USDT',
  'KSM-USDT',
  'INJ-USDT',
  'PEPE-USDT',
]

const KlineManager = () => {
  const { modal, message: messageApi } = App.useApp()
  const [fetchModalOpen, setFetchModalOpen] = useState(false)
  const [form] = Form.useForm<FetchKlineFormData>()
  const [dataRanges, setDataRanges] = useState<DataRange[]>([])
  const [loadingRanges, setLoadingRanges] = useState(false)
  const [selectSymbols, setSelectSymbols] = useState<string[]>(DEFAULT_SYMBOLS)

  const intervals = [
    { value: '1m', label: '1分钟' },
    { value: '5m', label: '5分钟' },
    { value: '15m', label: '15分钟' },
    { value: '30m', label: '30分钟' },
    { value: '1H', label: '1小时' },
    { value: '4H', label: '4小时' },
    { value: '1D', label: '1天' },
  ]

  // 加载数据范围：先从 API 拿到 DB 中实际有数据的交易对，再查每个的范围
  const loadDataRanges = async () => {
    setLoadingRanges(true)
    const ranges: DataRange[] = []

    try {
      // 1. 获取 DB 中实际有 K 线数据的交易对
      let actualSymbols: string[] = []
      try {
        const symRes = await fetch(BACKTEST_API.symbols)
        if (symRes.ok) {
          const dbSymbols: string[] = await symRes.json()
          actualSymbols = dbSymbols
          // 更新下拉框：DB 已有数据的排前面，再追加默认列表
          setSelectSymbols([...new Set([...dbSymbols, ...DEFAULT_SYMBOLS])])
        }
      } catch {}

      // 2. 仅对 DB 中有数据的交易对发送范围查询（避免无效请求）
      for (const symbol of actualSymbols) {
        for (const interval of intervals) {
          try {
            const params = new URLSearchParams({ symbol, interval: interval.value })
            const response = await fetch(`${BACKTEST_API.klines.range}?${params}`)
            if (response.ok) {
              const data = await response.json()
              if (data && data.count > 0) {
                ranges.push({ symbol, interval: interval.value, ...data })
              }
            }
          } catch {}
        }
      }

      setDataRanges(ranges)
    } catch {
      messageApi.error('加载数据范围失败')
    } finally {
      setLoadingRanges(false)
    }
  }

  // 获取K线数据
  const fetchMutation = useMutation({
    mutationFn: async (values: FetchKlineRequest) => {
      const response = await fetch(BACKTEST_API.klines.fetch, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || '获取K线数据失败')
      }

      return response.json()
    },
    onSuccess: (data: FetchKlineResponse) => {
      messageApi.success(
        `获取完成！总计: ${data.total}, 新增: ${data.new}, 更新: ${data.updated}, 跳过: ${data.skipped}`,
      )
      setFetchModalOpen(false)
      form.resetFields()
      loadDataRanges() // 刷新数据范围列表
    },
    onError: (error: Error) => {
      messageApi.error(error.message)
    },
  })

  // 删除K线数据
  const deleteMutation = useMutation({
    mutationFn: async ({ symbol, interval }: { symbol: string; interval: string }) => {
      const params = new URLSearchParams({ symbol, interval })
      const response = await fetch(`${BACKTEST_API.klines.delete}?${params}`, {
        method: 'DELETE',
      })

      if (!response.ok) {
        throw new Error('删除K线数据失败')
      }

      return response.json()
    },
    onSuccess: (data) => {
      messageApi.success(`已删除 ${data.deleted} 条数据`)
      loadDataRanges() // 刷新数据范围列表
    },
    onError: (error: Error) => {
      messageApi.error(error.message)
    },
  })

  const columns: ColumnsType<DataRange> = [
    {
      title: '交易对',
      dataIndex: 'symbol',
      key: 'symbol',
      width: 120,
      render: (symbol: string) => <Tag color="blue">{symbol}</Tag>,
    },
    {
      title: '周期',
      dataIndex: 'interval',
      key: 'interval',
      width: 80,
      render: (interval: string) => (
        <Tag color="cyan">{intervals.find((i) => i.value === interval)?.label || interval}</Tag>
      ),
    },
    {
      title: '数据条数',
      dataIndex: 'count',
      key: 'count',
      width: 100,
      render: (count: number) => count.toLocaleString(),
    },
    {
      title: '开始时间',
      dataIndex: 'start_time_str',
      key: 'start_time',
      width: 180,
    },
    {
      title: '结束时间',
      dataIndex: 'end_time_str',
      key: 'end_time',
      width: 180,
    },
    {
      title: '时间跨度',
      key: 'duration',
      width: 120,
      render: (_: any, record: DataRange) => {
        const days = Math.round((record.end_time - record.start_time) / (1000 * 60 * 60 * 24))
        return `${days} 天`
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      fixed: 'right',
      render: (_: any, record: DataRange) => (
        <Button
          type="link"
          size="small"
          danger
          icon={<Trash2 size={14} />}
          onClick={() => {
            modal.confirm({
              title: '确认删除',
              content: `确定要删除 ${record.symbol} ${record.interval} 的所有K线数据吗？`,
              onOk: () =>
                deleteMutation.mutate({ symbol: record.symbol, interval: record.interval }),
            })
          }}
        >
          删除
        </Button>
      ),
    },
  ]

  // 打开获取数据对话框
  const handleOpenFetchModal = () => {
    setFetchModalOpen(true)
    // 重置表单并设置默认值
    // 结束时间设置为当前时间减2小时，避免OKX API数据延迟问题
    const endTime = dayjs().subtract(2, 'hour')
    const startTime = endTime.subtract(7, 'days')
    form.setFieldsValue({
      symbol: 'BTC-USDT-SWAP',
      interval: '1H',
      time_range: [startTime, endTime],
    })
  }

  const handleFetch = () => {
    form.validateFields().then((values: FetchKlineFormData) => {
      const [startTime, endTime] = values.time_range
      fetchMutation.mutate({
        symbol: values.symbol,
        interval: values.interval,
        start_time: startTime.valueOf(),
        end_time: endTime.valueOf(),
      })
    })
  }

  // 组件挂载时自动加载数据范围
  useEffect(() => {
    loadDataRanges()
  }, [])

  return (
    <div style={{ padding: '24px' }}>
      {/* 第一部分: 已存储的数据 */}
      <Card
        title={
          <Space>
            <Database size={16} style={{ color: '#1890ff' }} />
            <span>已存储的K线数据</span>
            <Tag color="blue">数据库中已有的历史数据</Tag>
          </Space>
        }
        extra={
          <Button icon={<RefreshCw size={14} />} onClick={loadDataRanges} loading={loadingRanges}>
            刷新
          </Button>
        }
        style={{ marginBottom: 24 }}
      >
        <Alert
          message="这是数据库中已保存的K线数据"
          description="下方列表显示的是已经下载并保存到数据库的历史数据。回测时将使用这些数据,无需重复获取。"
          type="info"
          showIcon
          icon={<Info size={14} />}
          closable
          style={{ marginBottom: 16 }}
        />

        <Table
          columns={columns}
          dataSource={dataRanges}
          rowKey={(record) => `${record.symbol}-${record.interval}`}
          loading={loadingRanges}
          scroll={{ x: 1000 }}
          pagination={{
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 组数据`,
          }}
          locale={{
            emptyText: '暂无数据,请点击下方"获取新数据"按钮从OKX下载历史K线',
          }}
        />
      </Card>

      <Divider style={{ margin: '32px 0' }} />

      {/* 第二部分: 获取新数据 */}
      <Card
        title={
          <Space>
            <Download size={16} style={{ color: '#52c41a' }} />
            <span>获取历史K线数据</span>
            <Tag color="green">从OKX交易所下载新数据</Tag>
          </Space>
        }
      >
        <Alert
          message="从OKX交易所下载K线数据"
          description="点击下方按钮,选择交易对、时间周期和时间范围,从OKX交易所API下载历史K线数据并保存到数据库。下载前请先查看上方已有数据,避免重复获取。"
          type="success"
          showIcon
          style={{ marginBottom: 16 }}
        />

        <div style={{ padding: '20px', background: '#1a1a1a', borderRadius: 8 }}>
          <div style={{ marginBottom: 16, fontSize: 14, color: '#e5e5e5' }}>
            <strong>提示:</strong>
          </div>
          <ul
            style={{ margin: 0, paddingLeft: 20, fontSize: 13, color: '#a3a3a3', lineHeight: 1.8 }}
          >
            <li>获取数据前请确保已配置代理并能正常访问OKX API</li>
            <li>OKX API有请求频率限制,大范围数据获取需要时间,请耐心等待</li>
            <li>1分钟周期数据量很大,建议选择较短时间范围(如7-30天)</li>
            <li>1小时/4小时周期适合获取较长时间范围(如90-180天)</li>
            <li>已存在的数据会自动跳过,不会重复保存</li>
            <li>建议先获取小范围数据测试,确认无误后再获取大范围数据</li>
          </ul>

          <div style={{ marginTop: 20, textAlign: 'center' }}>
            <Button
              type="primary"
              size="large"
              icon={<CloudDownload size={16} />}
              onClick={handleOpenFetchModal}
            >
              获取新数据
            </Button>
          </div>
        </div>
      </Card>

      {/* 获取数据模态框 */}
      <Modal
        title={
          <Space>
            <CloudDownload size={16} />
            <span>获取K线数据</span>
          </Space>
        }
        open={fetchModalOpen}
        onOk={handleFetch}
        onCancel={() => {
          setFetchModalOpen(false)
          form.resetFields()
        }}
        confirmLoading={fetchMutation.isPending}
        width={600}
        okText="开始获取"
        cancelText="取消"
      >
        <Spin spinning={fetchMutation.isPending}>
          <Form
            form={form}
            layout="vertical"
            initialValues={{
              symbol: 'BTC-USDT-SWAP',
              interval: '1H',
            }}
          >
            <Form.Item
              name="symbol"
              label="交易对"
              rules={[{ required: true, message: '请选择交易对' }]}
            >
              <Select
                placeholder="选择或搜索交易对，如 BTC-USDT-SWAP"
                showSearch
                allowClear
                filterOption={(input, option) =>
                  String(option?.value ?? '')
                    .toLowerCase()
                    .includes(input.toLowerCase())
                }
              >
                <Select.OptGroup label="合约（SWAP）">
                  {selectSymbols
                    .filter((s) => s.endsWith('-SWAP'))
                    .map((s) => (
                      <Select.Option key={s} value={s}>
                        {s}
                      </Select.Option>
                    ))}
                </Select.OptGroup>
                <Select.OptGroup label="现货（SPOT）">
                  {selectSymbols
                    .filter((s) => !s.endsWith('-SWAP'))
                    .map((s) => (
                      <Select.Option key={s} value={s}>
                        {s}
                      </Select.Option>
                    ))}
                </Select.OptGroup>
              </Select>
            </Form.Item>

            <Form.Item name="interval" label="K线周期" rules={[{ required: true }]}>
              <Select options={intervals} />
            </Form.Item>

            <Form.Item
              name="time_range"
              label="时间范围"
              rules={[{ required: true, message: '请选择时间范围' }]}
            >
              <RangePicker
                showTime
                style={{ width: '100%' }}
                disabledDate={(current) => current && current > dayjs().endOf('day')}
                presets={(() => {
                  // 结束时间设置为当前时间减2小时，避免OKX API数据延迟
                  const endTime = dayjs().subtract(2, 'hour')
                  return [
                    {
                      label: '最近7天',
                      value: [endTime.subtract(7, 'days'), endTime],
                    },
                    {
                      label: '最近30天',
                      value: [endTime.subtract(30, 'days'), endTime],
                    },
                    {
                      label: '最近90天',
                      value: [endTime.subtract(90, 'days'), endTime],
                    },
                    {
                      label: '最近180天',
                      value: [endTime.subtract(180, 'days'), endTime],
                    },
                    {
                      label: '最近1年',
                      value: [endTime.subtract(1, 'year'), endTime],
                    },
                  ]
                })()}
              />
            </Form.Item>

            <div style={{ padding: '12px', background: '#1a1a1a', borderRadius: 4, marginTop: 8 }}>
              <div style={{ fontSize: 12, color: '#a3a3a3', marginBottom: 8 }}>
                <strong style={{ color: '#e5e5e5' }}>注意事项：</strong>
              </div>
              <ul style={{ margin: 0, paddingLeft: 20, fontSize: 12, color: '#a3a3a3' }}>
                <li>OKX API有请求频率限制，大范围数据获取需要时间</li>
                <li>1分钟周期数据量大，建议选择较短时间范围</li>
                <li>已存在的数据会自动跳过，不会重复保存</li>
                <li>获取过程中请勿关闭窗口</li>
              </ul>
            </div>
          </Form>
        </Spin>
      </Modal>
    </div>
  )
}

export default KlineManager
