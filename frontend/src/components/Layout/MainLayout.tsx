import { useState, useEffect } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Drawer, Space } from 'antd'
import {
  LayoutDashboard,
  Zap,
  Settings,
  Menu as MenuIcon,
  Wifi,
  WifiOff,
  Wallet,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useWebSocketStore } from '@/stores/useWebSocketStore'
import LanguageSwitcher from '@/components/LanguageSwitcher'

const { Header, Sider, Content } = Layout

const MainLayout = () => {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const [isMobile, setIsMobile] = useState(false)
  const [drawerVisible, setDrawerVisible] = useState(false)
  const isConnected = useWebSocketStore((state) => state.connected)

  // 检测屏幕尺寸
  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 768)
    }
    checkMobile()
    window.addEventListener('resize', checkMobile)
    return () => window.removeEventListener('resize', checkMobile)
  }, [])

  const menuItems = [
    {
      key: '/dashboard',
      icon: <LayoutDashboard size={16} />,
      label: t('nav.dashboard'),
    },
    {
      key: '/strategies',
      icon: <Zap size={16} />,
      label: t('nav.strategy'),
    },
    {
      key: '/trading-management',
      icon: <Wallet size={16} />,
      label: '持仓与订单',
    },
    {
      key: '/api-config',
      icon: <Settings size={16} />,
      label: 'OKX API',
    },
  ]

  const menuContent = (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Logo区域 */}
      <div
        style={{
          height: 64,
          display: 'flex',
          alignItems: 'center',
          justifyContent: collapsed ? 'center' : 'flex-start',
          padding: collapsed ? '0' : '0 24px',
          borderBottom: '1px solid #2a2a2a',
        }}
      >
        {!collapsed ? (
          <div>
            <div
              style={{
                fontSize: 16,
                fontWeight: 700,
                color: '#1890ff',
                letterSpacing: '0.5px',
              }}
            >
              OKK QUANT
            </div>
            <div
              style={{
                fontSize: 10,
                color: '#737373',
                marginTop: -2,
                letterSpacing: '1px',
                textTransform: 'uppercase',
              }}
            >
              Trading System
            </div>
          </div>
        ) : (
          <div
            style={{
              fontSize: 18,
              fontWeight: 700,
              color: '#1890ff',
            }}
          >
            OQ
          </div>
        )}
      </div>

      {/* 菜单区域 */}
      <Menu
        theme="dark"
        mode="inline"
        selectedKeys={[location.pathname]}
        items={menuItems}
        onClick={({ key }) => {
          navigate(key)
          if (isMobile) {
            setDrawerVisible(false)
          }
        }}
        style={{
          flex: 1,
          border: 'none',
          paddingTop: 12,
        }}
      />

      {/* 底部状态栏 */}
      {!collapsed && (
        <div
          style={{
            padding: '12px 20px',
            borderTop: '1px solid #2a2a2a',
            fontSize: 11,
            color: '#737373',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {isConnected ? (
              <>
                <Wifi size={14} style={{ color: '#22c55e' }} />
                <span style={{ color: '#22c55e' }}>{t('common.connected', '已连接')}</span>
              </>
            ) : (
              <>
                <WifiOff size={14} style={{ color: '#ef4444' }} />
                <span style={{ color: '#ef4444' }}>{t('common.disconnected', '未连接')}</span>
              </>
            )}
          </div>
          <div style={{ marginTop: 4 }}>
            v1.0.0
          </div>
        </div>
      )}
    </div>
  )

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {/* 移动端抽屉菜单 */}
      {isMobile ? (
        <Drawer
          placement="left"
          onClose={() => setDrawerVisible(false)}
          open={drawerVisible}
          styles={{ body: { padding: 0, background: '#1a1a1a' }, header: { display: 'none' } }}
          width={250}
        >
          {menuContent}
        </Drawer>
      ) : (
        <Sider
          collapsible
          collapsed={collapsed}
          onCollapse={setCollapsed}
          theme="dark"
          width={220}
          collapsedWidth={64}
          style={{
            background: '#1a1a1a',
            borderRight: '1px solid #2a2a2a',
          }}
        >
          {menuContent}
        </Sider>
      )}

      <Layout>
        {/* Header */}
        <Header
          style={{
            height: 64,
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid #2a2a2a',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 20,
              flex: 1,
              minWidth: 0,
            }}
          >
            {isMobile && (
              <MenuIcon
                size={18}
                style={{
                  color: '#e5e5e5',
                  cursor: 'pointer',
                  flexShrink: 0,
                }}
                onClick={() => setDrawerVisible(true)}
              />
            )}
            <div style={{ minWidth: 0, flex: 1 }}>
              <div
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  color: '#e5e5e5',
                  lineHeight: 1.4,
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {menuItems.find((item) => item.key === location.pathname)?.label || '仪表盘'}
              </div>
            </div>
          </div>

          <Space size={20} style={{ flexShrink: 0 }}>
            {/* 语言切换 */}
            {!isMobile && <LanguageSwitcher />}

            {/* 连接状态 */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 12,
                color: isConnected ? '#22c55e' : '#737373',
                fontWeight: 600,
                whiteSpace: 'nowrap',
              }}
            >
              <div
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: isConnected ? '#22c55e' : '#737373',
                  animation: isConnected ? 'pulse 2s infinite' : 'none',
                }}
              />
              <span>{isConnected ? 'OKX' : t('common.offline', '离线')}</span>
            </div>
          </Space>
        </Header>

        {/* Content */}
        <Content
          style={{
            margin: 0,
            padding: 20,
            minHeight: 'calc(100vh - 64px)',
            overflow: 'auto',
          }}
        >
          <Outlet />
        </Content>
      </Layout>

      <style>{`
        @keyframes pulse {
          0%, 100% {
            opacity: 1;
          }
          50% {
            opacity: 0.5;
          }
        }
      `}</style>
    </Layout>
  )
}

export default MainLayout
