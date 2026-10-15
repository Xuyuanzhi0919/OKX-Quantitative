import { useState, useEffect } from 'react'
import {
  Card,
  Table,
  Button,
  Modal,
  Form,
  Input,
  Tag,
  Space,
  Popconfirm,
  App,
  Alert,
  Tooltip,
} from 'antd'
import { Plus, Edit, Trash2, Check, Brain, Zap, Key } from 'lucide-react'
import type { ColumnsType } from 'antd/es/table'
import { aiApi } from '@/services/api'

interface AIConfig {
  id: number
  name: string
  provider: string
  model: string
  is_active: boolean
  created_at: string
  updated_at?: string
}

const AIConfigManagement = () => {
  const { message } = App.useApp()
  const [configs, setConfigs] = useState<AIConfig[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editModalOpen, setEditModalOpen] = useState(false)
  const [editingConfig, setEditingConfig] = useState<AIConfig | null>(null)
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()

  useEffect(() => {
    fetchConfigs()
  }, [])

  const fetchConfigs = async () => {
    try {
      setLoading(true)
      const data = await aiApi.getConfigList()
      setConfigs(data)
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '获取AI配置失败')
    } finally {
      setLoading(false)
    }
  }

  const handleCreate = async () => {
    try {
      const values = await form.validateFields()
      setLoading(true)

      await aiApi.createConfig({
        name: values.name,
        provider: values.provider || 'deepseek',
        api_key: values.api_key,
        model: values.model || 'deepseek-chat',
      })

      message.success('AI配置创建成功')
      form.resetFields()
      setModalOpen(false)
      fetchConfigs()
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '创建失败')
    } finally {
      setLoading(false)
    }
  }

  const handleEdit = async () => {
    try {
      const values = await editForm.validateFields()
      setLoading(true)

      await aiApi.updateConfig(editingConfig!.id, {
        name: values.name,
        api_key: values.api_key,
        model: values.model,
      })

      message.success('AI配置更新成功')
      setEditModalOpen(false)
      setEditingConfig(null)
      editForm.resetFields()
      fetchConfigs()
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '更新失败')
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (id: number) => {
    try {
      await aiApi.deleteConfig(id)
      message.success('删除成功')
      fetchConfigs()
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '删除失败')
    }
  }

  const handleActivate = async (id: number) => {
    try {
      await aiApi.activateConfig(id)
      message.success('激活成功')
      fetchConfigs()
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '激活失败')
    }
  }

  const openEditModal = (config: AIConfig) => {
    setEditingConfig(config)
    editForm.setFieldsValue({
      name: config.name,
      api_key: '', // 不显示原API key
      model: config.model,
    })
    setEditModalOpen(true)
  }

  const columns: ColumnsType<AIConfig> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name, record) => (
        <Space>
          <span>{name}</span>
          {record.is_active && (
            <Tag color="success" icon={<Check size={12} />}>
              已激活
            </Tag>
          )}
        </Space>
      ),
    },
    {
      title: '提供商',
      dataIndex: 'provider',
      key: 'provider',
      render: (provider) => {
        const color = provider === 'deepseek' ? 'blue' : 'default'
        return <Tag color={color}>{provider.toUpperCase()}</Tag>
      },
    },
    {
      title: '模型',
      dataIndex: 'model',
      key: 'model',
      render: (model) => <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{model}</span>,
    },
    {
      title: 'API密钥',
      dataIndex: 'api_key',
      key: 'api_key',
      render: () => '********************', // 隐藏API key
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date) => new Date(date).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_, record) => (
        <Space size="small">
          {!record.is_active && (
            <Button
              type="primary"
              size="small"
              icon={<Check size={14} />}
              onClick={() => handleActivate(record.id)}
            >
              激活
            </Button>
          )}
          <Button size="small" icon={<Edit size={14} />} onClick={() => openEditModal(record)}>
            编辑
          </Button>
          <Popconfirm
            title="确定删除此配置？"
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button danger size="small" icon={<Trash2 size={14} />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: '24px', maxWidth: '1200px', margin: '0 auto' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <h1
          style={{
            fontSize: 24,
            fontWeight: 600,
            color: '#fff',
            marginBottom: 8,
            display: 'flex',
            alignItems: 'center',
            gap: 12,
          }}
        >
          <Brain size={28} style={{ color: '#8b5cf6' }} />
          AI服务配置
        </h1>
        <p style={{ color: '#737373', margin: 0 }}>配置DeepSeek API密钥，启用AI市场分析功能</p>
      </div>

      {/* 说明卡片 */}
      <Card
        style={{
          marginBottom: 24,
          background:
            'linear-gradient(135deg, rgba(139, 92, 246, 0.1) 0%, rgba(59, 130, 246, 0.1) 100%)',
          border: '1px solid rgba(139, 92, 246, 0.3)',
        }}
      >
        <Space direction="vertical" size="small" style={{ width: '100%' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              color: '#a3a3a3',
              fontSize: 13,
            }}
          >
            <Brain size={14} />
            <span style={{ fontWeight: 600 }}>如何获取DeepSeek API密钥？</span>
          </div>
          <div style={{ color: '#737373', fontSize: 12, marginLeft: 22 }}>
            1. 访问{' '}
            <a
              href="https://platform.deepseek.com/"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: '#8b5cf6' }}
            >
              DeepSeek开放平台
            </a>
          </div>
          <div style={{ color: '#737373', fontSize: 12, marginLeft: 22 }}>2. 注册/登录账号</div>
          <div style={{ color: '#737373', fontSize: 12, marginLeft: 22 }}>
            3. 进入"API Keys"页面创建密钥
          </div>
          <div style={{ color: '#737373', fontSize: 12, marginLeft: 22 }}>
            4. 复制API Key并粘贴到下方配置中
          </div>
        </Space>
      </Card>

      {/* 配置列表 */}
      <Card
        title="AI配置列表"
        extra={
          <Button type="primary" icon={<Plus size={16} />} onClick={() => setModalOpen(true)}>
            添加配置
          </Button>
        }
        style={{ background: '#1a1a1a', border: '1px solid #2a2a2a' }}
      >
        <Table
          columns={columns}
          dataSource={configs}
          rowKey="id"
          loading={loading}
          pagination={false}
          locale={{ emptyText: '暂无AI配置，请添加' }}
          style={{ marginTop: 16 }}
        />
      </Card>

      {/* 创建配置模态框 */}
      <Modal
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Key size={18} style={{ color: '#8b5cf6' }} />
            添加AI配置
          </div>
        }
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false)
          form.resetFields()
        }}
        onOk={handleCreate}
        confirmLoading={loading}
        width={600}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            provider: 'deepseek',
            model: 'deepseek-chat',
          }}
        >
          <Form.Item
            label="配置名称"
            name="name"
            rules={[{ required: true, message: '请输入配置名称' }]}
            tooltip="给你的配置起个名字，方便识别"
          >
            <Input placeholder="例如: DeepSeek主账号" />
          </Form.Item>

          <Form.Item label="服务提供商" name="provider">
            <Input disabled value="deepseek" />
          </Form.Item>

          <Form.Item
            label={
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span>API密钥</span>
                <Tooltip title="从DeepSeek平台获取">
                  <Zap size={14} style={{ color: '#737373' }} />
                </Tooltip>
              </div>
            }
            name="api_key"
            rules={[{ required: true, message: '请输入API密钥' }]}
          >
            <Input.Password placeholder="sk-xxxxxxxxxxxxxxxx" style={{ fontFamily: 'monospace' }} />
          </Form.Item>

          <Form.Item label="模型" name="model" tooltip="选择要使用的模型">
            <Input disabled value="deepseek-chat" />
          </Form.Item>

          <Alert
            message="安全提示"
            description="API密钥将加密存储在数据库中。建议定期更换密钥以保证安全。"
            type="info"
            showIcon
            style={{ marginTop: 16 }}
          />
        </Form>
      </Modal>

      {/* 编辑配置模态框 */}
      <Modal
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Edit size={18} style={{ color: '#8b5cf6' }} />
            编辑AI配置
          </div>
        }
        open={editModalOpen}
        onCancel={() => {
          setEditModalOpen(false)
          setEditingConfig(null)
          editForm.resetFields()
        }}
        onOk={handleEdit}
        confirmLoading={loading}
        width={600}
      >
        <Form form={editForm} layout="vertical">
          <Form.Item
            label="配置名称"
            name="name"
            rules={[{ required: true, message: '请输入配置名称' }]}
          >
            <Input placeholder="例如: DeepSeek主账号" />
          </Form.Item>

          <Form.Item
            label="新API密钥"
            name="api_key"
            rules={[{ required: true, message: '请输入API密钥' }]}
            tooltip="留空则不更新API密钥"
          >
            <Input.Password placeholder="sk-xxxxxxxxxxxxxxxx" style={{ fontFamily: 'monospace' }} />
          </Form.Item>

          <Form.Item
            label="模型"
            name="model"
            rules={[{ required: true, message: '请输入模型名称' }]}
          >
            <Input placeholder="deepseek-chat" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default AIConfigManagement
