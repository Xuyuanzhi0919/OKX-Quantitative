import { Tabs } from 'antd'
import { Wallet, List } from 'lucide-react'
import PositionList from '../positions/PositionList'
import OrderList from '../orders/OrderList'

const TradingManagement = () => {
  const items = [
    {
      key: 'positions',
      label: (
        <span>
          <Wallet size={14} />
          持仓管理
        </span>
      ),
      children: <PositionList />,
    },
    {
      key: 'orders',
      label: (
        <span>
          <List size={14} />
          订单管理
        </span>
      ),
      children: <OrderList />,
    },
  ]

  return (
    <div style={{ padding: '0 24px 24px' }}>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ margin: 0, fontSize: 24, fontWeight: 600 }}>交易管理</h2>
        <p style={{ margin: '8px 0 0', color: '#737373' }}>实时监控持仓和订单状态</p>
      </div>
      <Tabs defaultActiveKey="positions" items={items} size="large" />
    </div>
  )
}

export default TradingManagement
