import { useState } from 'react'
import { App, Button, Card, Form, Input, Typography } from 'antd'
import { LockKeyhole, UserRound } from 'lucide-react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { authApi } from '@/services/api'
import { useUserStore } from '@/stores/useUserStore'

type LoginValues = {
  username: string
  password: string
}

export default function LoginPage() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const { isAuthenticated, setToken, setUser } = useUserStore()
  const [loading, setLoading] = useState(false)

  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />
  }

  const submit = async (values: LoginValues) => {
    setLoading(true)
    try {
      const result = await authApi.login(values.username.trim(), values.password)
      setToken(result.access_token)
      setUser(result.user)
      const target = (location.state as { from?: string } | null)?.from || '/dashboard'
      navigate(target, { replace: true })
    } catch (error: any) {
      const detail = error?.response?.data?.detail
      message.error(detail === 'Invalid credentials' ? '账号或密码错误' : (detail || '登录失败'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        padding: 24,
        background: 'radial-gradient(circle at 75% 10%, rgba(24,144,255,.16), transparent 36%), #0d0d0d',
      }}
    >
      <Card style={{ width: 'min(400px, 100%)', borderColor: '#2a2a2a' }} styles={{ body: { padding: 30 } }}>
        <Typography.Title level={3} style={{ margin: 0 }}>OKK QUANT</Typography.Title>
        <Typography.Text type="secondary">登录后才能启动、停止或修改实盘策略</Typography.Text>

        <Form<LoginValues>
          layout="vertical"
          initialValues={{ username: 'admin' }}
          onFinish={submit}
          style={{ marginTop: 26 }}
        >
          <Form.Item name="username" label="账号" rules={[{ required: true, message: '请输入账号' }]}>
            <Input prefix={<UserRound size={16} />} autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockKeyhole size={16} />} autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={loading} block size="large">
            登录
          </Button>
        </Form>
      </Card>
    </div>
  )
}
