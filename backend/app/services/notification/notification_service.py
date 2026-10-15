"""
推送通知服务
支持WebSocket、Telegram、Server酱、PushPlus、企业微信等多种推送方式
"""
from typing import Dict, List, Optional
from loguru import logger
from datetime import datetime
from decimal import Decimal
import json
from .channels import (
    AndroidPushChannel,
    BarkChannel,
    PushPlusChannel,
    ServerChanChannel,
    TelegramChannel,
    WeComChannel,
)


class NotificationType:
    """通知类型"""
    ORDER_CREATED = "order_created"      # 订单创建
    ORDER_FILLED = "order_filled"        # 订单成交
    POSITION_OPENED = "position_opened"  # 开仓
    POSITION_CLOSED = "position_closed"  # 平仓
    PROFIT_REALIZED = "profit_realized"  # 盈利实现
    STOP_LOSS = "stop_loss"             # 止损
    TAKE_PROFIT = "take_profit"         # 止盈
    RISK_WARNING = "risk_warning"       # 风险预警


class NotificationLevel:
    """通知级别"""
    INFO = "info"        # 普通信息
    SUCCESS = "success"  # 成功
    WARNING = "warning"  # 警告
    ERROR = "error"      # 错误


class NotificationService:
    """通知服务"""

    def __init__(self):
        self.websocket_manager = None  # WebSocket管理器(后续注入)
        self.channels = {}  # 推送渠道字典
        logger.info("推送通知服务初始化完成")

    def set_websocket_manager(self, manager):
        """设置WebSocket管理器"""
        self.websocket_manager = manager
        logger.info("WebSocket管理器已注入到通知服务")

    def configure_channels(self, config: Dict):
        """
        配置推送渠道

        Args:
            config: 渠道配置字典,例如:
            {
                "telegram": {
                    "enabled": true,
                    "bot_token": "xxx",
                    "chat_id": "xxx"
                },
                "serverchan": {
                    "enabled": true,
                    "sendkey": "xxx"
                }
            }
        """
        # 初始化Telegram渠道
        if "telegram" in config:
            self.channels["telegram"] = TelegramChannel(config["telegram"])
            logger.info(f"✅ Telegram渠道已配置 (启用: {self.channels['telegram'].is_enabled()})")

        # 初始化Server酱渠道
        if "serverchan" in config:
            self.channels["serverchan"] = ServerChanChannel(config["serverchan"])
            logger.info(f"✅ Server酱渠道已配置 (启用: {self.channels['serverchan'].is_enabled()})")

        # 初始化PushPlus渠道
        if "pushplus" in config:
            self.channels["pushplus"] = PushPlusChannel(config["pushplus"])
            logger.info(f"✅ PushPlus渠道已配置 (启用: {self.channels['pushplus'].is_enabled()})")

        # 初始化企业微信渠道
        if "wecom" in config:
            self.channels["wecom"] = WeComChannel(config["wecom"])
            logger.info(f"✅ 企业微信渠道已配置 (启用: {self.channels['wecom'].is_enabled()})")

        # 初始化Bark渠道
        if "bark" in config:
            self.channels["bark"] = BarkChannel(config["bark"])
            logger.info(f"✅ Bark渠道已配置 (启用: {self.channels['bark'].is_enabled()})")

        # 初始化Android全能消息推送渠道
        if "android_push" in config:
            self.channels["android_push"] = AndroidPushChannel(config["android_push"])
            logger.info(f"✅ Android全能消息推送渠道已配置 (启用: {self.channels['android_push'].is_enabled()})")

        logger.success(f"📢 推送渠道配置完成,共 {len(self.channels)} 个渠道")

    async def test_all_channels(self):
        """测试所有已配置的推送渠道"""
        results = {}
        for name, channel in self.channels.items():
            if channel.is_enabled():
                logger.info(f"测试 {name} 渠道连接...")
                results[name] = await channel.test_connection()
            else:
                results[name] = False
                logger.warning(f"{name} 渠道未启用,跳过测试")

        return results

    async def notify_order_created(
        self,
        user_id: int,
        strategy_id: int,
        strategy_name: str,
        symbol: str,
        side: str,
        order_type: str,
        price: Optional[float],
        amount: float
    ):
        """
        订单创建通知

        Args:
            user_id: 用户ID
            strategy_id: 策略ID
            strategy_name: 策略名称
            symbol: 交易对
            side: 买卖方向
            order_type: 订单类型
            price: 价格
            amount: 数量
        """
        side_text = "买入" if side == "buy" else "卖出"
        price_text = f"@ ${price}" if price else "市价"

        message = {
            "type": NotificationType.ORDER_CREATED,
            "level": NotificationLevel.INFO,
            "title": f"订单已创建",
            "message": f"{strategy_name} {side_text} {symbol} {price_text}",
            "data": {
                "strategy_id": strategy_id,
                "strategy_name": strategy_name,
                "symbol": symbol,
                "side": side,
                "order_type": order_type,
                "price": price,
                "amount": amount
            },
            "timestamp": datetime.now().isoformat()
        }

        await self._send_notification(user_id, message)
        logger.info(f"📤 订单创建通知: {side_text} {symbol} {price_text}")

    async def notify_position_opened(
        self,
        user_id: int,
        strategy_id: int,
        strategy_name: str,
        symbol: str,
        side: str,
        entry_price: float,
        amount: float,
        leverage: int,
        margin: float
    ):
        """
        开仓通知

        Args:
            user_id: 用户ID
            strategy_id: 策略ID
            strategy_name: 策略名称
            symbol: 交易对
            side: 方向
            entry_price: 开仓价
            amount: 数量
            leverage: 杠杆
            margin: 保证金
        """
        side_text = "做多" if side == "buy" or side == "long" else "做空"

        message = {
            "type": NotificationType.POSITION_OPENED,
            "level": NotificationLevel.SUCCESS,
            "title": f"🚀 开仓成功",
            "message": f"{strategy_name} {side_text} {symbol} @ ${entry_price:.6f}",
            "data": {
                "策略名称": strategy_name,
                "交易对": symbol,
                "方向": side_text,
                "开仓价": f"{entry_price:.6f}",
                "数量": f"{amount:.2f} 张",
                "杠杆": f"{leverage}x",
                "保证金": f"{margin:.2f} USDT",
                "仓位价值": f"{amount * entry_price:.2f} USDT"
            },
            "timestamp": datetime.now().isoformat()
        }

        await self._send_notification(user_id, message)
        logger.success(f"✅ 开仓通知: {side_text} {symbol} @ ${entry_price:.6f}")

    async def notify_position_closed(
        self,
        user_id: int,
        strategy_id: int,
        strategy_name: str,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        amount: float,
        pnl: float,
        pnl_pct: float,
        reason: str
    ):
        """
        平仓通知

        Args:
            user_id: 用户ID
            strategy_id: 策略ID
            strategy_name: 策略名称
            symbol: 交易对
            side: 方向
            entry_price: 开仓价
            exit_price: 平仓价
            amount: 数量
            pnl: 盈亏金额
            pnl_pct: 盈亏百分比
            reason: 平仓原因
        """
        is_profit = pnl > 0
        side_text = "做多" if side == "buy" or side == "long" else "做空"

        # 判断通知类型和级别
        if "止盈" in reason:
            notify_type = NotificationType.TAKE_PROFIT
            level = NotificationLevel.SUCCESS
            icon = "🎉"
        elif "止损" in reason:
            notify_type = NotificationType.STOP_LOSS
            level = NotificationLevel.WARNING
            icon = "⚠️"
        else:
            notify_type = NotificationType.POSITION_CLOSED
            level = NotificationLevel.SUCCESS if is_profit else NotificationLevel.WARNING
            icon = "💰" if is_profit else "📉"

        pnl_text = f"+{abs(pnl):.2f}" if is_profit else f"-{abs(pnl):.2f}"
        pnl_pct_text = f"+{pnl_pct:.2f}%" if is_profit else f"{pnl_pct:.2f}%"

        message = {
            "type": notify_type,
            "level": level,
            "title": f"{icon} {reason}",
            "message": f"{strategy_name} {side_text} {symbol} {pnl_text} ({pnl_pct_text})",
            "data": {
                "策略名称": strategy_name,
                "交易对": symbol,
                "方向": side_text,
                "开仓价": f"{entry_price:.6f}",
                "平仓价": f"{exit_price:.6f}",
                "数量": f"{amount:.2f} 张",
                "盈亏金额": f"{pnl_text} USDT",
                "盈亏比例": pnl_pct_text,
                "平仓原因": reason
            },
            "timestamp": datetime.now().isoformat()
        }

        await self._send_notification(user_id, message)

        log_msg = f"{icon} 平仓通知: {side_text} {symbol} @ ${exit_price:.6f}, 盈亏: {pnl_text} ({pnl_pct_text})"
        if is_profit:
            logger.success(log_msg)
        else:
            logger.warning(log_msg)

    async def notify_profit_realized(
        self,
        user_id: int,
        strategy_id: int,
        strategy_name: str,
        total_profit: float,
        total_trades: int,
        win_rate: float
    ):
        """
        盈利实现通知

        Args:
            user_id: 用户ID
            strategy_id: 策略ID
            strategy_name: 策略名称
            total_profit: 总盈利
            total_trades: 总交易次数
            win_rate: 胜率
        """
        is_profit = total_profit > 0
        profit_text = f"+{abs(total_profit):.2f}" if is_profit else f"-{abs(total_profit):.2f}"

        message = {
            "type": NotificationType.PROFIT_REALIZED,
            "level": NotificationLevel.SUCCESS if is_profit else NotificationLevel.WARNING,
            "title": f"💰 累计盈利统计",
            "message": f"{strategy_name} 累计 {profit_text} | 胜率 {win_rate:.1f}%",
            "data": {
                "策略名称": strategy_name,
                "累计盈利": f"{profit_text} USDT",
                "总交易次数": f"{total_trades} 笔",
                "胜率": f"{win_rate:.1f}%"
            },
            "timestamp": datetime.now().isoformat()
        }

        await self._send_notification(user_id, message)
        logger.info(f"💰 盈利统计通知: {profit_text}, 胜率 {win_rate:.1f}%")

    async def notify_risk_warning(
        self,
        user_id: int,
        strategy_id: int,
        strategy_name: str,
        symbol: str,
        warning_type: str,
        message_text: str,
        data: Optional[Dict] = None
    ):
        """
        风险预警通知

        Args:
            user_id: 用户ID
            strategy_id: 策略ID
            strategy_name: 策略名称
            symbol: 交易对
            warning_type: 预警类型
            message_text: 预警消息
            data: 额外数据
        """
        # 转换额外数据为中文
        chinese_data = {
            "策略名称": strategy_name,
            "交易对": symbol,
            "预警类型": warning_type,
            "预警消息": message_text
        }

        # 添加额外数据(转换常见英文key为中文)
        if data:
            key_mapping = {
                "stop_loss_count": "止损次数",
                "max_stop_loss_count": "最大止损次数",
                "test_key": "测试键"
            }
            for key, value in data.items():
                chinese_key = key_mapping.get(key, key)
                chinese_data[chinese_key] = value

        message = {
            "type": NotificationType.RISK_WARNING,
            "level": NotificationLevel.ERROR,
            "title": f"⚠️ 风险预警",
            "message": f"{strategy_name} {symbol}: {message_text}",
            "data": chinese_data,
            "timestamp": datetime.now().isoformat()
        }

        await self._send_notification(user_id, message)
        logger.error(f"⚠️ 风险预警: {strategy_name} - {message_text}")

    async def send_strategy_notification(
        self,
        strategy_id: int,
        title: str,
        message: str,
        level: str = "info",
        data: Optional[Dict] = None
    ):
        """
        策略通知（开仓、平仓、止损等）

        Args:
            strategy_id: 策略ID
            title: 通知标题
            message: 通知内容
            level: 通知级别 info/success/warning/error
            data: 额外数据
        """
        msg = {
            "type": "strategy_notification",
            "level": level,
            "title": title,
            "message": message,
            "data": data or {},
            "timestamp": datetime.now().isoformat()
        }
        # 通知广播给所有用户（策略通知不区分user_id，user_id=1兜底）
        await self._send_notification(user_id=1, message=msg)

    async def send_bark_notification(
        self,
        title: str,
        message: str,
        level: str = "info",
        data: Optional[Dict] = None
    ) -> bool:
        """只通过 Bark 发送通知。"""
        bark = self.channels.get("bark")
        if not bark or not bark.is_enabled():
            logger.warning("Bark渠道未启用，跳过Bark推送")
            return False

        try:
            return await bark.send(title, message, level, data or {})
        except Exception as e:
            logger.error(f"Bark推送异常: {e}")
            return False

    async def send_bark_alert(
        self,
        title: str,
        message: str,
        level: str = "info",
        data: Optional[Dict] = None,
        category: str = "OKK",
        strategy_id: Optional[int] = None,
    ) -> bool:
        """
        Bark 全能告警入口。

        用于策略信号、开仓、平仓、熔断、系统异常等需要直接推到手机的事件。
        这个方法只走 Bark，不会额外打扰 Telegram / PushPlus 等其它渠道。
        """
        payload = {
            "分类": category,
            "时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if strategy_id is not None:
            payload["策略ID"] = strategy_id
        if data:
            payload.update(data)
        return await self.send_bark_notification(title, message, level, payload)

    async def send_android_push_notification(
        self,
        title: str,
        message: str,
        level: str = "info",
        data: Optional[Dict] = None
    ) -> bool:
        """只通过 Android 全能消息推送发送通知。"""
        android_push = self.channels.get("android_push")
        if not android_push or not android_push.is_enabled():
            logger.warning("Android全能消息推送渠道未启用，跳过推送")
            return False

        try:
            return await android_push.send(title, message, level, data or {})
        except Exception as e:
            logger.error(f"Android全能消息推送异常: {e}")
            return False

    async def send_android_push_alert(
        self,
        title: str,
        message: str,
        level: str = "info",
        data: Optional[Dict] = None,
        category: str = "OKK",
        strategy_id: Optional[int] = None,
    ) -> bool:
        """
        Android 全能消息推送告警入口。

        用于策略信号、开仓、平仓、熔断、系统异常等需要直接推到 Android 手机的事件。
        不做应用层节流：只要调用就尝试发送，平台限频错误会记录到日志。
        """
        payload = {
            "分类": category,
            "时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if strategy_id is not None:
            payload["策略ID"] = strategy_id
        if data:
            payload.update(data)
        return await self.send_android_push_notification(title, message, level, payload)

    async def _send_notification(self, user_id: int, message: Dict):
        """
        发送通知到各个渠道

        Args:
            user_id: 用户ID
            message: 通知消息
        """
        title = message.get("title", "通知")
        content = message.get("message", "")
        level = message.get("level", "info")
        data = message.get("data", {})

        # 1. WebSocket推送 (实时推送,前端在线时接收)
        if self.websocket_manager:
            try:
                await self.websocket_manager.send_personal_message(
                    user_id=user_id,
                    message={
                        "event": "notification",
                        "data": message
                    }
                )
                logger.debug(f"WebSocket推送成功: user={user_id}, type={message['type']}")
            except Exception as e:
                logger.error(f"WebSocket推送失败: {e}")

        # 2. 第三方推送渠道 (离线也能收到)
        for channel_name, channel in self.channels.items():
            if channel.is_enabled():
                try:
                    await channel.send(title, content, level, data)
                except Exception as e:
                    logger.error(f"{channel_name} 推送异常: {e}")


# 全局通知服务实例
notification_service = NotificationService()
