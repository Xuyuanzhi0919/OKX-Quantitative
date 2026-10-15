"""
风控配置模型
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Float,
    Boolean,
    ForeignKey,
    Text,
)
from sqlalchemy.sql import func
from app.core.database import Base


class RiskControl(Base):
    """风控配置表"""

    __tablename__ = "risk_controls"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    strategy_id = Column(
        Integer, ForeignKey("strategies.id"), nullable=True, index=True
    )

    # 风控级别: global(全局), strategy(策略级), order(订单级)
    level = Column(String(20), nullable=False, default="strategy", index=True)

    # 风控类型: capital(资金), position(持仓), loss(亏损), drawdown(回撤), frequency(频率)
    risk_type = Column(String(50), nullable=False, index=True)

    # 风控规则名称
    name = Column(String(200), nullable=False)

    # 风控规则描述
    description = Column(Text, nullable=True)

    # 是否启用
    is_enabled = Column(Boolean, default=True, index=True)

    # === 资金风控参数 ===
    # 最小可用资金 (USDT)
    min_available_balance = Column(Float, nullable=True)
    # 最大持仓价值 (USDT)
    max_position_value = Column(Float, nullable=True)
    # 单笔交易最大金额 (USDT)
    max_order_amount = Column(Float, nullable=True)

    # === 盈亏风控参数 ===
    # 最大回撤百分比 (0.1 = 10%)
    max_drawdown_percent = Column(Float, nullable=True)
    # 日亏损限额 (USDT)
    daily_loss_limit = Column(Float, nullable=True)
    # 总亏损限额 (USDT)
    total_loss_limit = Column(Float, nullable=True)
    # 连续亏损次数限制
    max_consecutive_losses = Column(Integer, nullable=True)

    # === 持仓风控参数 ===
    # 单币种持仓上限 (个)
    max_position_per_symbol = Column(Float, nullable=True)
    # 持仓集中度上限 (0.5 = 50%)
    max_concentration_ratio = Column(Float, nullable=True)

    # === 交易频率风控参数 ===
    # 单位时间内最大交易次数
    max_trades_per_period = Column(Integer, nullable=True)
    # 时间周期 (秒)
    period_seconds = Column(Integer, nullable=True)

    # === 风控动作配置 ===
    # 触发动作: warn(警告), limit(限制), pause(暂停), close(平仓)
    action_on_trigger = Column(String(20), nullable=False, default="warn")

    # 警告阈值百分比 (达到此百分比时发出警告, 0.8 = 80%)
    warning_threshold = Column(Float, nullable=True, default=0.8)

    # 自动恢复 (风险解除后自动恢复交易)
    auto_resume = Column(Boolean, default=False)

    # === 状态跟踪 ===
    # 是否已触发
    is_triggered = Column(Boolean, default=False, index=True)
    # 触发次数
    trigger_count = Column(Integer, default=0)
    # 最后触发时间
    last_trigger_at = Column(DateTime(timezone=True), nullable=True)

    # 创建时间
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 更新时间
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self):
        return f"<RiskControl(id={self.id}, level={self.level}, type={self.risk_type}, enabled={self.is_enabled})>"


class RiskAction(Base):
    """风控动作日志表"""

    __tablename__ = "risk_actions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    strategy_id = Column(
        Integer, ForeignKey("strategies.id"), nullable=True, index=True
    )
    risk_control_id = Column(
        Integer, ForeignKey("risk_controls.id"), nullable=True, index=True
    )

    # 风控动作类型: warn, limit, pause, close, resume
    action_type = Column(String(20), nullable=False, index=True)

    # 触发原因
    trigger_reason = Column(Text, nullable=False)

    # 当前风险指标数据 (JSON格式)
    risk_metrics = Column(Text, nullable=True)

    # 执行结果: success, failed, partial
    execution_status = Column(String(20), nullable=False, default="success")

    # 执行详情
    execution_details = Column(Text, nullable=True)

    # 创建时间
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self):
        return f"<RiskAction(id={self.id}, type={self.action_type}, status={self.execution_status})>"
