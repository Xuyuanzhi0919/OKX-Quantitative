/**
 * 风控管理页面 - 优化版
 */
import { useState, useEffect } from 'react'
import {
  Card,
  Table,
  Button,
  Tag,
  Space,
  Modal,
  Form,
  Input,
  Select,
  InputNumber,
  Switch,
  Popconfirm,
  Tooltip,
  Alert,
  Descriptions,
  Divider,
  Row,
  Col,
  Statistic,
  App,
} from 'antd'
import { Plus, Pencil, Trash2, Power, AlertTriangle, Info, CheckCircle } from 'lucide-react'
import type { ColumnsType } from 'antd/es/table'
import {
  getRiskRules,
  createRiskRule,
  updateRiskRule,
  deleteRiskRule,
  emergencyStop,
  type RiskRule,
} from '@/services/riskControl'
import { strategyApi } from '@/services/api'
import type { Strategy } from '@/types'

const RiskControlPage = () => {
  const { message, modal } = App.useApp()
  const [rules, setRules] = useState<RiskRule[]>([])
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingRule, setEditingRule] = useState<RiskRule | null>(null)
  const [form] = Form.useForm()

  // 监听风控级别变化
  const watchLevel = Form.useWatch('level', form)
  const watchRiskType = Form.useWatch('risk_type', form)

  // 加载策略列表
  const loadStrategies = async () => {
    try {
      const response = await strategyApi.getList()
      setStrategies(response.items || [])
    } catch (error) {
      // 处理错误
    }
  }

  // 加载风控规则
  const loadRules = async () => {
    try {
      setLoading(true)
      const data = await getRiskRules()
      setRules(data)
    } catch (error) {
      message.error('加载失败: ' + (error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRules()
    loadStrategies()
  }, [])

  // 打开创建/编辑模态框
  const handleOpenModal = (rule?: RiskRule) => {
    setEditingRule(rule || null)
    if (rule) {
      form.setFieldsValue(rule)
    } else {
      form.resetFields()
      form.setFieldsValue({
        level: 'global',
        action_on_trigger: 'warn',
        warning_threshold: 0.8,
        is_enabled: true,
      })
    }
    setModalOpen(true)
  }

  // 提交表单
  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()

      // 如果是全局级别，移除strategy_id
      if (values.level === 'global') {
        delete values.strategy_id
      }

      if (editingRule) {
        await updateRiskRule(editingRule.id!, values)
        message.success('更新成功')
      } else {
        await createRiskRule(values)
        message.success('创建成功')
      }
      setModalOpen(false)
      loadRules()
    } catch (error) {
      if ((error as any).errorFields) {
        message.error('请检查表单填写')
      } else {
        message.error('操作失败: ' + (error as Error).message)
      }
    }
  }

  // 删除规则
  const handleDelete = async (id: number) => {
    try {
      await deleteRiskRule(id)
      message.success('删除成功')
      loadRules()
    } catch (error) {
      message.error('删除失败: ' + (error as Error).message)
    }
  }

  // 切换启用状态
  const handleToggleEnabled = async (rule: RiskRule) => {
    try {
      await updateRiskRule(rule.id!, { is_enabled: !rule.is_enabled })
      message.success(rule.is_enabled ? '已禁用' : '已启用')
      loadRules()
    } catch (error) {
      message.error('操作失败: ' + (error as Error).message)
    }
  }

  // 紧急停止
  const handleEmergencyStop = async () => {
    modal.confirm({
      title: '紧急停止确认',
      icon: <AlertTriangle style={{ color: '#ff4d4f' }} />,
      content: '确定要暂停所有策略吗？此操作将立即停止所有运行中的策略！',
      okText: '确认暂停',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          const result = await emergencyStop({ action: 'pause_all' })
          message.success(result.message)
          message.info(`已暂停 ${result.affected_strategies.length} 个策略`)
        } catch (error) {
          message.error('操作失败: ' + (error as Error).message)
        }
      },
    })
  }

  // 风控类型标签颜色
  const getRiskTypeColor = (type: string) => {
    const colors: Record<string, string> = {
      capital: 'blue',
      position: 'cyan',
      loss: 'red',
      drawdown: 'orange',
      frequency: 'purple',
    }
    return colors[type] || 'default'
  }

  // 风控类型中文
  const getRiskTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      capital: '资金',
      position: '持仓',
      loss: '亏损',
      drawdown: '回撤',
      frequency: '频率',
    }
    return labels[type] || type
  }

  // 动作类型中文和颜色
  const getActionInfo = (action: string) => {
    const info: Record<string, { label: string; color: string }> = {
      warn: { label: '警告', color: 'default' },
      limit: { label: '限制', color: 'orange' },
      pause: { label: '暂停', color: 'red' },
      close: { label: '平仓', color: 'volcano' },
    }
    return info[action] || { label: action, color: 'default' }
  }

  // 获取策略名称
  const getStrategyName = (strategyId?: number) => {
    if (!strategyId) return '-'
    const strategy = strategies.find((s) => s.id === strategyId)
    return strategy ? strategy.name : `策略 #${strategyId}`
  }

  // 格式化配置详情
  const formatRuleConfig = (rule: RiskRule) => {
    const configs: string[] = []

    if (rule.risk_type === 'capital') {
      if (rule.min_available_balance) configs.push(`最小可用: ${rule.min_available_balance} USDT`)
      if (rule.max_position_value) configs.push(`最大持仓: ${rule.max_position_value} USDT`)
    } else if (rule.risk_type === 'position') {
      if (rule.max_position_per_symbol) configs.push(`单币种上限: ${rule.max_position_per_symbol}`)
      if (rule.max_concentration_ratio)
        configs.push(`集中度: ${(rule.max_concentration_ratio * 100).toFixed(1)}%`)
    } else if (rule.risk_type === 'loss') {
      if (rule.daily_loss_limit) configs.push(`日亏损: ${rule.daily_loss_limit} USDT`)
      if (rule.total_loss_limit) configs.push(`总亏损: ${rule.total_loss_limit} USDT`)
      if (rule.max_consecutive_losses) configs.push(`连亏: ${rule.max_consecutive_losses} 次`)
    } else if (rule.risk_type === 'drawdown') {
      if (rule.max_drawdown_percent)
        configs.push(`回撤: ${(rule.max_drawdown_percent * 100).toFixed(1)}%`)
    } else if (rule.risk_type === 'frequency') {
      if (rule.max_trades_per_period) configs.push(`周期内: ${rule.max_trades_per_period} 单`)
      if (rule.period_seconds) configs.push(`周期: ${rule.period_seconds} 秒`)
    }

    return configs.join(' | ') || '未配置'
  }

  // 表格列
  const columns: ColumnsType<RiskRule> = [
    {
      title: '规则信息',
      dataIndex: 'name',
      key: 'name',
      width: 220,
      render: (name, record) => (
        <Space direction="vertical" size={0}>
          <span style={{ fontWeight: 500 }}>{name}</span>
          {record.description && (
            <span style={{ fontSize: 12, color: '#888' }}>{record.description}</span>
          )}
          <Space size={4} style={{ marginTop: 4 }}>
            <Tag color={record.level === 'global' ? 'gold' : 'green'} style={{ margin: 0 }}>
              {record.level === 'global' ? '全局' : getStrategyName(record.strategy_id)}
            </Tag>
          </Space>
        </Space>
      ),
    },
    {
      title: '风控类型',
      dataIndex: 'risk_type',
      key: 'risk_type',
      width: 100,
      render: (type) => <Tag color={getRiskTypeColor(type)}>{getRiskTypeLabel(type)}</Tag>,
    },
    {
      title: '配置详情',
      key: 'config',
      width: 250,
      render: (_, record) => (
        <span style={{ fontSize: 12, color: '#a3a3a3' }}>{formatRuleConfig(record)}</span>
      ),
    },
    {
      title: '触发动作',
      dataIndex: 'action_on_trigger',
      key: 'action_on_trigger',
      width: 100,
      render: (action) => {
        const actionInfo = getActionInfo(action)
        return <Tag color={actionInfo.color}>{actionInfo.label}</Tag>
      },
    },
    {
      title: '状态',
      key: 'status',
      width: 150,
      render: (_, record) => (
        <Space direction="vertical" size={4}>
          <Switch
            checked={record.is_enabled}
            onChange={() => handleToggleEnabled(record)}
            checkedChildren="已启用"
            unCheckedChildren="已禁用"
            size="small"
          />
          {record.is_triggered && (
            <Space size={4}>
              <AlertTriangle size={12} style={{ color: '#ff4d4f' }} />
              <span style={{ fontSize: 12, color: '#ff4d4f' }}>
                已触发 {record.trigger_count} 次
              </span>
            </Space>
          )}
          {!record.is_triggered && record.is_enabled && (
            <Space size={4}>
              <CheckCircle size={12} style={{ color: '#52c41a' }} />
              <span style={{ fontSize: 12, color: '#52c41a' }}>正常</span>
            </Space>
          )}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 130,
      fixed: 'right',
      render: (_, record) => (
        <Space size={8}>
          <Button
            type="link"
            size="small"
            icon={<Pencil size={14} />}
            onClick={() => handleOpenModal(record)}
            style={{ padding: '0 4px' }}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定删除此规则吗？"
            description="删除后无法恢复"
            onConfirm={() => handleDelete(record.id!)}
            okText="确定"
            cancelText="取消"
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<Trash2 size={14} />}
              style={{ padding: '0 4px' }}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // 统计数据
  const stats = {
    total: rules.length,
    enabled: rules.filter((r) => r.is_enabled).length,
    triggered: rules.filter((r) => r.is_triggered).length,
  }

  return (
    <div style={{ padding: 0 }}>
      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card>
            <Statistic title="总规则数" value={stats.total} prefix={<Info size={16} />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="已启用"
              value={stats.enabled}
              valueStyle={{ color: '#3f8600' }}
              prefix={<CheckCircle size={16} />}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="已触发"
              value={stats.triggered}
              valueStyle={{ color: stats.triggered > 0 ? '#cf1322' : '#666' }}
              prefix={<AlertTriangle size={16} />}
            />
          </Card>
        </Col>
      </Row>

      <Alert
        message="风控系统说明"
        description="配置风控规则以保护您的交易资金安全。触发风控时系统会根据配置执行相应动作（警告、限制、暂停或平仓）。建议优先配置资金和亏损风控。"
        type="info"
        showIcon
        closable
        style={{ marginBottom: 16 }}
      />

      <Card
        title={
          <Space>
            <span>风控规则管理</span>
            <Tag color="blue">{stats.enabled} 启用</Tag>
          </Space>
        }
        extra={
          <Space>
            <Button danger icon={<Power size={14} />} onClick={handleEmergencyStop}>
              紧急停止
            </Button>
            <Button type="primary" icon={<Plus size={14} />} onClick={() => handleOpenModal()}>
              创建规则
            </Button>
          </Space>
        }
      >
        <Table
          dataSource={rules}
          columns={columns}
          loading={loading}
          rowKey="id"
          scroll={{ x: 1100 }}
          pagination={{
            pageSize: 10,
            showTotal: (total) => `共 ${total} 条规则`,
          }}
        />
      </Card>

      <Modal
        title={editingRule ? '编辑风控规则' : '创建风控规则'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        width={700}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          {/* 基本信息 */}
          <Divider orientation="left">基本信息</Divider>

          <Form.Item
            name="name"
            label="规则名称"
            rules={[
              { required: true, message: '请输入规则名称' },
              { max: 100, message: '名称最多100个字符' },
            ]}
          >
            <Input placeholder="例如：日亏损限额 500 USDT" />
          </Form.Item>

          <Form.Item name="description" label="规则描述">
            <Input.TextArea
              rows={2}
              placeholder="详细说明此规则的作用和触发条件"
              maxLength={500}
              showCount
            />
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="level"
                label="风控级别"
                rules={[{ required: true }]}
                tooltip="全局级别对所有策略生效，策略级别仅对指定策略生效"
              >
                <Select>
                  <Select.Option value="global">全局 (所有策略)</Select.Option>
                  <Select.Option value="strategy">策略级 (指定策略)</Select.Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              {watchLevel === 'strategy' && (
                <Form.Item
                  name="strategy_id"
                  label="选择策略"
                  rules={[{ required: true, message: '请选择策略' }]}
                >
                  <Select
                    placeholder="选择要应用此规则的策略"
                    showSearch
                    optionFilterProp="children"
                  >
                    {strategies.map((strategy) => (
                      <Select.Option key={strategy.id} value={strategy.id}>
                        {strategy.name} ({strategy.symbol})
                      </Select.Option>
                    ))}
                  </Select>
                </Form.Item>
              )}
            </Col>
          </Row>

          {/* 风控配置 */}
          <Divider orientation="left">风控配置</Divider>

          <Form.Item
            name="risk_type"
            label="风控类型"
            rules={[{ required: true, message: '请选择风控类型' }]}
          >
            <Select placeholder="选择风控类型">
              <Select.Option value="capital">
                <Space>
                  <Tag color="blue">资金</Tag>
                  <span>控制最小可用余额和最大持仓价值</span>
                </Space>
              </Select.Option>
              <Select.Option value="position">
                <Space>
                  <Tag color="cyan">持仓</Tag>
                  <span>限制持仓数量和单笔订单大小</span>
                </Space>
              </Select.Option>
              <Select.Option value="loss">
                <Space>
                  <Tag color="red">亏损</Tag>
                  <span>限制日亏损、总亏损和连续亏损次数</span>
                </Space>
              </Select.Option>
              <Select.Option value="drawdown">
                <Space>
                  <Tag color="orange">回撤</Tag>
                  <span>控制账户最大回撤百分比</span>
                </Space>
              </Select.Option>
              <Select.Option value="frequency">
                <Space>
                  <Tag color="purple">频率</Tag>
                  <span>限制订单频率，防止过度交易</span>
                </Space>
              </Select.Option>
            </Select>
          </Form.Item>

          {/* 动态表单字段 */}
          <Form.Item
            noStyle
            shouldUpdate={(prevValues, currentValues) =>
              prevValues.risk_type !== currentValues.risk_type
            }
          >
            {({ getFieldValue }) => {
              const riskType = getFieldValue('risk_type')

              if (riskType === 'capital') {
                return (
                  <>
                    <Row gutter={16}>
                      <Col span={12}>
                        <Form.Item
                          name="min_available_balance"
                          label="最小可用资金 (USDT)"
                          tooltip="可用余额低于此值时触发风控"
                          rules={[
                            { required: true, message: '请输入最小可用资金' },
                            { type: 'number', min: 0, message: '必须大于等于0' },
                          ]}
                        >
                          <InputNumber min={0} style={{ width: '100%' }} placeholder="例如: 1000" />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item
                          name="max_position_value"
                          label="最大持仓价值 (USDT)"
                          tooltip="持仓总价值超过此值时触发风控"
                        >
                          <InputNumber
                            min={0}
                            style={{ width: '100%' }}
                            placeholder="例如: 10000"
                          />
                        </Form.Item>
                      </Col>
                    </Row>
                  </>
                )
              }

              if (riskType === 'position') {
                return (
                  <>
                    <Row gutter={16}>
                      <Col span={12}>
                        <Form.Item
                          name="max_position_size"
                          label="最大持仓数量"
                          tooltip="持仓数量超过此值时触发风控"
                          rules={[
                            { required: true, message: '请输入最大持仓数量' },
                            { type: 'number', min: 0, message: '必须大于0' },
                          ]}
                        >
                          <InputNumber min={0} style={{ width: '100%' }} placeholder="例如: 100" />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item
                          name="max_single_order_size"
                          label="单笔订单最大数量"
                          tooltip="单笔订单数量超过此值时触发风控"
                        >
                          <InputNumber min={0} style={{ width: '100%' }} placeholder="例如: 10" />
                        </Form.Item>
                      </Col>
                    </Row>
                  </>
                )
              }

              if (riskType === 'loss') {
                return (
                  <>
                    <Row gutter={16}>
                      <Col span={12}>
                        <Form.Item
                          name="daily_loss_limit"
                          label="日亏损限额 (USDT)"
                          tooltip="当日亏损超过此值时触发风控"
                        >
                          <InputNumber min={0} style={{ width: '100%' }} placeholder="例如: 500" />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item
                          name="total_loss_limit"
                          label="总亏损限额 (USDT)"
                          tooltip="累计亏损超过此值时触发风控"
                        >
                          <InputNumber min={0} style={{ width: '100%' }} placeholder="例如: 2000" />
                        </Form.Item>
                      </Col>
                    </Row>
                    <Form.Item
                      name="max_consecutive_losses"
                      label="最大连续亏损次数"
                      tooltip="连续亏损次数达到此值时触发风控"
                    >
                      <InputNumber min={1} style={{ width: '100%' }} placeholder="例如: 5" />
                    </Form.Item>
                  </>
                )
              }

              if (riskType === 'drawdown') {
                return (
                  <Form.Item
                    name="max_drawdown_percent"
                    label="最大回撤百分比"
                    tooltip="回撤百分比超过此值时触发风控 (0.15 = 15%)"
                    rules={[
                      { required: true, message: '请输入最大回撤百分比' },
                      { type: 'number', min: 0, max: 1, message: '必须在 0-1 之间' },
                    ]}
                  >
                    <InputNumber
                      min={0}
                      max={1}
                      step={0.01}
                      style={{ width: '100%' }}
                      placeholder="例如: 0.15 (15%)"
                      formatter={(value) => `${(Number(value || 0) * 100).toFixed(0)}%`}
                      parser={(value) => (Number(value?.replace('%', '')) / 100) as any}
                    />
                  </Form.Item>
                )
              }

              if (riskType === 'frequency') {
                return (
                  <>
                    <Row gutter={16}>
                      <Col span={12}>
                        <Form.Item
                          name="max_orders_per_minute"
                          label="每分钟最大订单数"
                          tooltip="每分钟订单数超过此值时触发风控"
                        >
                          <InputNumber min={1} style={{ width: '100%' }} placeholder="例如: 10" />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item
                          name="max_daily_orders"
                          label="每日最大订单数"
                          tooltip="每日订单总数超过此值时触发风控"
                        >
                          <InputNumber min={1} style={{ width: '100%' }} placeholder="例如: 1000" />
                        </Form.Item>
                      </Col>
                    </Row>
                  </>
                )
              }

              return (
                <Alert
                  message="请选择风控类型"
                  description="选择风控类型后，将显示相应的配置选项"
                  type="info"
                  showIcon
                />
              )
            }}
          </Form.Item>

          {/* 触发配置 */}
          <Divider orientation="left">触发配置</Divider>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="action_on_trigger"
                label="触发动作"
                rules={[{ required: true }]}
                tooltip="触发风控时执行的动作"
              >
                <Select>
                  <Select.Option value="warn">
                    <Space>
                      <Tag color="default">警告</Tag>
                      <span>仅发送警告通知</span>
                    </Space>
                  </Select.Option>
                  <Select.Option value="limit">
                    <Space>
                      <Tag color="orange">限制</Tag>
                      <span>禁止新建订单</span>
                    </Space>
                  </Select.Option>
                  <Select.Option value="pause">
                    <Space>
                      <Tag color="red">暂停</Tag>
                      <span>暂停策略运行</span>
                    </Space>
                  </Select.Option>
                  <Select.Option value="close">
                    <Space>
                      <Tag color="volcano">平仓</Tag>
                      <span>平仓并暂停策略</span>
                    </Space>
                  </Select.Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="warning_threshold"
                label="警告阈值"
                tooltip="达到限额的此百分比时提前预警 (0.8 = 80%)"
                rules={[
                  { required: true, message: '请输入警告阈值' },
                  { type: 'number', min: 0, max: 1, message: '必须在 0-1 之间' },
                ]}
              >
                <InputNumber
                  min={0}
                  max={1}
                  step={0.1}
                  style={{ width: '100%' }}
                  formatter={(value) => `${(Number(value || 0) * 100).toFixed(0)}%`}
                  parser={(value) => (Number(value?.replace('%', '')) / 100) as any}
                />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="is_enabled"
            label="启用规则"
            valuePropName="checked"
            tooltip="创建后立即启用此规则"
          >
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default RiskControlPage
