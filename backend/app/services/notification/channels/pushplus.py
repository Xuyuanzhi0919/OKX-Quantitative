"""
PushPlus推送渠道
官方文档: https://www.pushplus.plus/doc/
"""

from typing import Dict, Optional
import httpx
from loguru import logger
from .base import NotificationChannel


class PushPlusChannel(NotificationChannel):
    """PushPlus推送渠道"""

    def __init__(self, config: Dict):
        """
        初始化PushPlus渠道

        配置示例:
        {
            "enabled": true,
            "token": "xxxxxxxxxxxxxxxxxxxxxx",
            "topic": "",  # 可选: 群组编号
            "template": "html"  # 可选: html, txt, json, markdown, cloudMonitor
        }

        获取Token: https://www.pushplus.plus/push1.html
        """
        super().__init__(config)
        self.token = config.get("token")
        self.topic = config.get("topic", "")
        self.template = config.get("template", "html")
        self.api_url = "http://www.pushplus.plus/send"

        if not self.token:
            logger.warning("⚠️ PushPlus配置不完整,已禁用")
            self.enabled = False

    def format_message(
        self, title: str, content: str, data: Optional[Dict] = None
    ) -> str:
        """格式化为HTML消息"""
        emoji = self.get_emoji(data.get("level", "info") if data else "info")

        # HTML格式
        html = f"""
<h2>{emoji} {title}</h2>
<p>{content}</p>
"""

        if data:
            html += "<hr/><h3>详细信息:</h3><ul>"
            for key, value in data.items():
                if key not in ["level", "timestamp"]:
                    html += f"<li><strong>{key}:</strong> {value}</li>"
            html += "</ul>"

        return html

    async def send(
        self, title: str, content: str, level: str = "info", data: Optional[Dict] = None
    ) -> bool:
        """发送PushPlus消息"""
        if not self.is_enabled():
            return False

        try:
            # 格式化消息
            formatted_content = self.format_message(
                title, content, {"level": level, **(data or {})}
            )

            # 发送请求
            payload = {
                "token": self.token,
                "title": f"{self.get_emoji(level)} {title}",
                "content": formatted_content,
                "template": self.template,
            }

            # 如果指定了群组
            if self.topic:
                payload["topic"] = self.topic

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.api_url, json=payload)
                response.raise_for_status()

                result = response.json()
                if result.get("code") == 200:
                    logger.info(f"✅ PushPlus推送成功: {title}")
                    return True
                else:
                    logger.error(f"❌ PushPlus推送失败: {result.get('msg')}")
                    return False

        except httpx.HTTPStatusError as e:
            await self.handle_error(e, f"HTTP {e.response.status_code}")
            return False
        except Exception as e:
            await self.handle_error(e, "发送消息")
            return False

    async def test_connection(self) -> bool:
        """测试PushPlus连接"""
        try:
            from datetime import datetime

            payload = {
                "token": self.token,
                "title": "✅ OKK量化交易系统 - 推送测试",
                "content": f"<h3>PushPlus推送配置成功!</h3><p>测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>",
                "template": self.template,
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.api_url, json=payload)
                response.raise_for_status()
                result = response.json()

                if result.get("code") == 200:
                    logger.info("✅ PushPlus连接成功")
                    return True
                return False

        except Exception as e:
            logger.error(f"❌ PushPlus连接测试失败: {e}")
            return False
