import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider, theme, App as AntApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import enUS from 'antd/locale/en_US'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { wsService, NotificationData } from './services/websocket'
import { useWebSocketStore } from './stores/useWebSocketStore'
import { useUserStore } from './stores/useUserStore'
import LoginPage from './features/auth/LoginPage'

const MainLayout = lazy(() => import('./components/Layout/MainLayout'))
const Dashboard = lazy(() => import('./features/dashboard/Dashboard'))
const StrategyList = lazy(() => import('./features/strategy/StrategyList'))
const TradingManagement = lazy(() => import('./features/trading/TradingManagement'))
const APIConfigManagement = lazy(() => import('./features/settings/APIConfigManagement'))

// 创建React Query客户端
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

// 内部组件，用于访问 App context
function AppContent() {
  const { message } = AntApp.useApp()
  const setConnected = useWebSocketStore((state) => state.setConnected)

  useEffect(() => {
    // 初始化WebSocket连接
    wsService.connect()

    // 监听连接事件
    const unsubscribeConnect = wsService.onConnect(() => {
      setConnected(true)
      // 显示连接成功通知
      message.success('WebSocket实时推送服务已连接')
    })

    const unsubscribeDisconnect = wsService.onDisconnect(() => {
      setConnected(false)
      // 显示断开连接通知
      message.warning('WebSocket连接已断开，正在尝试重新连接...')
    })

    // 监听系统通知
    const unsubscribeNotification = wsService.onNotification((data: NotificationData) => {
      // 根据通知类型显示不同样式的通知
      const messageContent = data.title ? `${data.title}: ${data.message}` : data.message
      message[data.type]({
        content: messageContent,
        duration: data.type === 'error' ? 8 : 5,
      })
    })

    // 清理函数
    return () => {
      unsubscribeConnect()
      unsubscribeDisconnect()
      unsubscribeNotification()
      wsService.disconnect()
    }
  }, [setConnected, message])

  return (
    <BrowserRouter>
      <Suspense fallback={<div style={{ minHeight: '100vh', background: '#0d0d0d' }} />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<ProtectedLayout />}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="strategies" element={<StrategyList />} />
            <Route path="trading-management" element={<TradingManagement />} />
            <Route path="api-config" element={<APIConfigManagement />} />
            <Route path="trading" element={<Navigate to="/trading-management" replace />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}

function ProtectedLayout() {
  const isAuthenticated = useUserStore((state) => state.isAuthenticated)
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: window.location.pathname }} replace />
  }
  return <MainLayout />
}

function App() {
  const { i18n } = useTranslation()

  // 根据当前语言选择Ant Design locale
  const antdLocale = i18n.language === 'en-US' ? enUS : zhCN

  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider
        locale={antdLocale}
        theme={{
          algorithm: theme.darkAlgorithm,
          token: {
            colorPrimary: '#1890ff',
            colorBgBase: '#0d0d0d',
            colorBgContainer: '#1a1a1a',
            colorBgElevated: '#222222',
            colorBorder: '#2a2a2a',
            colorText: '#e5e5e5',
            colorTextSecondary: '#a3a3a3',
            colorTextTertiary: '#737373',
            borderRadius: 4,
            fontSize: 14,
            fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
          },
          components: {
            Card: {
              colorBgContainer: '#1a1a1a',
              colorBorderSecondary: '#2a2a2a',
            },
            Table: {
              colorBgContainer: 'transparent',
              colorBorderSecondary: '#2a2a2a',
            },
          },
        }}
      >
        <AntApp>
          <AppContent />
        </AntApp>
      </ConfigProvider>
    </QueryClientProvider>
  )
}

export default App
