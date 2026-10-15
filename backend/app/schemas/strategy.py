"""
策略相关的Pydantic schemas
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime
from app.models.strategy import StrategyType, StrategyStatus


# 策略基础信息
class StrategyBase(BaseModel):
    """策略基础信息"""

    model_config = ConfigDict(use_enum_values=True)

    name: str = Field(..., description="策略名称")
    type: StrategyType = Field(..., description="策略类型")
    symbol: str = Field(..., description="交易对")
    api_config_id: Optional[int] = Field(None, description="绑定的API配置ID")
    timeframe: Optional[str] = Field(None, description="时间周期")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="策略参数")
    description: Optional[str] = Field(None, description="策略描述")


# 创建策略请求
class StrategyCreate(StrategyBase):
    """创建策略请求"""

    pass


# 更新策略请求
class StrategyUpdate(BaseModel):
    """更新策略请求"""

    name: Optional[str] = None
    symbol: Optional[str] = None
    api_config_id: Optional[int] = None
    timeframe: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


# 策略响应
class StrategyResponse(StrategyBase):
    """策略响应"""

    id: int
    user_id: int
    status: StrategyStatus
    total_profit: float = 0.0
    total_trades: int = 0
    win_rate: float = 0.0
    created_at: datetime
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None

    class Config:
        from_attributes = True  # 允许从ORM模型创建


# 策略列表响应
class StrategyListResponse(BaseModel):
    """策略列表响应"""

    total: int
    items: list[StrategyResponse]


# 网格订单详情
class GridOrderDetail(BaseModel):
    """网格订单详情"""

    grid_index: int = Field(..., description="网格索引")
    buy_price: float = Field(..., description="买入价格")
    sell_price: Optional[float] = Field(None, description="卖出价格")
    buy_status: Optional[str] = Field(None, description="买单状态")
    buy_order_id: Optional[str] = Field(None, description="买单ID")
    buy_filled_amount: float = Field(0, description="买单已成交数量")
    sell_status: Optional[str] = Field(None, description="卖单状态")
    sell_order_id: Optional[str] = Field(None, description="卖单ID")
    sell_filled_amount: float = Field(0, description="卖单已成交数量")


# 策略统计响应
class StrategyStatsResponse(BaseModel):
    """策略统计响应"""

    strategy_id: int
    is_running: bool
    position_size: Optional[float] = None
    position_cost: Optional[float] = None
    realized_pnl: Optional[float] = None
    total_trades: Optional[int] = None
    total_buy_volume: Optional[float] = None
    total_sell_volume: Optional[float] = None
    grid_orders: Optional[int] = None
    grid_orders_detail: Optional[list[GridOrderDetail]] = Field(
        None, description="网格订单详情列表"
    )
    signal_status: Optional[dict] = Field(None, description="策略当前信号状态")
    position_status: Optional[dict] = Field(None, description="策略当前持仓风控状态")
    risk_status: Optional[dict] = Field(None, description="策略运行期风控状态")
    health_status: Optional[dict] = Field(None, description="策略运行健康状态")
