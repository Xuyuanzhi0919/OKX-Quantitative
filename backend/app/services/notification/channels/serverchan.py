"""
Server酱推送渠道
官方文档: https://sct.ftqq.com/
"""

from typing import Dict, Optional
import httpx
from loguru import logger
from .base import NotificationChannel


class ServerChanChannel(NotificationChannel):
    """Server酱推送渠道 (Turbo版)"""

    def __init__(self, config: Dict):
        """
        初始化Server酱渠道

        配置示例:
        {
            "enabled": true,
            "sendkey": "SCTxxxxxxxxxxxxxxxxxxxxx",
            "channel": "9"  # 可选: 推送通道 (9=微信服务号)
        }

        获取SendKey: https://sct.ftqq.com/sendkey
        """
        super().__init__(config)
        self.sendkey = config.get("sendkey")
        self.channel = config.get("channel", "9")  # 默认微信服务号
        self.api_url = f"https://sctapi.ftqq.com/{self.sendkey}.send"

        if not self.sendkey:
            logger.warning("⚠️ Server酱配置不完整,已禁用")
            self.enabled = False

    def format_message(
        self, title: str, content: str, data: Optional[Dict] = None
    ) -> tuple:
        """
        格式化消息为Server酱格式

        Returns:
            (title, desp): 标题和Markdown正文
        """
        emoji = self.get_emoji(data.get("level", "info") if data else "info")
        formatted_title = f"{emoji} {title}"

        # Server酱支持Markdown格式
        desp = content

        if data:
            desp += "\n\n---\n\n**详细信息:**\n"
            for key, value in data.items():
                if key not in ["level", "timestamp"]:
                    desp += f"\n- **{key}**: `{value}`"

        return formatted_title, desp

    async def send(
        self, title: str, content: str, level: str = "info", data: Optional[Dict] = None
    ) -> bool:
        """发送Server酱消息"""
        if not self.is_enabled():
            return False

        try:
            # 格式化消息
            formatted_title, desp = self.format_message(
                title, content, {"level": level, **(data or {})}
            )

            # 发送请求
            payload = {"title": formatted_title, "desp": desp, "channel": self.channel}

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.api_url, data=payload)
                response.raise_for_status()

                result = response.json()
                if result.get("code") == 0:
                    logger.info(f"✅ Server酱推送成功: {title}")
                    return True
                else:
                    logger.error(f"❌ Server酱推送失败: {result.get('message')}")
                    return False

        except httpx.HTTPStatusError as e:
            await self.handle_error(e, f"HTTP {e.response.status_code}")
            return False
        except Exception as e:
            await self.handle_error(e, "发送消息")
            return False

    async def test_connection(self) -> bool:
        """测试Server酱连接"""
        try:
            payload = {
                "title": "OKK量化交易系统 - 推送测试",
                "desp": "✅ Server酱推送配置成功!\n\n测试时间: "
                + str(
                    httpx.AsyncClient().build_request("GET", "http://httpbin.org/get")
                ),
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.api_url, data=payload)
                response.raise_for_status()
                result = response.json()

                if result.get("code") == 0:
                    logger.info("✅ Server酱连接成功")
                    return True
                return False

        except Exception as e:
            logger.error(f"❌ Server酱连接测试失败: {e}")
            return False
