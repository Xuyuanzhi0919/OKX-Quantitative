"""
WebSocket连接管理器
"""

import socketio
from loguru import logger
from typing import Dict, Set

# 创建Socket.IO服务器
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",  # 生产环境应该限制具体域名
    logger=True,  # 启用日志
    engineio_logger=True,  # 启用engineio日志
)


class WebSocketManager:
    """WebSocket连接管理器"""

    def __init__(self):
        # 存储每个房间(symbol)的订阅用户
        self.subscriptions: Dict[str, Set[str]] = {}
        # 存储用户订阅的房间
        self.user_rooms: Dict[str, Set[str]] = {}
        # 存储用户ID到sid的映射 (用于用户级别推送)
        self.user_sids: Dict[int, Set[str]] = {}

    def add_subscription(self, sid: str, symbol: str):
        """添加订阅"""
        if symbol not in self.subscriptions:
            self.subscriptions[symbol] = set()
        self.subscriptions[symbol].add(sid)

        if sid not in self.user_rooms:
            self.user_rooms[sid] = set()
        self.user_rooms[sid].add(symbol)

        logger.info(f"User {sid} subscribed to {symbol}")

    def remove_subscription(self, sid: str, symbol: str):
        """移除订阅"""
        if symbol in self.subscriptions:
            self.subscriptions[symbol].discard(sid)
            if not self.subscriptions[symbol]:
                del self.subscriptions[symbol]

        if sid in self.user_rooms:
            self.user_rooms[sid].discard(symbol)
            if not self.user_rooms[sid]:
                del self.user_rooms[sid]

        logger.info(f"User {sid} unsubscribed from {symbol}")

    def remove_user(self, sid: str):
        """移除用户所有订阅"""
        if sid in self.user_rooms:
            symbols = list(self.user_rooms[sid])
            for symbol in symbols:
                self.remove_subscription(sid, symbol)
        logger.info(f"User {sid} disconnected, all subscriptions removed")

    def get_subscribed_symbols(self) -> Set[str]:
        """获取所有被订阅的交易对"""
        return set(self.subscriptions.keys())

    def get_symbol_subscribers(self, symbol: str) -> Set[str]:
        """获取订阅某个交易对的所有用户"""
        return self.subscriptions.get(symbol, set())

    def register_user(self, sid: str, user_id: int):
        """注册用户ID和sid的映射"""
        if user_id not in self.user_sids:
            self.user_sids[user_id] = set()
        self.user_sids[user_id].add(sid)
        logger.info(f"Registered user {user_id} with sid {sid}")

    def unregister_user(self, sid: str, user_id: int = None):
        """注销用户的sid"""
        if user_id:
            if user_id in self.user_sids:
                self.user_sids[user_id].discard(sid)
                if not self.user_sids[user_id]:
                    del self.user_sids[user_id]
        else:
            # 从所有用户中移除这个sid
            for uid, sids in list(self.user_sids.items()):
                sids.discard(sid)
                if not sids:
                    del self.user_sids[uid]

    async def send_personal_message(self, user_id: int, message: dict):
        """发送消息给特定用户的所有连接"""
        if user_id in self.user_sids:
            for sid in self.user_sids[user_id]:
                try:
                    await sio.emit("message", message, to=sid)
                    logger.debug(f"Sent message to user {user_id} (sid: {sid})")
                except Exception as e:
                    logger.error(f"Failed to send message to sid {sid}: {e}")


# 全局管理器实例
ws_manager = WebSocketManager()


# Socket.IO事件处理
@sio.event
async def connect(sid, environ):
    """客户端连接"""
    logger.info(f"Client connected: {sid}")
    await sio.emit("connected", {"sid": sid}, to=sid)


@sio.event
async def disconnect(sid):
    """客户端断开"""
    logger.info(f"Client disconnected: {sid}")
    ws_manager.remove_user(sid)


@sio.event
async def subscribe(sid, data):
    """订阅行情"""
    try:
        symbol = data.get("symbol")
        if not symbol:
            await sio.emit("error", {"message": "Symbol is required"}, to=sid)
            return

        # 添加订阅
        ws_manager.add_subscription(sid, symbol)

        # 加入Socket.IO房间
        await sio.enter_room(sid, symbol)

        await sio.emit("subscribed", {"symbol": symbol}, to=sid)
        logger.info(f"Client {sid} subscribed to {symbol}")

    except Exception as e:
        logger.error(f"Subscribe error: {e}")
        await sio.emit("error", {"message": str(e)}, to=sid)


@sio.event
async def unsubscribe(sid, data):
    """取消订阅"""
    try:
        symbol = data.get("symbol")
        if not symbol:
            await sio.emit("error", {"message": "Symbol is required"}, to=sid)
            return

        # 移除订阅
        ws_manager.remove_subscription(sid, symbol)

        # 离开Socket.IO房间
        await sio.leave_room(sid, symbol)

        await sio.emit("unsubscribed", {"symbol": symbol}, to=sid)
        logger.info(f"Client {sid} unsubscribed from {symbol}")

    except Exception as e:
        logger.error(f"Unsubscribe error: {e}")
        await sio.emit("error", {"message": str(e)}, to=sid)


