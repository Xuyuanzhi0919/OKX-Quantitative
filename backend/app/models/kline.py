"""
K线数据模型 - 用于存储历史K线数据和回测
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    BigInteger,
    Index,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from app.core.database import Base


class Kline(Base):
    """K线数据表 - 时序数据"""

    __tablename__ = "klines"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # 交易对和周期
    symbol = Column(
        String(20), nullable=False, index=True, comment="交易对，如 BTC-USDT"
    )
    interval = Column(
        String(10),
        nullable=False,
        index=True,
        comment="K线周期：1m/5m/15m/30m/1H/4H/1D",
    )

    # K线数据
    timestamp = Column(
        BigInteger, nullable=False, index=True, comment="K线开始时间戳(毫秒)"
    )
    open = Column(Numeric(20, 8), nullable=False, comment="开盘价")
    high = Column(Numeric(20, 8), nullable=False, comment="最高价")
    low = Column(Numeric(20, 8), nullable=False, comment="最低价")
    close = Column(Numeric(20, 8), nullable=False, comment="收盘价")
    volume = Column(Numeric(30, 8), nullable=False, comment="成交量(币)")
    volume_currency = Column(Numeric(30, 8), nullable=False, comment="成交额(USDT)")

    # 额外信息
    confirm = Column(Integer, default=1, comment="是否确认：0=未确认,1=已确认")

    # 联合唯一索引：同一交易对、周期、时间戳只能有一条记录
    __table_args__ = (
        UniqueConstraint(
            "symbol", "interval", "timestamp", name="uix_symbol_interval_timestamp"
        ),
        Index("idx_symbol_interval_timestamp", "symbol", "interval", "timestamp"),
        {"comment": "K线数据表 - 用于回测和历史数据分析"},
    )

    def __repr__(self):
        return f"<Kline(symbol={self.symbol}, interval={self.interval}, timestamp={self.timestamp})>"
