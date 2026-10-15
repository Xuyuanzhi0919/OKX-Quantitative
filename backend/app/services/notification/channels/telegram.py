"""
Telegram Bot 推送渠道
官方文档: https://core.telegram.org/bots/api
"""

from typing import Dict, Optional
import httpx
from loguru import logger
from .base import NotificationChannel


class TelegramChannel(NotificationChannel):
    """Telegram推送渠道"""

    def __init__(self, config: Dict):
        """
        初始化Telegram渠道

        配置示例:
        {
            "enabled": true,
            "bot_token": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
            "chat_id": "123456789",
            "parse_mode": "Markdown",  # 可选: HTML, Markdown, MarkdownV2
            "disable_notification": false,
            "proxy": "http://127.0.0.1:7897"  # 可选: HTTP代理
        }
        """
        super().__init__(config)
        self.bot_token = config.get("bot_token")
        self.chat_id = config.get("chat_id")
        self.parse_mode = config.get("parse_mode", "Markdown")
        self.disable_notification = config.get("disable_notification", False)
        self.proxy = config.get("proxy")
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"

        if not self.bot_token or not self.chat_id:
            logger.warning("⚠️ Telegram配置不完整,已禁用")
            self.enabled = False

    def format_message(
        self, title: str, content: str, data: Optional[Dict] = None
    ) -> str:
        """格式化为Markdown消息"""
        emoji = self.get_emoji(data.get("level", "info") if data else "info")

        # Telegram Markdown格式
        message = f"*{emoji} {title}*\n\n{content}"

        if data:
            message += "\n\n*详细信息:*"
            for key, value in data.items():
                if key not in ["level", "timestamp"]:
                    # 转义Markdown特殊字符
                    safe_value = (
                        str(value)
                        .replace("_", "\\_")
                        .replace("*", "\\*")
                        .replace("[", "\\[")
                        .replace("`", "\\`")
                    )
                    message += f"\n• `{key}`: {safe_value}"

        return message

    async def send(
        self, title: str, content: str, level: str = "info", data: Optional[Dict] = None
    ) -> bool:
        """发送Telegram消息"""
        if not self.is_enabled():
            return False

        try:
            # 格式化消息
            message = self.format_message(
                title, content, {"level": level, **(data or {})}
            )

            # 发送请求
            url = f"{self.api_base}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": self.parse_mode,
                "disable_notification": self.disable_notification,
            }

            # 配置HTTP客户端
            proxies = (
                {"http://": self.proxy, "https://": self.proxy} if self.proxy else None
            )

            async with httpx.AsyncClient(proxies=proxies, timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()

                result = response.json()
                if result.get("ok"):
                    logger.info(f"✅ Telegram推送成功: {title}")
                    return True
                else:
                    logger.error(f"❌ Telegram推送失败: {result.get('description')}")
                    return False

        except httpx.HTTPStatusError as e:
            await self.handle_error(e, f"HTTP {e.response.status_code}")
            return False
        except Exception as e:
            await self.handle_error(e, "发送消息")
            return False

    async def test_connection(self) -> bool:
        """测试Telegram连接"""
        try:
            url = f"{self.api_base}/getMe"
            proxies = (
                {"http://": self.proxy, "https://": self.proxy} if self.proxy else None
            )

            async with httpx.AsyncClient(proxies=proxies, timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                result = response.json()

                if result.get("ok"):
                    bot_info = result.get("result", {})
                    logger.info(f"✅ Telegram连接成功: @{bot_info.get('username')}")
                    return True
                return False

        except Exception as e:
            logger.error(f"❌ Telegram连接测试失败: {e}")
            return False
