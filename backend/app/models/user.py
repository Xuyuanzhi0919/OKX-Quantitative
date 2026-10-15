"""
用户模型
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, func
from sqlalchemy.orm import relationship
from app.core.database import Base


class User(Base):
    """用户表"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(
        String(50), unique=True, index=True, nullable=False, comment="用户名"
    )
    email = Column(String(100), unique=True, index=True, comment="邮箱")
    hashed_password = Column(String(255), nullable=False, comment="密码哈希")
    is_active = Column(Boolean, default=True, comment="是否激活")
    is_superuser = Column(Boolean, default=False, comment="是否超级用户")

    # OKX API凭证（加密存储）- 已废弃,使用api_configs关系
    okx_api_key = Column(String(255), comment="OKX API Key")
    okx_secret_key = Column(String(255), comment="OKX Secret Key（加密）")
    okx_passphrase = Column(String(255), comment="OKX Passphrase（加密）")

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), comment="更新时间"
    )

    # 关系
    api_configs = relationship(
        "APIConfig", back_populates="user", cascade="all, delete-orphan"
    )
