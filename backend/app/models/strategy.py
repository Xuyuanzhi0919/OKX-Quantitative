"""
策略模型
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, Text, JSON, ForeignKey, Enum
from sqlalchemy.orm import relationship
from app.core.database import Base
from sqlalchemy import func
import enum


class StrategyStatus(str, enum.Enum):
    """策略状态"""
    STOPPED = "stopped"  # 停止
    RUNNING = "running"  # 运行中
    PAUSED = "paused"  # 暂停
    ERROR = "error"  # 错误


class StrategyType(str, enum.Enum):
    """策略类型"""
    GRID = "grid"  # 网格交易
    SWING_LONG = "swing_long"  # 波段做多
    SWING_SHORT = "swing_short" # 波段做空
    AI_SWING_LONG = "ai_swing_long"  # AI增强波段做多
    MARTIN = "martin"  # 马丁格尔
    TREND = "trend"  # 趋势跟踪
    ARBITRAGE = "arbitrage"  # 套利
    ORDER_BOOK_IMBALANCE = "order_book_imbalance"  # 订单簿不平衡高频策略
    DUAL_SIDE = "dual_side"  # 双向持仓策略（多空双向）
    ADAPTIVE_GRID_TREND = "adaptive_grid_trend"  # 自适应趋势网格
    TOP_GAINERS_MOMENTUM = "top_gainers_momentum"  # 涨幅榜前三15m动量策略
    EXPLOSIVE_MOMENTUM_CHASER = "explosive_momentum_chaser"  # 爆量急拉追涨策略
    CUSTOM = "custom"  # 自定义


class Strategy(Base):
    """策略表"""

    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, comment="用户ID")
    api_config_id = Column(Integer, ForeignKey("api_configs.id", ondelete="SET NULL"), nullable=True, comment="绑定的API配置ID")
    name = Column(String(100), nullable=False, comment="策略名称")
    type = Column(Enum(StrategyType, name='strategy_type', create_type=False, values_callable=lambda x: [e.value for e in x]), nullable=False, comment="策略类型")
    status = Column(Enum(StrategyStatus, name='strategy_status', create_type=False, values_callable=lambda x: [e.value for e in x]), default=StrategyStatus.STOPPED, comment="策略状态")

    # 交易配置
    symbol = Column(String(50), nullable=False, comment="交易对，如BTC-USDT")
    timeframe = Column(String(10), comment="时间周期，如1m, 5m, 1h")

    # 策略参数（JSON格式存储，不同策略类型参数不同）
    parameters = Column(JSON, comment="策略参数")

    # 风控配置
    max_position = Column(Float, comment="最大持仓量")
    stop_loss = Column(Float, comment="止损比例")
    take_profit = Column(Float, comment="止盈比例")

    # 统计数据
    total_profit = Column(Float, default=0.0, comment="总盈亏")
    total_trades = Column(Integer, default=0, comment="总交易次数")
    win_rate = Column(Float, default=0.0, comment="胜率")

    # 持仓状态（用于重启后恢复）
    position_in_position = Column(Boolean, default=False, comment="是否有持仓")
    position_side = Column(String(10), default="", comment="持仓方向: long/short/空字符串")
    position_entry_price = Column(Float, default=0.0, comment="开仓均价")
    position_qty = Column(Float, default=0.0, comment="持仓数量")
    position_open_time = Column(Float, default=0.0, comment="开仓时间戳(unix秒)")
    position_highest_price = Column(Float, default=0.0, comment="极值价格(多仓=最高价,空仓=最低价,移动止损用)")
    position_trail_stop_px = Column(Float, default=0.0, comment="当前移动止损触发价")

    # 描述
    description = Column(Text, comment="策略描述")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), comment="更新时间")
    started_at = Column(DateTime(timezone=True), comment="启动时间")
    stopped_at = Column(DateTime(timezone=True), comment="停止时间")

    # 关联
    # user = relationship("User", back_populates="strategies")


class StrategyEvent(Base):
    """策略运行事件表，用于策略解释和复盘。"""

    __tablename__ = "strategy_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True, comment="用户ID")
    strategy_id = Column(Integer, ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False, index=True, comment="策略ID")
    event_type = Column(String(50), nullable=False, index=True, comment="事件类型")
    level = Column(String(20), nullable=False, default="info", comment="级别: info/warning/error/success")
    title = Column(String(200), nullable=False, comment="事件标题")
    message = Column(Text, comment="事件说明")
    data = Column(JSON, comment="事件结构化数据")
    parameter_snapshot = Column(JSON, comment="策略参数快照")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True, comment="创建时间")
