import { useState } from 'react'
import { Card, Form, Input, InputNumber, Button, Row, Col, Radio, Space, Divider, App } from 'antd'
import { Save, Key, Shield, CheckCircle, AlertTriangle } from 'lucide-react'
import { useTranslation } from 'react-i18next'

const Settings = () => {
  const { t } = useTranslation()
  const { message } = App.useApp()
  const [apiForm] = Form.useForm()
  const [riskForm] = Form.useForm()
  const [testing, setTesting] = useState(false)

  const onSaveApi = (values: any) => {
    message.success(t('message.saveSuccess'))
  }

  const onSaveRisk = (values: any) => {
    message.success(t('message.saveSuccess'))
  }

  const testConnection = async () => {
    try {
      setTesting(true)
      // TODO: 实际测试API连接
      await new Promise((resolve) => setTimeout(resolve, 1500))
      message.success(t('message.connectionSuccess'))
    } catch (error) {
      message.error(t('message.connectionFailed'))
    } finally {
      setTesting(false)
    }
  }

  return (
    <div>
      {/* 安全警告 */}
      <Card
        variant="borderless"
        size="small"
        style={{
          marginBottom: 16,
          background: 'rgba(245, 158, 11, 0.1)',
          border: '1px solid rgba(245, 158, 11, 0.2)',
        }}
      >
        <div style={{ display: 'flex', gap: 12 }}>
          <AlertTriangle size={20} style={{ color: '#f59e0b', marginTop: 2 }} />
          <div>
            <div
              style={{
                fontWeight: 600,
                marginBottom: 6,
                color: '#f59e0b',
                fontSize: 12,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              {t('settings.securityWarning')}
            </div>
            <div
              style={{ fontSize: 12, color: '#a3a3a3', lineHeight: 1.6, whiteSpace: 'pre-line' }}
            >
              {t('settings.securityTips')}
            </div>
          </div>
        </div>
      </Card>

      <Row gutter={[16, 16]}>
        {/* API配置 */}
        <Col xs={24} lg={14}>
          <Card
            title={
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Key size={14} />
                <div className="pro-card-header" style={{ margin: 0 }}>
                  {t('settings.apiConfig').toUpperCase()}
                </div>
              </div>
            }
            variant="borderless"
            size="small"
          >
            <Form form={apiForm} layout="vertical" onFinish={onSaveApi}>
              {/* 环境选择 */}
              <Form.Item
                label={
                  <span className="pro-card-header">{t('settings.environment').toUpperCase()}</span>
                }
                name="environment"
                initialValue="demo"
                style={{ marginBottom: 20 }}
              >
                <Radio.Group size="large" buttonStyle="solid">
                  <Radio.Button value="demo">{t('settings.demo')}</Radio.Button>
                  <Radio.Button value="live">{t('settings.live')}</Radio.Button>
                </Radio.Group>
              </Form.Item>

              {/* API Key */}
              <Form.Item
                label={
                  <span className="pro-card-header">{t('settings.apiKey').toUpperCase()}</span>
                }
                name="apiKey"
                rules={[{ required: true, message: t('message.required') }]}
                style={{ marginBottom: 20 }}
              >
                <Input
                  size="large"
                  placeholder={`Enter your OKX ${t('settings.apiKey')}`}
                  prefix={<Key size={14} style={{ color: '#737373' }} />}
                  style={{ fontFamily: 'monospace' }}
                />
              </Form.Item>

              {/* Secret Key */}
              <Form.Item
                label={
                  <span className="pro-card-header">{t('settings.secretKey').toUpperCase()}</span>
                }
                name="secretKey"
                rules={[{ required: true, message: t('message.required') }]}
                style={{ marginBottom: 20 }}
              >
                <Input.Password
                  size="large"
                  placeholder={`Enter your OKX ${t('settings.secretKey')}`}
                  prefix={<Key size={14} style={{ color: '#737373' }} />}
                  style={{ fontFamily: 'monospace' }}
                />
              </Form.Item>

              {/* Passphrase */}
              <Form.Item
                label={
                  <span className="pro-card-header">{t('settings.passphrase').toUpperCase()}</span>
                }
                name="passphrase"
                rules={[{ required: true, message: t('message.required') }]}
                style={{ marginBottom: 20 }}
              >
                <Input.Password
                  size="large"
                  placeholder={`Enter your OKX ${t('settings.passphrase')}`}
                  prefix={<Key size={14} style={{ color: '#737373' }} />}
                  style={{ fontFamily: 'monospace' }}
                />
              </Form.Item>

              <Divider style={{ margin: '20px 0', borderColor: '#2a2a2a' }} />

              {/* 操作按钮 */}
              <Form.Item style={{ marginBottom: 0 }}>
                <Space size={12}>
                  <Button
                    type="primary"
                    htmlType="submit"
                    size="large"
                    icon={<Save size={14} />}
                    style={{ minWidth: 140, fontWeight: 600 }}
                  >
                    {t('settings.saveConfig').toUpperCase()}
                  </Button>
                  <Button
                    size="large"
                    icon={<CheckCircle size={14} />}
                    onClick={testConnection}
                    loading={testing}
                    style={{ minWidth: 140, fontWeight: 600 }}
                  >
                    {t('settings.testConnection').toUpperCase()}
                  </Button>
                </Space>
              </Form.Item>
            </Form>
          </Card>
        </Col>

        {/* 风控设置 */}
        <Col xs={24} lg={10}>
          <Card
            title={
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Shield size={14} />
                <div className="pro-card-header" style={{ margin: 0 }}>
                  {t('settings.riskManagement').toUpperCase()}
                </div>
              </div>
            }
            variant="borderless"
            size="small"
          >
            <Form form={riskForm} layout="vertical" onFinish={onSaveRisk}>
              {/* 最大仓位 */}
              <Form.Item
                label={
                  <span className="pro-card-header">{t('settings.maxPosition').toUpperCase()}</span>
                }
                name="maxPosition"
                initialValue={10000}
                rules={[
                  { required: true, message: t('message.required') },
                  { type: 'number', min: 0 },
                ]}
                style={{ marginBottom: 20 }}
              >
                <InputNumber
                  size="large"
                  style={{ width: '100%' }}
                  placeholder="10000"
                  precision={2}
                  formatter={(value) => `${value}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                  parser={(value) => value!.replace(/,/g, '')}
                />
              </Form.Item>

              {/* 全局止损 */}
              <Form.Item
                label={
                  <span className="pro-card-header">{t('settings.stopLoss').toUpperCase()}</span>
                }
                name="stopLoss"
                initialValue={5}
                rules={[
                  { required: true, message: t('message.required') },
                  { type: 'number', min: 0, max: 100 },
                ]}
                style={{ marginBottom: 20 }}
              >
                <InputNumber
                  size="large"
                  style={{ width: '100%' }}
                  placeholder="5"
                  precision={2}
                  min={0}
                  max={100}
                />
              </Form.Item>

              {/* 单笔最大投入 */}
              <Form.Item
                label={
                  <span className="pro-card-header">
                    {t('settings.maxOrderSize').toUpperCase()}
                  </span>
                }
                name="maxOrderSize"
                initialValue={1000}
                rules={[
                  { required: true, message: t('message.required') },
                  { type: 'number', min: 0 },
                ]}
                style={{ marginBottom: 20 }}
              >
                <InputNumber
                  size="large"
                  style={{ width: '100%' }}
                  placeholder="1000"
                  precision={2}
                  formatter={(value) => `${value}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                  parser={(value) => value!.replace(/,/g, '')}
                />
              </Form.Item>

              {/* 最大杠杆 */}
              <Form.Item
                label={
                  <span className="pro-card-header">{t('settings.maxLeverage').toUpperCase()}</span>
                }
                name="maxLeverage"
                initialValue={5}
                rules={[
                  { required: true, message: t('message.required') },
                  { type: 'number', min: 1, max: 125 },
                ]}
                style={{ marginBottom: 20 }}
              >
                <InputNumber
                  size="large"
                  style={{ width: '100%' }}
                  placeholder="5"
                  precision={0}
                  min={1}
                  max={125}
                  suffix="x"
                />
              </Form.Item>

              <Divider style={{ margin: '20px 0', borderColor: '#2a2a2a' }} />

              {/* 保存按钮 */}
              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  type="primary"
                  htmlType="submit"
                  size="large"
                  icon={<Save size={14} />}
                  style={{ width: '100%', fontWeight: 600 }}
                >
                  {t('settings.saveRiskSettings').toUpperCase()}
                </Button>
              </Form.Item>
            </Form>
          </Card>

          {/* 风险等级指示 */}
          <Card
            variant="borderless"
            size="small"
            style={{
              marginTop: 16,
              background: 'rgba(34, 197, 94, 0.1)',
              border: '1px solid rgba(34, 197, 94, 0.2)',
            }}
          >
            <div style={{ display: 'flex', gap: 12 }}>
              <Shield size={16} style={{ color: '#22c55e', marginTop: 2 }} />
              <div>
                <div
                  style={{
                    fontWeight: 600,
                    marginBottom: 4,
                    color: '#22c55e',
                    fontSize: 11,
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                  }}
                >
                  {t('settings.riskLevel')}: {t('settings.lowRisk')}
                </div>
                <div style={{ fontSize: 11, color: '#a3a3a3', lineHeight: 1.5 }}>
                  {t('settings.riskLevelDesc')}
                </div>
              </div>
            </div>
          </Card>
        </Col>
      </Row>

      {/* API权限说明 */}
      <Card
        title={
          <div className="pro-card-header" style={{ margin: 0 }}>
            {t('settings.requiredPermissions').toUpperCase()}
          </div>
        }
        variant="borderless"
        size="small"
        style={{ marginTop: 16 }}
      >
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={8}>
            <div style={{ padding: '12px 0' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <CheckCircle size={16} style={{ color: '#22c55e' }} />
                <span style={{ fontWeight: 600, fontSize: 12, textTransform: 'uppercase' }}>
                  {t('settings.readPermission')}
                </span>
              </div>
              <div style={{ fontSize: 11, color: '#737373', lineHeight: 1.5 }}>
                {t('settings.readDesc')}
              </div>
            </div>
          </Col>
          <Col xs={24} sm={8}>
            <div style={{ padding: '12px 0' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <CheckCircle size={16} style={{ color: '#22c55e' }} />
                <span style={{ fontWeight: 600, fontSize: 12, textTransform: 'uppercase' }}>
                  {t('settings.tradePermission')}
                </span>
              </div>
              <div style={{ fontSize: 11, color: '#737373', lineHeight: 1.5 }}>
                {t('settings.tradeDesc')}
              </div>
            </div>
          </Col>
          <Col xs={24} sm={8}>
            <div style={{ padding: '12px 0' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <AlertTriangle size={16} style={{ color: '#ef4444' }} />
                <span style={{ fontWeight: 600, fontSize: 12, textTransform: 'uppercase' }}>
                  {t('settings.withdrawDisabled')}
                </span>
              </div>
              <div style={{ fontSize: 11, color: '#737373', lineHeight: 1.5 }}>
                {t('settings.withdrawDesc')}
              </div>
            </div>
          </Col>
        </Row>
      </Card>
    </div>
  )
}

export default Settings
