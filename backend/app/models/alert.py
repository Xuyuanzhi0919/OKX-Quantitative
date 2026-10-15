"""
告警记录模型
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    Float,
    Boolean,
    ForeignKey,
)
from sqlalchemy.sql import func
from app.core.database import Base


class Alert(Base):
    """告警记录表"""

    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    strategy_id = Column(
        Integer, ForeignKey("strategies.id"), nullable=True, index=True
    )

    # 告警类型: stop_loss(止损), take_profit(止盈), risk_warning(风险警告), system_error(系统错误)
    alert_type = Column(String(50), nullable=False, index=True)

    # 告警级别: info, warning, error, success
    severity = Column(String(20), nullable=False, default="info")

    # 告警标题
    title = Column(String(200), nullable=False)

    # 告警消息
    message = Column(Text, nullable=False)

    # 告警数据 (JSON格式,存储相关指标)
    data = Column(Text, nullable=True)

    # 是否已读
    is_read = Column(Boolean, default=False, index=True)

    # 是否已处理
    is_handled = Column(Boolean, default=False)

    # 创建时间
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 处理时间
    handled_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<Alert(id={self.id}, type={self.alert_type}, severity={self.severity}, title={self.title})>"
