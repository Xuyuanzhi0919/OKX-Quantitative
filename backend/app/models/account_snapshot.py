"""
账户净值快照模型 - 用于计算最大回撤和今日盈亏
"""

from sqlalchemy import Column, Integer, Float, DateTime
from sqlalchemy import func
from app.core.database import Base


class AccountSnapshot(Base):
    """账户净值历史快照表"""

    __tablename__ = "account_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, default=1, index=True, comment="用户ID")
    total_equity = Column(Float, nullable=False, comment="账户总净值(USDT)")
    available_balance = Column(Float, default=0.0, comment="可用余额(USDT)")
    unrealized_pnl = Column(Float, default=0.0, comment="未实现盈亏(USDT)")
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        comment="快照时间",
    )
