"""
Bark 推送渠道
官方服务: https://api.day.app
"""

from typing import Dict, Optional

import httpx
from loguru import logger

from .base import NotificationChannel


class BarkChannel(NotificationChannel):
    """Bark iOS 推送渠道。"""

    def __init__(self, config: Dict):
        """
        配置示例:
        {
            "enabled": true,
            "server_url": "https://api.day.app",
            "device_key": "xxxxxxxxxxxxxxxx",
            "group": "OKK",
            "sound": "alarm",
            "level": "active"
        }
        """
        super().__init__(config)
        self.server_url = str(config.get("server_url") or "https://api.day.app").rstrip(
            "/"
        )
        self.device_key = str(config.get("device_key") or "").strip().strip("/")
        self.group = config.get("group", "OKK")
        self.sound = config.get("sound")
        self.level = config.get("level", "active")
        self.icon = config.get("icon")
        self.url = config.get("url")

        if not self.device_key or self.device_key == "YOUR_BARK_DEVICE_KEY":
            logger.warning("⚠️ Bark配置不完整,已禁用")
            self.enabled = False

    async def send(
        self, title: str, content: str, level: str = "info", data: Optional[Dict] = None
    ) -> bool:
        """发送 Bark 消息。"""
        if not self.is_enabled():
            return False

        payload = {
            "title": f"{self.get_emoji(level)} {title}",
            "body": self.format_message_body(content, data),
            "group": self.group,
            "level": self.level,
        }
        if self.sound:
            payload["sound"] = self.sound
        if self.icon:
            payload["icon"] = self.icon
        if self.url:
            payload["url"] = self.url

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.server_url}/{self.device_key}", json=payload
                )
                response.raise_for_status()
                result = response.json()

            if result.get("code") == 200:
                logger.info(f"✅ Bark推送成功: {title}")
                return True

            logger.error(f"❌ Bark推送失败: {result}")
            return False
        except httpx.HTTPStatusError as exc:
            await self.handle_error(exc, f"HTTP {exc.response.status_code}")
            return False
        except Exception as exc:
            await self.handle_error(exc, "发送消息")
            return False

    def format_message_body(self, content: str, data: Optional[Dict] = None) -> str:
        message = content
        if data:
            lines = []
            for key, value in data.items():
                if key not in {"level", "timestamp"}:
                    lines.append(f"{key}: {value}")
            if lines:
                message += "\n\n" + "\n".join(lines)
        return message

    async def test_connection(self) -> bool:
        """测试 Bark 连接。"""
        return await self.send(
            "OKK量化交易系统 - 推送测试",
            "Bark 推送配置成功",
            level="success",
        )
