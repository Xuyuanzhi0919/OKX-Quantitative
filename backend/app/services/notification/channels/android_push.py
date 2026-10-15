"""
全能消息推送 Bark（Android APP）渠道
官方文档: https://www.ggsuper.com.cn/push/api.html
"""

import os
from typing import Dict, Optional

import httpx
from loguru import logger

from .base import NotificationChannel


class AndroidPushChannel(NotificationChannel):
    """Android 全能消息推送渠道。"""

    def __init__(self, config: Dict):
        """
        配置示例:
        {
            "enabled": true,
            "api_url": "https://www.ggsuper.com.cn/push/api/v1/sendMsg3_New.php",
            "token": "xxxxxxxxxxxxxxxx",
            "sender": "OKK",
            "url": "",
            "issecure": 0
        }
        """
        super().__init__(config)
        self.api_url = str(
            config.get("api_url")
            or "https://www.ggsuper.com.cn/push/api/v1/sendMsg3_New.php"
        )
        self.token = str(
            config.get("token") or os.getenv("ANDROID_PUSH_TOKEN") or ""
        ).strip()
        self.sender = str(config.get("sender") or "OKK")
        self.url = str(config.get("url") or "")
        self.issecure = int(config.get("issecure", 0))

        if not self.token or self.token == "YOUR_ANDROID_PUSH_TOKEN":
            logger.warning("⚠️ Android全能消息推送配置不完整,已禁用")
            self.enabled = False

    async def send(
        self, title: str, content: str, level: str = "info", data: Optional[Dict] = None
    ) -> bool:
        """发送 Android 全能消息推送。"""
        if not self.is_enabled():
            return False

        payload = {
            "title": f"{self.get_emoji(level)} {title}",
            "msg": self.format_message_body(content, data),
            "token": self.token,
            "issecure": self.issecure,
            "sender": self.sender,
        }
        if self.url:
            payload["url"] = self.url

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.api_url, json=payload)
                response.raise_for_status()
                result = response.json()

            if str(result.get("code")) == "80000000":
                logger.info(f"✅ Android全能消息推送成功: {title}")
                return True

            logger.error(f"❌ Android全能消息推送失败: {result}")
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
        """测试 Android 全能消息推送连接。"""
        return await self.send(
            "OKK量化交易系统 - 推送测试",
            "Android 全能消息推送配置成功",
            level="success",
        )