@sio.event
async def authenticate(sid, data):
    """用户认证,用于用户级别推送"""
    try:
        user_id = data.get("user_id")
        if not user_id:
            await sio.emit("error", {"message": "User ID is required"}, to=sid)
            return

        # 注册用户
        ws_manager.register_user(sid, user_id)

        # 加入用户专属房间
        await sio.enter_room(sid, f"user_{user_id}")

        await sio.emit("authenticated", {"user_id": user_id}, to=sid)
        logger.info(f"Client {sid} authenticated as user {user_id}")

    except Exception as e:
        logger.error(f"Authenticate error: {e}")
        await sio.emit("error", {"message": str(e)}, to=sid)


@sio.event
async def subscribe_strategies(sid):
    """订阅所有策略更新"""
    try:
        # 加入全局策略房间
        await sio.enter_room(sid, "strategies")
        await sio.emit("subscribed_strategies", {}, to=sid)
        logger.info(f"Client {sid} subscribed to all strategies")
    except Exception as e:
        logger.error(f"Subscribe strategies error: {e}")
        await sio.emit("error", {"message": str(e)}, to=sid)


@sio.event
async def unsubscribe_strategies(sid):
    """取消订阅所有策略"""
    try:
        await sio.leave_room(sid, "strategies")
        await sio.emit("unsubscribed_strategies", {}, to=sid)
        logger.info(f"Client {sid} unsubscribed from all strategies")
    except Exception as e:
        logger.error(f"Unsubscribe strategies error: {e}")
        await sio.emit("error", {"message": str(e)}, to=sid)


@sio.event
async def subscribe_strategy(sid, data):
    """订阅单个策略"""
    try:
        strategy_id = data.get("strategy_id")
        if not strategy_id:
            await sio.emit("error", {"message": "Strategy ID is required"}, to=sid)
            return

        room = f"strategy_{strategy_id}"
        await sio.enter_room(sid, room)
        await sio.emit("subscribed_strategy", {"strategy_id": strategy_id}, to=sid)
        logger.info(f"Client {sid} subscribed to strategy {strategy_id}")
    except Exception as e:
        logger.error(f"Subscribe strategy error: {e}")
        await sio.emit("error", {"message": str(e)}, to=sid)


@sio.event
async def unsubscribe_strategy(sid, data):
    """取消订阅单个策略"""
    try:
        strategy_id = data.get("strategy_id")
        if not strategy_id:
            await sio.emit("error", {"message": "Strategy ID is required"}, to=sid)
            return

        room = f"strategy_{strategy_id}"
        await sio.leave_room(sid, room)
        await sio.emit("unsubscribed_strategy", {"strategy_id": strategy_id}, to=sid)
        logger.info(f"Client {sid} unsubscribed from strategy {strategy_id}")
    except Exception as e:
        logger.error(f"Unsubscribe strategy error: {e}")
        await sio.emit("error", {"message": str(e)}, to=sid)


@sio.event
async def subscribe_risk_control(sid):
    """订阅风控预警"""
    try:
        # 加入全局风控房间
        await sio.enter_room(sid, "risk_control")
        await sio.emit("subscribed_risk_control", {}, to=sid)
        logger.info(f"Client {sid} subscribed to risk control alerts")
    except Exception as e:
        logger.error(f"Subscribe risk control error: {e}")
        await sio.emit("error", {"message": str(e)}, to=sid)


@sio.event
async def unsubscribe_risk_control(sid):
    """取消订阅风控预警"""
    try:
        await sio.leave_room(sid, "risk_control")
        await sio.emit("unsubscribed_risk_control", {}, to=sid)
        logger.info(f"Client {sid} unsubscribed from risk control alerts")
    except Exception as e:
        logger.error(f"Unsubscribe risk control error: {e}")
        await sio.emit("error", {"message": str(e)}, to=sid)


# 广播函数
async def broadcast_ticker(symbol: str, data: dict):
    """广播Ticker数据"""
    await sio.emit("ticker", data, room=symbol)


async def broadcast_orderbook(symbol: str, data: dict):
    """广播订单簿数据"""
    await sio.emit("orderbook", data, room=symbol)


async def broadcast_trades(symbol: str, data: dict):
    """广播成交记录"""
    await sio.emit("trades", data, room=symbol)


async def broadcast_kline(symbol: str, data: dict):
    """广播K线数据"""
    await sio.emit("kline", data, room=symbol)


async def broadcast_strategy_update(strategy_id: int, data: dict):
    """广播策略状态更新"""
    # 发送到 strategy_{id} 房间
    await sio.emit("strategy_update", data, room=f"strategy_{strategy_id}")
    # 同时发送到全局策略房间（用于Dashboard监听所有策略）
    await sio.emit("strategy_update", data, room="strategies")


