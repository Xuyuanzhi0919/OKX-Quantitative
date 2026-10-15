import React, { useState } from 'react'
import {
  Card,
  Table,
  Button,
  Modal,
  Form,
  Input,
  Switch,
  Space,
  Tag,
  Popconfirm,
  Typography,
  App as AntApp,
} from 'antd'
import { Plus, CheckCircle, XCircle, Pencil, Trash2, RefreshCw, Zap } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

const { Title, Text } = Typography

// API配置接口
interface APIConfig {
  id: number
  name: string
  exchange: string
  api_key: string
  is_simulated: boolean
  is_active: boolean
  is_valid: boolean
  proxy?: string
  last_verified_at?: string
  error_message?: string
  created_at: string
  updated_at?: string
}

// API配置端点
const API_CONFIGS_API = {
  list: '/api/v1/api-configs/list',
  create: '/api/v1/api-configs/create',
  activate: (id: number) => `/api/v1/api-configs/${id}/activate`,
  delete: (id: number) => `/api/v1/api-configs/${id}`,
  verify: (id: number) => `/api/v1/api-configs/${id}/verify`,
  getActive: '/api/v1/api-configs/active',
}

const authHeaders = (extra?: HeadersInit): HeadersInit => {
  const token = localStorage.getItem('token')
  return {
    ...(extra || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

const APIConfigManagement: React.FC = () => {
  const { message } = AntApp.useApp()
  const [form] = Form.useForm()
  const [isModalVisible, setIsModalVisible] = useState(false)
  const queryClient = useQueryClient()

  // 获取配置列表
  const { data: configs = [], isLoading } = useQuery<APIConfig[]>({
    queryKey: ['api-configs'],
    queryFn: async () => {
      const response = await fetch(API_CONFIGS_API.list, {
        headers: authHeaders(),
      })
      if (!response.ok) throw new Error('获取配置列表失败')
      return response.json()
    },
    refetchInterval: 30000, // 每30秒刷新
  })

  // 创建配置
  const createMutation = useMutation({
    mutationFn: async (values: any) => {
      const response = await fetch(API_CONFIGS_API.create, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(values),
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || '创建失败')
      }
      return response.json()
    },
    onSuccess: (data) => {
      message.success(`配置创建成功${data.is_valid ? '' : ',但验证失败: ' + data.error_message}`)
      queryClient.invalidateQueries({ queryKey: ['api-configs'] })
      setIsModalVisible(false)
      form.resetFields()
    },
    onError: (error: Error) => {
      message.error(`创建失败: ${error.message}`)
    },
  })

  // 激活配置
  const activateMutation = useMutation({
    mutationFn: async (id: number) => {
      const response = await fetch(API_CONFIGS_API.activate(id), {
        method: 'POST',
        headers: authHeaders(),
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || '切换失败')
      }
      return response.json()
    },
    onSuccess: (data) => {
      message.success(data.msg)
      localStorage.removeItem('okk_dashboard_v1')
      queryClient.invalidateQueries({ queryKey: ['api-configs'] })
    },
    onError: (error: Error) => {
      message.error(`切换失败: ${error.message}`)
    },
  })

  // 删除配置
  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      const response = await fetch(API_CONFIGS_API.delete(id), {
        method: 'DELETE',
        headers: authHeaders(),
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || '删除失败')
      }
      return response.json()
    },
    onSuccess: () => {
      message.success('删除成功')
      queryClient.invalidateQueries({ queryKey: ['api-configs'] })
    },
    onError: (error: Error) => {
      message.error(`删除失败: ${error.message}`)
    },
  })

  // 验证配置
  const verifyMutation = useMutation({
    mutationFn: async (id: number) => {
      const response = await fetch(API_CONFIGS_API.verify(id), {
        method: 'POST',
        headers: authHeaders(),
      })
      if (!response.ok) throw new Error('验证失败')
      return response.json()
    },
    onSuccess: (data) => {
      if (data.data.is_valid) {
        message.success('配置验证成功')
      } else {
        message.error(`配置验证失败: ${data.data.error_message}`)
      }
      queryClient.invalidateQueries({ queryKey: ['api-configs'] })
    },
    onError: (error: Error) => {
      message.error(`验证失败: ${error.message}`)
    },
  })

  const columns = [
    {
      title: '配置名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: APIConfig) => (
        <Space>
          <Text strong>{text}</Text>
          {record.is_active && <Tag color="blue">当前使用</Tag>}
        </Space>
      ),
    },
    {
      title: '交易所',
      dataIndex: 'exchange',
      key: 'exchange',
    },
    {
      title: 'API Key',
      dataIndex: 'api_key',
      key: 'api_key',
      render: (text: string) => <Text code>{text}</Text>,
    },
    {
      title: '类型',
      dataIndex: 'is_simulated',
      key: 'is_simulated',
      render: (isSimulated: boolean) => (
        <Tag color={isSimulated ? 'orange' : 'green'}>{isSimulated ? '模拟盘' : '实盘'}</Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_valid',
      key: 'is_valid',
      render: (isValid: boolean, record: APIConfig) => (
        <Space direction="vertical" size={0}>
          <Tag
            icon={isValid ? <CheckCircle size={14} /> : <XCircle size={14} />}
            color={isValid ? 'success' : 'error'}
          >
            {isValid ? '有效' : '无效'}
          </Tag>
          {!isValid && record.error_message && (
            <Text type="danger" style={{ fontSize: '12px' }}>
              {record.error_message}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '代理',
      dataIndex: 'proxy',
      key: 'proxy',
      render: (proxy?: string) => proxy || '-',
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: APIConfig) => (
        <Space>
          {!record.is_active && record.is_valid && (
            <Button
              type="primary"
              size="small"
              icon={<Zap size={14} />}
              onClick={() => activateMutation.mutate(record.id)}
              loading={activateMutation.isPending}
            >
              切换
            </Button>
          )}
          <Button
            size="small"
            icon={<RefreshCw size={14} />}
            onClick={() => verifyMutation.mutate(record.id)}
            loading={verifyMutation.isPending}
          >
            验证
          </Button>
          {!record.is_active && (
            <Popconfirm
              title="确定删除此配置吗?"
              onConfirm={() => deleteMutation.mutate(record.id)}
              okText="确定"
              cancelText="取消"
            >
              <Button danger size="small" icon={<Trash2 size={14} />}>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  const handleCreateConfig = () => {
    form.validateFields().then((values) => {
      createMutation.mutate(values)
    })
  }

  return (
    <div style={{ padding: '24px' }}>
      <Card
        title={
          <Space>
            <Title level={4} style={{ margin: 0 }}>
              API 配置管理
            </Title>
            <Text type="secondary">管理你的实盘和模拟盘 API 配置</Text>
          </Space>
        }
        extra={
          <Button type="primary" icon={<Plus size={14} />} onClick={() => setIsModalVisible(true)}>
            添加配置
          </Button>
        }
      >
        <Table
          columns={columns}
          dataSource={configs}
          rowKey="id"
          loading={isLoading}
          pagination={false}
        />
      </Card>

      {/* 创建配置Modal */}
      <Modal
        title="添加 API 配置"
        open={isModalVisible}
        onOk={handleCreateConfig}
        onCancel={() => {
          setIsModalVisible(false)
          form.resetFields()
        }}
        confirmLoading={createMutation.isPending}
        width={600}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            exchange: 'OKX',
            is_simulated: false,
            proxy: undefined,
          }}
        >
          <Form.Item
            label="配置名称"
            name="name"
            rules={[{ required: true, message: '请输入配置名称' }]}
          >
            <Input placeholder="例如: OKX 实盘配置" />
          </Form.Item>

          <Form.Item label="交易所" name="exchange">
            <Input disabled />
          </Form.Item>

          <Form.Item
            label="API Key"
            name="api_key"
            rules={[{ required: true, message: '请输入 API Key' }]}
          >
            <Input.Password placeholder="输入你的 API Key" />
          </Form.Item>

          <Form.Item
            label="Secret Key"
            name="secret_key"
            rules={[{ required: true, message: '请输入 Secret Key' }]}
          >
            <Input.Password placeholder="输入你的 Secret Key" />
          </Form.Item>

          <Form.Item
            label="Passphrase"
            name="passphrase"
            rules={[{ required: true, message: '请输入 Passphrase' }]}
          >
            <Input.Password placeholder="输入你的 Passphrase" />
          </Form.Item>

          <Form.Item label="模拟盘" name="is_simulated" valuePropName="checked">
            <Switch checkedChildren="是" unCheckedChildren="否" />
          </Form.Item>

          <Form.Item label="代理地址" name="proxy">
            <Input placeholder="可选，例如: http://127.0.0.1:7897" allowClear />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default APIConfigManagement
