"""
AI配置模型
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from app.core.database import Base
from sqlalchemy import func


class AIConfig(Base):
    """AI配置表"""

    __tablename__ = "ai_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, comment="用户ID")
    name = Column(String(100), nullable=False, comment="配置名称")

    # DeepSeek配置
    provider = Column(String(50), default="deepseek", comment="AI服务提供商")
    api_key = Column(String(255), nullable=False, comment="API密钥")
    model = Column(String(100), default="deepseek-chat", comment="模型名称")

    # 配置状态
    is_active = Column(Boolean, default=False, comment="是否激活")

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), comment="更新时间"
    )