async def broadcast_strategy_stats(strategy_id: int, data: dict):
    """广播策略统计数据"""
    await sio.emit("strategy_stats", data, room=f"strategy_{strategy_id}")
    await sio.emit("strategy_stats", data, room="strategies")


async def broadcast_notification(notification: dict):
    """
    广播系统通知

    Args:
        notification: 通知数据
            {
                "type": "success" | "warning" | "error" | "info",
                "title": "通知标题",
                "message": "通知内容",
                "strategy_id": 策略ID (可选),
                "timestamp": 时间戳
            }
    """
    # 全局广播（所有在线用户都能收到）
    await sio.emit("notification", notification)


async def broadcast_position_update(strategy_id: int, data: dict):
    """
    广播持仓更新

    Args:
        strategy_id: 策略ID
        data: 持仓数据
            {
                "strategy_id": int,
                "symbol": str,
                "position": float,
                "avg_cost": float,
                "current_price": float,
                "floating_profit": float,
                "floating_profit_rate": float,
                "timestamp": int
            }
    """
    await sio.emit("position_update", data, room=f"strategy_{strategy_id}")
    await sio.emit("position_update", data, room="strategies")


async def broadcast_order_update(strategy_id: int, data: dict):
    """
    广播订单更新

    Args:
        strategy_id: 策略ID
        data: 订单数据
            {
                "strategy_id": int,
                "order_id": str,
                "symbol": str,
                "side": "buy" | "sell",
                "type": "limit" | "market",
                "price": float,
                "amount": float,
                "filled": float,
                "status": "pending" | "filled" | "partially_filled" | "cancelled" | "failed",
                "event": "created" | "filled" | "partially_filled" | "cancelled",
                "message": str,
                "timestamp": int
            }
    """
    await sio.emit("order_update", data, room=f"strategy_{strategy_id}")
    await sio.emit("order_update", data, room="strategies")


async def broadcast_risk_alert(alert_data: dict):
    """
    广播风控预警

    Args:
        alert_data: 风控预警数据
            {
                "id": int,
                "alert_type": "risk_warning",
                "severity": "info" | "warning" | "error",
                "title": str,
                "message": str,
                "strategy_id": int (可选),
                "rule_id": int (可选),
                "metrics": dict,
                "timestamp": str
            }
    """
    # 发送到全局风控房间（所有用户）
    await sio.emit("risk_alert", alert_data, room="risk_control")

    # 如果有策略ID，也发送到策略房间
    if alert_data.get("strategy_id"):
        strategy_id = alert_data["strategy_id"]
        await sio.emit("risk_alert", alert_data, room=f"strategy_{strategy_id}")
        await sio.emit("risk_alert", alert_data, room="strategies")

    # 作为通知也广播一次
    notification = {
        "type": alert_data["severity"],
        "title": alert_data["title"],
        "message": alert_data["message"],
        "strategy_id": alert_data.get("strategy_id"),
        "timestamp": alert_data["timestamp"],
    }
    await broadcast_notification(notification)

    logger.warning(f"Risk alert broadcasted: {alert_data['title']}")


async def broadcast_risk_action(action_data: dict):
    """
    广播风控动作执行

    Args:
        action_data: 风控动作数据
            {
                "id": int,
                "action_type": "warn" | "limit" | "pause" | "close" | "resume",
                "trigger_reason": str,
                "execution_status": "success" | "failed" | "partial",
                "strategy_id": int (可选),
                "rule_id": int (可选),
                "timestamp": str
            }
    """
    # 发送到全局风控房间
    await sio.emit("risk_action", action_data, room="risk_control")

    # 如果有策略ID，也发送到策略房间
    if action_data.get("strategy_id"):
        strategy_id = action_data["strategy_id"]
        await sio.emit("risk_action", action_data, room=f"strategy_{strategy_id}")
        await sio.emit("risk_action", action_data, room="strategies")

    logger.info(f"Risk action broadcasted: {action_data['action_type']}")


async def broadcast_balance_update(data: dict):
    """
    广播账户余额更新

    Args:
        data: 余额数据
            {
                "total_equity": float,
                "available_balance": float,
                "unrealized_pnl": float,
                "margin_ratio": float,
                "details": [...],
                "timestamp": int
            }
    """
    # 全局广播账户余额
    await sio.emit("balance_update", data)
    logger.debug(f"Balance update broadcasted: total_equity={data.get('total_equity')}")


async def broadcast_positions_update(data: dict):
    """
    广播全局持仓列表更新

    Args:
        data: 持仓列表数据
            {
                "positions": [
                    {
                        "symbol": str,
                        "side": "long" | "short",
                        "size": float,
                        "avg_price": float,
                        "current_price": float,
                        "unrealized_pnl": float,
                        "unrealized_pnl_pct": float,
                        "margin": float,
                        ...
                    }
                ],
                "total_positions": int,
                "total_unrealized_pnl": float,
                "timestamp": int
            }
    """
    # 全局广播持仓列表
    await sio.emit("positions_update", data)
    logger.debug(
        f"Positions update broadcasted: {len(data.get('positions', []))} positions"
    )
