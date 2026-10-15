"""
企业微信机器人推送渠道
官方文档: https://developer.work.weixin.qq.com/document/path/91770
"""

from typing import Dict, Optional
import httpx
from loguru import logger
from .base import NotificationChannel


class WeComChannel(NotificationChannel):
    """企业微信机器人推送渠道"""

    def __init__(self, config: Dict):
        """
        初始化企业微信渠道

        配置示例:
        {
            "enabled": true,
            "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxx",
            "mentioned_list": [],  # 可选: @指定成员 ["user1", "user2"]
            "mentioned_mobile_list": []  # 可选: @指定手机号 ["13800000000"]
        }

        获取Webhook: 企业微信 -> 群聊 -> 添加群机器人
        """
        super().__init__(config)
        self.webhook_url = config.get("webhook_url")
        self.mentioned_list = config.get("mentioned_list", [])
        self.mentioned_mobile_list = config.get("mentioned_mobile_list", [])

        if not self.webhook_url:
            logger.warning("⚠️ 企业微信配置不完整,已禁用")
            self.enabled = False

    def format_message(
        self, title: str, content: str, data: Optional[Dict] = None
    ) -> str:
        """格式化为Markdown消息"""
        emoji = self.get_emoji(data.get("level", "info") if data else "info")

        # 企业微信Markdown格式
        message = f"# {emoji} {title}\n\n{content}\n"

        if data:
            message += "\n---\n\n**详细信息:**\n"
            for key, value in data.items():
                if key not in ["level", "timestamp"]:
                    message += f'\n- <font color="comment">{key}:</font> `{value}`'

        return message

    async def send(
        self, title: str, content: str, level: str = "info", data: Optional[Dict] = None
    ) -> bool:
        """发送企业微信消息"""
        if not self.is_enabled():
            return False

        try:
            # 格式化消息
            formatted_content = self.format_message(
                title, content, {"level": level, **(data or {})}
            )

            # 构建请求体
            payload = {
                "msgtype": "markdown",
                "markdown": {"content": formatted_content},
            }

            # 添加@功能
            if self.mentioned_list or self.mentioned_mobile_list:
                payload["markdown"]["mentioned_list"] = self.mentioned_list
                payload["markdown"][
                    "mentioned_mobile_list"
                ] = self.mentioned_mobile_list

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.webhook_url, json=payload)
                response.raise_for_status()

                result = response.json()
                if result.get("errcode") == 0:
                    logger.info(f"✅ 企业微信推送成功: {title}")
                    return True
                else:
                    logger.error(f"❌ 企业微信推送失败: {result.get('errmsg')}")
                    return False

        except httpx.HTTPStatusError as e:
            await self.handle_error(e, f"HTTP {e.response.status_code}")
            return False
        except Exception as e:
            await self.handle_error(e, "发送消息")
            return False

    async def test_connection(self) -> bool:
        """测试企业微信连接"""
        try:
            from datetime import datetime

            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "content": f"# ✅ OKK量化交易系统 - 推送测试\n\n企业微信推送配置成功!\n\n测试时间: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
                },
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.webhook_url, json=payload)
                response.raise_for_status()
                result = response.json()

                if result.get("errcode") == 0:
                    logger.info("✅ 企业微信连接成功")
                    return True
                return False

        except Exception as e:
            logger.error(f"❌ 企业微信连接测试失败: {e}")
            return False
