"""
OKX WebSocket客户端
"""

import asyncio
import json
import websockets
import hmac
import hashlib
import base64
import time
from datetime import datetime, timezone
from loguru import logger
from typing import Dict, Callable, Set, Optional
from .manager import (
    broadcast_ticker,
    broadcast_orderbook,
    broadcast_trades,
    broadcast_kline,
    ws_manager,
)


class OKXWebSocketClient:
    """OKX WebSocket客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        passphrase: Optional[str] = None,
        simulated: bool = False,
    ):
        """
        初始化OKX WebSocket客户端

        Args:
            api_key: API Key (Private WebSocket需要)
            secret_key: Secret Key (Private WebSocket需要)
            passphrase: API Passphrase (Private WebSocket需要)
            simulated: 是否使用模拟盘
        """
        # API凭证
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.simulated = simulated

        # WebSocket URLs
        if simulated:
            self.public_url = "wss://wspap.okx.com:8443/ws/v5/public"
            self.business_url = "wss://wspap.okx.com:8443/ws/v5/business"
            self.private_url = "wss://wspap.okx.com:8443/ws/v5/private"
        else:
            self.public_url = "wss://ws.okx.com:8443/ws/v5/public"
            self.business_url = "wss://ws.okx.com:8443/ws/v5/business"
            self.private_url = "wss://ws.okx.com:8443/ws/v5/private"

        # WebSocket连接
        self.ws_public = None  # public WebSocket连接
        self.ws_business = None  # business WebSocket连接
        self.ws_private = None  # private WebSocket连接

        self.subscribed_channels: Set[str] = set()
        self.running = False
        self.reconnect_delay = 5  # 重连延迟(秒)
        self.private_authenticated = False  # Private WebSocket登录状态

    def _generate_signature(self, timestamp: str) -> str:
        """
        生成OKX WebSocket登录签名

        签名算法: timestamp + 'GET' + '/users/self/verify'

        Args:
            timestamp: ISO格式时间戳

        Returns:
            Base64编码的签名字符串
        """
        message = timestamp + "GET" + "/users/self/verify"
        mac = hmac.new(
            bytes(self.secret_key, encoding="utf-8"),
            bytes(message, encoding="utf-8"),
            digestmod=hashlib.sha256,
        )
        signature = base64.b64encode(mac.digest()).decode("utf-8")
        return signature

    async def _login_private(self):
        """登录Private WebSocket"""
        try:
            # 生成时间戳 (Unix时间戳,秒)
            timestamp = str(int(time.time()))

            # 生成签名
            signature = self._generate_signature(timestamp)

            # 构造登录消息
            login_msg = {
                "op": "login",
                "args": [
                    {
                        "apiKey": self.api_key,
                        "passphrase": self.passphrase,
                        "timestamp": timestamp,
                        "sign": signature,
                    }
                ],
            }

            # 发送登录请求
            await self.ws_private.send(json.dumps(login_msg))
            logger.info("Sent login request to OKX Private WebSocket")

            # 等待登录响应
            response = await self.ws_private.recv()
            data = json.loads(response)

            if data.get("event") == "login" and data.get("code") == "0":
                self.private_authenticated = True
                logger.info("Successfully authenticated to OKX Private WebSocket")
            else:
                logger.error(f"Failed to authenticate to OKX Private WebSocket: {data}")

        except Exception as e:
            logger.error(f"Error logging into Private WebSocket: {e}")

    async def connect(self):
        """连接到OKX WebSocket（public和business端点）"""
        try:
            # 连接public端点（ticker, orderbook, trades）
            logger.info(f"Connecting to OKX Public WebSocket: {self.public_url}")
            self.ws_public = await websockets.connect(
                self.public_url, ping_interval=20, ping_timeout=10
            )
            logger.info("Connected to OKX Public WebSocket")

            # 连接business端点（K线数据）
            logger.info(f"Connecting to OKX Business WebSocket: {self.business_url}")
            self.ws_business = await websockets.connect(
                self.business_url, ping_interval=20, ping_timeout=10
            )
            logger.info("Connected to OKX Business WebSocket")

            # 连接private端点（订单更新）- 仅在提供了API凭证时连接
            if self.api_key and self.secret_key and self.passphrase:
                logger.info(f"Connecting to OKX Private WebSocket: {self.private_url}")
                self.ws_private = await websockets.connect(
                    self.private_url, ping_interval=20, ping_timeout=10
                )
                logger.info("Connected to OKX Private WebSocket")

                # 登录认证
                await self._login_private()

            self.running = True
            return True
        except Exception as e:
            logger.error(f"Failed to connect to OKX WebSocket: {e}")
            return False

    async def disconnect(self):
        """断开连接"""
        self.running = False
        if self.ws_public:
            await self.ws_public.close()
            logger.info("Disconnected from OKX Public WebSocket")
        if self.ws_business:
            await self.ws_business.close()
            logger.info("Disconnected from OKX Business WebSocket")
        if self.ws_private:
            await self.ws_private.close()
            logger.info("Disconnected from OKX Private WebSocket")
            self.private_authenticated = False

    async def subscribe_ticker(self, symbol: str):
        """订阅Ticker（使用public连接）"""
        channel = f"tickers:{symbol}"
        if channel in self.subscribed_channels:
            return

        try:
            subscribe_msg = {
                "op": "subscribe",
                "args": [{"channel": "tickers", "instId": symbol}],
            }
            await self.ws_public.send(json.dumps(subscribe_msg))
            self.subscribed_channels.add(channel)
            logger.info(f"Subscribed to ticker: {symbol}")
        except Exception as e:
            logger.error(f"Failed to subscribe ticker {symbol}: {e}")

    async def subscribe_orderbook(self, symbol: str, depth: str = "books5"):
        """订阅订单簿（使用public连接）"""
        channel = f"{depth}:{symbol}"
        if channel in self.subscribed_channels:
            return

        try:
            subscribe_msg = {
                "op": "subscribe",
                "args": [{"channel": depth, "instId": symbol}],
            }
            await self.ws_public.send(json.dumps(subscribe_msg))
            self.subscribed_channels.add(channel)
            logger.info(f"Subscribed to orderbook: {symbol}")
        except Exception as e:
            logger.error(f"Failed to subscribe orderbook {symbol}: {e}")

    async def subscribe_trades(self, symbol: str):
        """订阅成交记录（使用public连接）"""
        channel = f"trades:{symbol}"
        if channel in self.subscribed_channels:
            return

        try:
            subscribe_msg = {
                "op": "subscribe",
                "args": [{"channel": "trades", "instId": symbol}],
            }
            await self.ws_public.send(json.dumps(subscribe_msg))
            self.subscribed_channels.add(channel)
            logger.info(f"Subscribed to trades: {symbol}")
        except Exception as e:
            logger.error(f"Failed to subscribe trades {symbol}: {e}")

    async def subscribe_kline(self, symbol: str, bar: str = "1m"):
        """
        订阅K线数据（使用business连接）

        Args:
            symbol: 交易对，如 BTC-USDT
            bar: K线周期，支持 1m/3m/5m/15m/30m/1H/2H/4H/6H/12H/1D/1W/1M
        """
        channel = f"candle{bar}:{symbol}"
        if channel in self.subscribed_channels:
            return

        try:
            # OKX K线频道在 business WebSocket，格式: "candle" + bar
            # 例如: candle1m, candle1H, candle1D
            subscribe_msg = {
                "op": "subscribe",
                "args": [{"channel": f"candle{bar}", "instId": symbol}],
            }
            await self.ws_business.send(json.dumps(subscribe_msg))
            self.subscribed_channels.add(channel)
            logger.info(f"Subscribed to kline {bar}: {symbol} on business WebSocket")
        except Exception as e:
            logger.error(f"Failed to subscribe kline {symbol}: {e}")

    async def subscribe_orders(self, inst_type: str = "SPOT"):
        """
        订阅订单更新频道 (使用private连接)

        Args:
            inst_type: 产品类型 SPOT/SWAP/FUTURES/OPTION
        """
        if not self.private_authenticated:
            logger.warning(
                "Private WebSocket not authenticated, cannot subscribe to orders"
            )
            return

        channel = f"orders:{inst_type}"
        if channel in self.subscribed_channels:
            return

        try:
            subscribe_msg = {
                "op": "subscribe",
                "args": [{"channel": "orders", "instType": inst_type}],
            }
            await self.ws_private.send(json.dumps(subscribe_msg))
            self.subscribed_channels.add(channel)
            logger.info(f"Subscribed to orders channel: {inst_type}")
        except Exception as e:
            logger.error(f"Failed to subscribe orders {inst_type}: {e}")

    async def unsubscribe(self, channel: str, symbol: str):
        """取消订阅"""
        channel_key = f"{channel}:{symbol}"
        if channel_key not in self.subscribed_channels:
            return

        try:
            unsubscribe_msg = {
                "op": "unsubscribe",
                "args": [{"channel": channel, "instId": symbol}],
            }
            await self.ws.send(json.dumps(unsubscribe_msg))
            self.subscribed_channels.discard(channel_key)
            logger.info(f"Unsubscribed from {channel}: {symbol}")
        except Exception as e:
            logger.error(f"Failed to unsubscribe {channel} {symbol}: {e}")

    async def handle_message(self, message: dict):
        """处理接收到的消息"""
        try:
            # 处理订阅响应
            if "event" in message:
                if message["event"] == "subscribe":
                    logger.info(f"Subscription confirmed: {message}")
                elif message["event"] == "error":
                    logger.error(f"Subscription error: {message}")
                return

            # 处理数据推送
            if "data" in message and "arg" in message:
                arg = message["arg"]
                channel = arg.get("channel")
                inst_id = arg.get("instId")
                data = message["data"]

                if not data:
                    return

                # 根据channel类型分发数据
                if channel == "tickers":
                    await self.handle_ticker(inst_id, data[0])
                elif channel in ["books5", "books", "books50-l2-tbt"]:
                    await self.handle_orderbook(inst_id, data[0])
                elif channel == "trades":
                    await self.handle_trades(inst_id, data)
                elif channel.startswith("candle"):
                    # 提取K线周期，如 candle1m -> 1m
                    bar = channel.replace("candle", "")
                    await self.handle_kline(inst_id, bar, data[0])
                elif channel == "orders":
                    # 处理订单更新，data可能包含多个订单
                    for order in data:
                        await self.handle_order(order)

        except Exception as e:
            logger.error(f"Error handling message: {e}")

    async def handle_ticker(self, symbol: str, data: dict):
        """处理Ticker数据"""
        try:
            ticker_data = {
                "symbol": symbol,
                "last": float(data["last"]),
                "lastSz": float(data["lastSz"]),
                "askPx": float(data["askPx"]) if data["askPx"] else 0,
                "askSz": float(data["askSz"]) if data["askSz"] else 0,
                "bidPx": float(data["bidPx"]) if data["bidPx"] else 0,
                "bidSz": float(data["bidSz"]) if data["bidSz"] else 0,
                "open24h": float(data["open24h"]),
                "high24h": float(data["high24h"]),
                "low24h": float(data["low24h"]),
                "vol24h": float(data["vol24h"]) if data["vol24h"] else 0,
                "volCcy24h": float(data["volCcy24h"]) if data["volCcy24h"] else 0,
                "ts": int(data["ts"]),
            }
            await broadcast_ticker(symbol, ticker_data)
        except Exception as e:
            logger.error(f"Error handling ticker: {e}")

    async def handle_orderbook(self, symbol: str, data: dict):
        """处理订单簿数据"""
        try:
            orderbook_data = {
                "symbol": symbol,
                "asks": [
                    [float(ask[0]), float(ask[1])] for ask in data.get("asks", [])
                ],
                "bids": [
                    [float(bid[0]), float(bid[1])] for bid in data.get("bids", [])
                ],
                "ts": int(data["ts"]),
            }
            await broadcast_orderbook(symbol, orderbook_data)
        except Exception as e:
            logger.error(f"Error handling orderbook: {e}")

    async def handle_trades(self, symbol: str, data: list):
        """处理成交记录"""
        try:
            trades_data = {
                "symbol": symbol,
                "trades": [
                    {
                        "tradeId": trade["tradeId"],
                        "price": float(trade["px"]),
                        "size": float(trade["sz"]),
                        "side": trade["side"],  # buy or sell
                        "ts": int(trade["ts"]),
                    }
                    for trade in data
                ],
            }
            await broadcast_trades(symbol, trades_data)
        except Exception as e:
            logger.error(f"Error handling trades: {e}")

    async def handle_kline(self, symbol: str, bar: str, data: dict):
        """
        处理K线数据

        OKX K线数据格式:
        [
            "1597026383085",  // ts: 开始时间
            "3.721",          // o: 开盘价
            "3.743",          // h: 最高价
            "3.677",          // l: 最低价
            "3.708",          // c: 收盘价
            "8422410",        // vol: 成交量(张)
            "22698348.04",    // volCcy: 成交量(币)
            "0"               // confirm: 0未确认 1已确认
        ]
        """
        try:
            kline_data = {
                "symbol": symbol,
                "bar": bar,
                "ts": data[0],
                "o": data[1],
                "h": data[2],
                "l": data[3],
                "c": data[4],
                "vol": data[5],
                "volCcy": data[6],
                "confirm": data[7],
            }
            await broadcast_kline(symbol, kline_data)
        except Exception as e:
            logger.error(f"Error handling kline: {e}")

    async def handle_order(self, data: dict):
        """
        处理订单更新数据

        OKX订单数据中的关键字段:
        - ordId: 订单ID
        - instId: 产品ID (如 BTC-USDT)
        - side: buy/sell
        - ordType: market/limit/post_only等
        - state: live/partially_filled/filled/canceled
        - sz: 委托数量
        - accFillSz: 累计成交数量
        - avgPx: 成交均价
        - fee: 手续费
        """
        try:
            logger.info(
                f"📦 收到订单更新: {data.get('ordId')} - 状态={data.get('state')}, "
                f"交易对={data.get('instId')}, 已成交={data.get('accFillSz')}/{data.get('sz')}"
            )

            # 映射OKX字段到策略期望的字段格式
            order_data = {
                "order_id": data.get("ordId"),
                "symbol": data.get("instId"),
                "side": data.get("side"),
                "order_type": data.get("ordType", "limit"),
                "status": data.get("state"),  # live/partially_filled/filled/canceled
                "price": float(data.get("avgPx") or data.get("px", 0)),
                "size": float(data.get("sz", 0)),
                "filled_size": float(data.get("accFillSz", 0)),
                "fee": float(data.get("fee", 0)),
                "fee_currency": data.get("feeCcy"),
                "timestamp": int(data.get("uTime", 0)),
            }

            # 将订单更新广播到策略管理器
            # 通过strategy manager找到对应的策略并调用其on_order_update方法
            from app.services.strategy.manager import strategy_manager

            # 遍历所有运行中的策略,找到匹配交易对的策略
            inst_id = data.get("instId")
            for strategy_id, strategy in strategy_manager.strategies.items():
                if hasattr(strategy, "symbol") and strategy.symbol == inst_id:
                    # 调用策略的订单更新回调,传递映射后的数据
                    await strategy.on_order_update(order_data)
                    logger.info(f"✅ 订单更新已推送到策略 {strategy_id}")

        except Exception as e:
            logger.error(f"❌ 处理订单更新失败: {e}")

    async def listen_public(self):
        """监听public WebSocket消息（ticker, orderbook, trades）"""
        while self.running:
            try:
                if not self.ws_public:
                    logger.warning("Public WebSocket not connected")
                    await asyncio.sleep(self.reconnect_delay)
                    continue

                message = await self.ws_public.recv()
                data = json.loads(message)
                await self.handle_message(data)

            except websockets.exceptions.ConnectionClosed:
                logger.warning("Public WebSocket connection closed, reconnecting...")
                await self.reconnect()
            except Exception as e:
                logger.error(f"Error in public listen loop: {e}")
                await asyncio.sleep(1)

    async def listen_business(self):
        """监听business WebSocket消息（K线数据）"""
        while self.running:
            try:
                if not self.ws_business:
                    logger.warning("Business WebSocket not connected")
                    await asyncio.sleep(self.reconnect_delay)
                    continue

                message = await self.ws_business.recv()
                data = json.loads(message)
                await self.handle_message(data)

            except websockets.exceptions.ConnectionClosed:
                logger.warning("Business WebSocket connection closed, reconnecting...")
                await self.reconnect()
            except Exception as e:
                logger.error(f"Error in business listen loop: {e}")
                await asyncio.sleep(1)

    async def listen_private(self):
        """监听private WebSocket消息（订单更新等）"""
        while self.running:
            try:
                if not self.ws_private:
                    logger.warning("Private WebSocket not connected")
                    await asyncio.sleep(self.reconnect_delay)
                    continue

                message = await self.ws_private.recv()
                data = json.loads(message)

                # 处理登录响应
                if data.get("event") == "login":
                    if data.get("code") == "0":
                        logger.info("✅ Private WebSocket login success")
                    else:
                        logger.error(f"❌ Private WebSocket login failed: {data}")
                    continue

                # 处理订阅确认
                if data.get("event") == "subscribe":
                    logger.info(f"✅ Private channel subscription confirmed: {data}")
                    continue

                # 处理错误
                if data.get("event") == "error":
                    logger.error(f"❌ Private WebSocket error: {data}")
                    continue

                # 处理数据推送
                await self.handle_message(data)

            except websockets.exceptions.ConnectionClosed:
                logger.warning("⚠️ Private WebSocket connection closed, reconnecting...")
                await self.reconnect()
            except Exception as e:
                logger.error(f"❌ Error in private listen loop: {e}")
                await asyncio.sleep(1)

    async def reconnect(self):
        """重连"""
        logger.info("Attempting to reconnect...")
        await asyncio.sleep(self.reconnect_delay)

        if await self.connect():
            # 重新订阅之前的频道
            old_channels = list(self.subscribed_channels)
            self.subscribed_channels.clear()

            for channel_key in old_channels:
                parts = channel_key.split(":")
                if len(parts) == 2:
                    channel, symbol = parts
                    if channel == "tickers":
                        await self.subscribe_ticker(symbol)
                    elif channel.startswith("books"):
                        await self.subscribe_orderbook(symbol, channel)
                    elif channel == "trades":
                        await self.subscribe_trades(symbol)
                    elif channel.startswith("candle"):
                        # 提取K线周期，如 candle1m -> 1m
                        bar = channel.replace("candle", "")
                        await self.subscribe_kline(symbol, bar)

    async def start(self):
        """启动WebSocket客户端"""
        if await self.connect():
            # 启动监听任务：public, business, private(如果已连接)
            asyncio.create_task(self.listen_public())
            asyncio.create_task(self.listen_business())

            # 如果Private WebSocket已连接,启动监听任务并订阅orders频道
            if self.ws_private and self.private_authenticated:
                asyncio.create_task(self.listen_private())
                # 订阅所有SPOT订单更新
                await self.subscribe_orders("SPOT")
                logger.info("🔔 已订阅Private WebSocket订单更新频道")

            asyncio.create_task(self.manage_subscriptions())
        else:
            logger.error("Failed to start OKX WebSocket client")

    async def manage_subscriptions(self):
        """管理订阅 - 根据用户订阅动态调整OKX订阅"""
        while self.running:
            try:
                # 获取当前所有被订阅的交易对
                subscribed_symbols = ws_manager.get_subscribed_symbols()

                # 订阅新的交易对
                for symbol in subscribed_symbols:
                    await self.subscribe_ticker(symbol)
                    await self.subscribe_orderbook(symbol)
                    await self.subscribe_trades(symbol)
                    # 订阅多个周期的K线数据（注意：分钟小写m，小时大写H，天大写D）
                    await self.subscribe_kline(symbol, "1m")
                    await self.subscribe_kline(symbol, "5m")
                    await self.subscribe_kline(symbol, "15m")
                    await self.subscribe_kline(symbol, "1H")
                    await self.subscribe_kline(symbol, "4H")
                    await self.subscribe_kline(symbol, "1D")

                # 每10秒检查一次
                await asyncio.sleep(10)

            except Exception as e:
                logger.error(f"Error in manage_subscriptions: {e}")
                await asyncio.sleep(10)


# 全局OKX WebSocket客户端
okx_ws_client = OKXWebSocketClient()
