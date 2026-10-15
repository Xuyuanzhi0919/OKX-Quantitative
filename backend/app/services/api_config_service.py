"""
API配置服务 - 动态获取当前激活的API配置
"""
from typing import Optional
import socket
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.api_config import APIConfig
from app.services.exchange.okx import OKXExchange
from app.core.config import settings
from loguru import logger


class APIConfigService:
    """API配置服务"""

    @staticmethod
    def _resolve_proxy(config_proxy: Optional[str] = None) -> Optional[str]:
        """优先使用账户配置代理，其次使用 .env，最后探测常见本地代理端口。"""
        if config_proxy and config_proxy.strip():
            return config_proxy.strip()
        if settings.OKX_PROXY and settings.OKX_PROXY.strip():
            return settings.OKX_PROXY.strip()

        for port in (7897, 7890, 7891):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    return f"http://127.0.0.1:{port}"
            except OSError:
                continue
        return None

    @staticmethod
    def get_active_config(user_id: int = 1, db: Optional[Session] = None) -> Optional[APIConfig]:
        """
        获取用户当前激活的API配置

        Args:
            user_id: 用户ID
            db: 数据库会话,如果为None则创建新会话

        Returns:
            APIConfig对象或None
        """
        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            config = db.query(APIConfig).filter(
                APIConfig.user_id == user_id,
                APIConfig.is_active == True
            ).first()

            return config
        finally:
            if should_close:
                db.close()

    @staticmethod
    def get_config(
        user_id: int = 1,
        config_id: Optional[int] = None,
        db: Optional[Session] = None
    ) -> Optional[APIConfig]:
        """
        获取指定API配置；config_id为空时回退到当前激活配置。
        """
        if config_id is None:
            return APIConfigService.get_active_config(user_id=user_id, db=db)

        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            return db.query(APIConfig).filter(
                APIConfig.user_id == user_id,
                APIConfig.id == config_id
            ).first()
        finally:
            if should_close:
                db.close()

    @staticmethod
    def get_exchange(user_id: int = 1, config_id: Optional[int] = None) -> OKXExchange:
        """
        获取OKX交易所实例 (优先使用数据库配置,否则使用.env配置)

        Args:
            user_id: 用户ID

        Returns:
            OKXExchange实例
        """
        # 尝试从数据库获取绑定配置；未绑定则使用激活配置
        config = APIConfigService.get_config(user_id=user_id, config_id=config_id)

        if config_id is not None and not config:
            raise Exception(f"API配置不存在或不属于用户: {config_id}")

        if config_id is not None and config and not config.is_valid:
            raise Exception(f"API配置无效: {config.name} - {config.error_message or '请先验证配置'}")

        if config and config.is_valid:
            logger.info(f"使用数据库API配置: {config.name} ({'模拟盘' if config.is_simulated else '实盘'})")
            return OKXExchange(
                api_key=config.api_key,
                secret_key=config.secret_key,
                passphrase=config.passphrase,
                simulated=config.is_simulated,
                proxy=APIConfigService._resolve_proxy(config.proxy)
            )
        else:
            # 回退到.env配置
            logger.info("使用.env文件API配置")
            if not settings.OKX_API_KEY or not settings.OKX_SECRET_KEY or not settings.OKX_PASSPHRASE:
                raise Exception("未找到有效的API配置,请在数据库或.env文件中配置")

            return OKXExchange(
                api_key=settings.OKX_API_KEY,
                secret_key=settings.OKX_SECRET_KEY,
                passphrase=settings.OKX_PASSPHRASE,
                simulated=settings.OKX_SIMULATED,
                proxy=APIConfigService._resolve_proxy()
            )


# 全局实例
api_config_service = APIConfigService()
