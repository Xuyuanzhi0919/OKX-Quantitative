"""
订单模型
"""

from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, Enum
from app.core.database import Base
from sqlalchemy import func
import enum


class OrderSide(str, enum.Enum):
    """订单方向"""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, enum.Enum):
    """订单类型"""

    LIMIT = "limit"  # 限价单
    MARKET = "market"  # 市价单
    IOC = "ioc"  # 立即成交或取消 (Immediate-Or-Cancel)
    POST_ONLY = "post_only"  # 只做Maker (Post Only)
    STOP_LIMIT = "stop_limit"  # 止损限价单
    STOP_MARKET = "stop_market"  # 止损市价单


class OrderStatus(str, enum.Enum):
    """订单状态"""

    PENDING = "pending"  # 待提交
    SUBMITTED = "submitted"  # 已提交
    PARTIAL_FILLED = "partial_filled"  # 部分成交
    FILLED = "filled"  # 完全成交
    CANCELED = "canceled"  # 已撤销
    FAILED = "failed"  # 失败


class Order(Base):
    """订单表"""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, comment="用户ID")
    strategy_id = Column(
        Integer, ForeignKey("strategies.id"), comment="策略ID（手动交易可为空）"
    )

    # 订单基本信息
    order_id = Column(String(100), unique=True, index=True, comment="交易所订单ID")
    symbol = Column(String(50), nullable=False, index=True, comment="交易对")
    side = Column(
        Enum(
            OrderSide,
            name="order_side",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        comment="买卖方向",
    )
    order_type = Column(
        Enum(
            OrderType,
            name="order_type",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        comment="订单类型",
    )
    status = Column(
        Enum(
            OrderStatus,
            name="order_status",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=OrderStatus.PENDING,
        comment="订单状态",
    )

    # 价格和数量
    price = Column(Float, comment="委托价格（市价单为空）")
    amount = Column(Float, nullable=False, comment="委托数量")
    filled_amount = Column(Float, default=0.0, comment="已成交数量")
    avg_price = Column(Float, comment="成交均价")

    # 费用
    fee = Column(Float, default=0.0, comment="手续费")
    fee_currency = Column(String(10), comment="手续费币种")

    # 时间
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    submitted_at = Column(DateTime(timezone=True), comment="提交时间")
    filled_at = Column(DateTime(timezone=True), comment="完全成交时间")
    canceled_at = Column(DateTime(timezone=True), comment="撤销时间")

    # 备注
    note = Column(String(255), comment="备注")
