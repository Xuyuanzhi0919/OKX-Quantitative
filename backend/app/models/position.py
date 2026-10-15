"""
持仓模型
"""

from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey
from app.core.database import Base
from sqlalchemy import func


class Position(Base):
    """持仓表"""

    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, comment="用户ID")
    strategy_id = Column(
        Integer, ForeignKey("strategies.id"), comment="策略ID（手动持仓可为空）"
    )

    # 持仓信息
    symbol = Column(String(50), nullable=False, index=True, comment="交易对")
    amount = Column(Float, nullable=False, comment="持仓数量")
    available_amount = Column(Float, nullable=False, comment="可用数量")
    frozen_amount = Column(Float, default=0.0, comment="冻结数量")

    # 成本信息
    avg_price = Column(Float, nullable=False, comment="持仓均价")
    total_cost = Column(Float, nullable=False, comment="总成本")

    # 盈亏信息
    unrealized_pnl = Column(Float, default=0.0, comment="未实现盈亏")
    realized_pnl = Column(Float, default=0.0, comment="已实现盈亏")

    # 时间
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), comment="建仓时间"
    )
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), comment="更新时间"
    )
