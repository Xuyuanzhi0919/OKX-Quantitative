import { useState, useEffect } from 'react'
import {
  Card,
  Table,
  Tag,
  Button,
  Space,
  Select,
  Row,
  Col,
  Statistic,
  Popconfirm,
  Typography,
  App,
} from 'antd'
import { Bell, Check, Trash2, RotateCw } from 'lucide-react'
import { alertApi } from '@/services/api'
import type { Alert, AlertType, AlertSeverity } from '@/types'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'

const { Option } = Select
const { Text } = Typography

const AlertHistory = () => {
  const { message } = App.useApp()
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [unreadCount, setUnreadCount] = useState(0)
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 })

  // 筛选条件
  const [filterType, setFilterType] = useState<AlertType | undefined>()
  const [filterSeverity, setFilterSeverity] = useState<AlertSeverity | undefined>()
  const [filterRead, setFilterRead] = useState<boolean | undefined>()

  // 获取告警列表
  const fetchAlerts = async () => {
    setLoading(true)
    try {
      const params = {
        skip: (pagination.current - 1) * pagination.pageSize,
        limit: pagination.pageSize,
        alert_type: filterType,
        severity: filterSeverity,
        is_read: filterRead,
      }

      const response = await alertApi.getList(params)
      setAlerts(response.alerts || [])
      setTotal(response.total || 0)
    } catch (error) {
      message.error(`获取告警列表失败: ${(error as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  // 获取未读数量
  const fetchUnreadCount = async () => {
    try {
      const response = await alertApi.getUnreadCount()
      setUnreadCount(response.count || 0)
    } catch (error) {
      // 处理错误
    }
  }

  // 标记单个告警为已读
  const handleMarkRead = async (id: number) => {
    try {
      await alertApi.markRead(id)
      message.success('已标记为已读')
      fetchAlerts()
      fetchUnreadCount()
    } catch (error) {
      message.error(`标记失败: ${(error as Error).message}`)
    }
  }

  // 标记所有为已读
  const handleMarkAllRead = async () => {
    try {
      const response = await alertApi.markAllRead()
      message.success(`已标记 ${response.count} 条告警为已读`)
      fetchAlerts()
      fetchUnreadCount()
    } catch (error) {
      message.error(`批量标记失败: ${(error as Error).message}`)
    }
  }

  // 删除告警
  const handleDelete = async (id: number) => {
    try {
      await alertApi.delete(id)
      message.success('删除成功')
      fetchAlerts()
    } catch (error) {
      message.error(`删除失败: ${(error as Error).message}`)
    }
  }

  // 获取告警类型标签
  const getAlertTypeTag = (type: AlertType) => {
    const config: Record<AlertType, { color: string; text: string }> = {
      stop_loss: { color: 'red', text: '止损' },
      take_profit: { color: 'green', text: '止盈' },
      risk_warning: { color: 'orange', text: '风险警告' },
      system_error: { color: 'purple', text: '系统错误' },
    }
    return <Tag color={config[type].color}>{config[type].text}</Tag>
  }

  // 获取严重级别标签
  const getSeverityTag = (severity: AlertSeverity) => {
    const config: Record<AlertSeverity, { color: string; text: string }> = {
      info: { color: 'blue', text: '信息' },
      warning: { color: 'orange', text: '警告' },
      error: { color: 'red', text: '错误' },
      success: { color: 'green', text: '成功' },
    }
    return <Tag color={config[severity].color}>{config[severity].text}</Tag>
  }

  // 表格列定义
  const columns: ColumnsType<Alert> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (text: string) => dayjs(text).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '类型',
      dataIndex: 'alert_type',
      key: 'alert_type',
      width: 100,
      render: (type: AlertType) => getAlertTypeTag(type),
    },
    {
      title: '级别',
      dataIndex: 'severity',
      key: 'severity',
      width: 80,
      render: (severity: AlertSeverity) => getSeverityTag(severity),
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      width: 150,
    },
    {
      title: '消息',
      dataIndex: 'message',
      key: 'message',
      ellipsis: true,
    },
    {
      title: '状态',
      key: 'status',
      width: 80,
      render: (_, record) => (
        <Tag color={record.is_read ? 'default' : 'blue'}>{record.is_read ? '已读' : '未读'}</Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      render: (_, record) => (
        <Space>
          {!record.is_read && (
            <Button
              type="link"
              size="small"
              icon={<Check size={14} />}
              onClick={() => handleMarkRead(record.id)}
            >
              标记已读
            </Button>
          )}
          <Popconfirm
            title="确认删除此告警?"
            onConfirm={() => handleDelete(record.id)}
            okText="确认"
            cancelText="取消"
          >
            <Button type="link" danger size="small" icon={<Trash2 size={14} />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // 初始加载
  useEffect(() => {
    fetchAlerts()
    fetchUnreadCount()
  }, [pagination.current, pagination.pageSize, filterType, filterSeverity, filterRead])

  return (
    <div>
      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic title="总告警数" value={total} prefix={<Bell size={14} />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="未读告警"
              value={unreadCount}
              valueStyle={{ color: '#ff4d4f' }}
              prefix={<Bell size={14} />}
            />
          </Card>
        </Col>
      </Row>

      {/* 筛选和操作栏 */}
      <Card
        title="告警历史"
        extra={
          <Space>
            <Button
              type="primary"
              icon={<Check size={14} />}
              onClick={handleMarkAllRead}
              disabled={unreadCount === 0}
            >
              全部标记已读
            </Button>
            <Button
              icon={<RotateCw size={14} />}
              onClick={() => {
                fetchAlerts()
                fetchUnreadCount()
              }}
            >
              刷新
            </Button>
          </Space>
        }
      >
        {/* 筛选器 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Select
              placeholder="筛选类型"
              allowClear
              style={{ width: '100%' }}
              value={filterType}
              onChange={setFilterType}
            >
              <Option value="stop_loss">止损</Option>
              <Option value="take_profit">止盈</Option>
              <Option value="risk_warning">风险警告</Option>
              <Option value="system_error">系统错误</Option>
            </Select>
          </Col>
          <Col span={6}>
            <Select
              placeholder="筛选级别"
              allowClear
              style={{ width: '100%' }}
              value={filterSeverity}
              onChange={setFilterSeverity}
            >
              <Option value="info">信息</Option>
              <Option value="warning">警告</Option>
              <Option value="error">错误</Option>
              <Option value="success">成功</Option>
            </Select>
          </Col>
          <Col span={6}>
            <Select
              placeholder="筛选状态"
              allowClear
              style={{ width: '100%' }}
              value={filterRead}
              onChange={setFilterRead}
            >
              <Option value={false}>未读</Option>
              <Option value={true}>已读</Option>
            </Select>
          </Col>
        </Row>

        {/* 告警列表 */}
        <Table
          columns={columns}
          dataSource={alerts}
          rowKey="id"
          loading={loading}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: total,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              setPagination({ current: page, pageSize: pageSize || 20 })
            },
          }}
          rowClassName={(record) => (record.is_read ? '' : 'unread-alert')}
        />
      </Card>

      <style>{`
        .unread-alert {
          background-color: #f0f7ff;
        }
      `}</style>
    </div>
  )
}

export default AlertHistory
