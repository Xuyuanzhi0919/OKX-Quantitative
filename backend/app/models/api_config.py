"""
API配置模型 - 存储用户的OKX API密钥配置
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class APIConfig(Base):
    """API配置模型"""

    __tablename__ = "api_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # API配置信息
    name = Column(
        String(100), nullable=False, comment="配置名称,如'实盘配置'/'模拟盘配置'"
    )
    exchange = Column(String(50), nullable=False, default="OKX", comment="交易所名称")
    api_key = Column(String(255), nullable=False, comment="API Key")
    secret_key = Column(Text, nullable=False, comment="Secret Key (加密存储)")
    passphrase = Column(String(255), nullable=False, comment="API Passphrase")

    # 配置属性
    is_simulated = Column(Boolean, default=False, comment="是否为模拟盘")
    is_active = Column(Boolean, default=False, comment="是否为当前激活配置")
    proxy = Column(String(255), nullable=True, comment="代理地址")

    # 状态信息
    is_valid = Column(Boolean, default=True, comment="配置是否有效")
    last_verified_at = Column(
        DateTime(timezone=True), nullable=True, comment="最后验证时间"
    )
    error_message = Column(Text, nullable=True, comment="错误信息")

    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # 关系
    user = relationship("User", back_populates="api_configs")

    def __repr__(self):
        return f"<APIConfig(id={self.id}, name='{self.name}', exchange='{self.exchange}', is_simulated={self.is_simulated}, is_active={self.is_active})>"
