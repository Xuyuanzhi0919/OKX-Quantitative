"""
回测相关数据模型
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    DateTime,
    Text,
    JSON,
    ForeignKey,
    BigInteger,
)
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class Backtest(Base):
    """回测记录表"""

    __tablename__ = "backtests"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True, comment="用户ID")

    # 基本信息
    name = Column(String(100), nullable=False, comment="回测名称")
    description = Column(Text, comment="回测描述")
    strategy_type = Column(
        String(50), nullable=False, comment="策略类型：grid/martin/trend等"
    )
    symbol = Column(String(20), nullable=False, comment="交易对，如 BTC-USDT")
    interval = Column(
        String(10), nullable=False, comment="K线周期：1m/5m/15m/30m/1H/4H/1D"
    )

    # 回测配置
    start_time = Column(BigInteger, nullable=False, comment="回测开始时间戳(毫秒)")
    end_time = Column(BigInteger, nullable=False, comment="回测结束时间戳(毫秒)")
    initial_capital = Column(
        Numeric(20, 2), nullable=False, default=10000, comment="初始资金(USDT)"
    )
    parameters = Column(JSON, comment="策略参数")

    # 回测状态
    status = Column(
        String(20),
        nullable=False,
        default="pending",
        comment="状态：pending/running/completed/failed",
    )
    progress = Column(Integer, default=0, comment="执行进度 0-100")
    error_message = Column(Text, comment="错误信息")

    # 回测结果 - 基础指标
    final_capital = Column(Numeric(20, 2), comment="最终资金(USDT)")
    total_return = Column(Numeric(10, 4), comment="总收益率")
    annualized_return = Column(Numeric(10, 4), comment="年化收益率")
    max_drawdown = Column(Numeric(10, 4), comment="最大回撤")
    sharpe_ratio = Column(Numeric(10, 4), comment="夏普比率")

    # 回测结果 - 交易统计
    total_trades = Column(Integer, default=0, comment="总交易次数")
    winning_trades = Column(Integer, default=0, comment="盈利交易次数")
    losing_trades = Column(Integer, default=0, comment="亏损交易次数")
    win_rate = Column(Numeric(10, 4), comment="胜率")
    profit_factor = Column(Numeric(10, 4), comment="盈亏比")

    # 回测结果 - 费用统计
    total_fee = Column(Numeric(20, 8), comment="总手续费")

    # 回测结果 - 详细数据（JSON存储）
    equity_curve = Column(JSON, comment="资金曲线数据 [{timestamp, equity}, ...]")
    trade_history = Column(JSON, comment="交易历史记录")
    position_history = Column(JSON, comment="持仓历史记录")

    # 时间戳
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )
    completed_at = Column(DateTime, comment="完成时间")

    # 关联交易记录
    trades = relationship(
        "BacktestTrade", back_populates="backtest", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Backtest(id={self.id}, name={self.name}, status={self.status})>"


class BacktestTrade(Base):
    """回测交易记录表"""

    __tablename__ = "backtest_trades"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    backtest_id = Column(
        Integer,
        ForeignKey("backtests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 交易信息
    timestamp = Column(BigInteger, nullable=False, comment="交易时间戳(毫秒)")
    side = Column(String(10), nullable=False, comment="方向：buy/sell")
    price = Column(Numeric(20, 8), nullable=False, comment="成交价格")
    amount = Column(Numeric(20, 8), nullable=False, comment="成交数量")
    fee = Column(Numeric(20, 8), nullable=False, comment="手续费")

    # 持仓信息
    position_before = Column(Numeric(20, 8), comment="交易前持仓")
    position_after = Column(Numeric(20, 8), comment="交易后持仓")
    capital_before = Column(Numeric(20, 2), comment="交易前资金")
    capital_after = Column(Numeric(20, 2), comment="交易后资金")

    # 盈亏信息
    pnl = Column(Numeric(20, 8), comment="本次交易盈亏")
    pnl_percent = Column(Numeric(10, 4), comment="本次交易盈亏百分比")

    # 关联回测记录
    backtest = relationship("Backtest", back_populates="trades")

    def __repr__(self):
        return f"<BacktestTrade(id={self.id}, side={self.side}, price={self.price})>"
