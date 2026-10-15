"""
推送渠道基类
定义所有推送渠道的统一接口
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
from loguru import logger


class NotificationChannel(ABC):
    """推送渠道基类"""

    def __init__(self, config: Dict):
        """
        初始化推送渠道

        Args:
            config: 渠道配置 (API密钥、URL等)
        """
        self.config = config
        self.enabled = config.get("enabled", False)
        self.channel_name = self.__class__.__name__

    @abstractmethod
    async def send(
        self, title: str, content: str, level: str = "info", data: Optional[Dict] = None
    ) -> bool:
        """
        发送通知

        Args:
            title: 通知标题
            content: 通知内容
            level: 通知级别 (info/success/warning/error)
            data: 附加数据

        Returns:
            bool: 发送成功返回True,失败返回False
        """
        pass

    def is_enabled(self) -> bool:
        """检查渠道是否启用"""
        return self.enabled

    def format_message(
        self, title: str, content: str, data: Optional[Dict] = None
    ) -> str:
        """
        格式化消息内容(默认纯文本格式)

        子类可以覆盖此方法实现特定格式(如Markdown、HTML)
        """
        message = f"【{title}】\n\n{content}"
        if data:
            message += f"\n\n详细信息: {data}"
        return message

    def get_emoji(self, level: str) -> str:
        """根据级别获取对应emoji"""
        emoji_map = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌"}
        return emoji_map.get(level, "📢")

    async def handle_error(self, error: Exception, context: str):
        """统一错误处理"""
        logger.error(f"{self.channel_name} 推送失败 [{context}]: {error}")
