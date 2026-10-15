"""
模拟订单管理器
用于模拟盘的订单生命周期管理
"""

import time
import asyncio
import random
from decimal import Decimal
from typing import Dict, Optional, List
from loguru import logger


class MockOrderManager:
    """模拟订单管理器"""

    def __init__(self):
        self.orders: Dict[str, Dict] = {}  # order_id -> order_data
        self.next_order_id = 1
        self.pending_tasks = {}  # order_id -> asyncio.Task

    def create_order(
        self, symbol: str, side: str, price: str, size: str, order_type: str = "limit"
    ) -> Dict:
        """
        创建模拟订单

        Args:
            symbol: 交易对
            side: 买卖方向 (buy/sell)
            price: 价格
            size: 数量
            order_type: 订单类型 (limit/market)

        Returns:
            订单信息字典
        """
        # 生成唯一的模拟订单ID
        order_id = f"MOCK-{self.next_order_id:08d}"
        self.next_order_id += 1

        # 创建订单数据结构（模拟OKX API返回格式）
        order = {
            "ordId": order_id,
            "clOrdId": "",
            "tag": "",
            "instId": symbol,
            "side": side.lower(),
            "ordType": order_type,
            "px": str(price),
            "sz": str(size),
            "state": "live",  # 初始状态为未成交
            "accFillSz": "0",  # 已成交数量
            "fillPx": "0",  # 成交均价
            "fillSz": "0",  # 成交数量
            "fillTime": "",
            "avgPx": "0",  # 成交均价
            "lever": "1",
            "tpTriggerPx": "",
            "tpOrdPx": "",
            "slTriggerPx": "",
            "slOrdPx": "",
            "feeCcy": "",
            "fee": "0",
            "rebateCcy": "",
            "rebate": "0",
            "pnl": "0",
            "category": "",
            "uTime": str(int(time.time() * 1000)),
            "cTime": str(int(time.time() * 1000)),
        }

        self.orders[order_id] = order

        # 模拟延迟成交（2-10秒后自动成交）
        delay = random.uniform(2, 10)
        task = asyncio.create_task(self._auto_fill_order(order_id, delay))
        self.pending_tasks[order_id] = task

        logger.info(
            f"创建模拟订单: {order_id} | {symbol} | {side} | "
            f"价格={price} | 数量={size} | 将在{delay:.1f}秒后成交"
        )

        return order

    async def _auto_fill_order(self, order_id: str, delay: float):
        """
        自动成交订单

        Args:
            order_id: 订单ID
            delay: 延迟时间（秒）
        """
        try:
            await asyncio.sleep(delay)

            if order_id not in self.orders:
                return

            order = self.orders[order_id]

            # 模拟成交
            order["state"] = "filled"
            order["accFillSz"] = order["sz"]
            order["fillSz"] = order["sz"]
            order["avgPx"] = order["px"]
            order["fillPx"] = order["px"]
            order["fillTime"] = str(int(time.time() * 1000))
            order["uTime"] = str(int(time.time() * 1000))

            # 模拟手续费（0.1%）
            fee_rate = Decimal("0.001")
            trade_amount = Decimal(order["px"]) * Decimal(order["sz"])
            fee = trade_amount * fee_rate
            order["fee"] = str(fee)
            order["feeCcy"] = "USDT"

            logger.info(
                f"模拟订单成交: {order_id} | {order['instId']} | "
                f"{order['side']} | {order['avgPx']} | {order['accFillSz']}"
            )

        except asyncio.CancelledError:
            logger.info(f"模拟订单自动成交任务被取消: {order_id}")
        except Exception as e:
            logger.error(f"模拟订单自动成交失败: {order_id} - {e}")

    def get_order(self, order_id: str) -> Optional[Dict]:
        """
        获取订单信息

        Args:
            order_id: 订单ID

        Returns:
            订单信息，如果不存在返回None
        """
        return self.orders.get(order_id)

    def get_pending_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """
        获取所有未成交订单

        Args:
            symbol: 交易对（可选，如果指定则只返回该交易对的订单）

        Returns:
            未成交订单列表
        """
        pending = []
        for order in self.orders.values():
            if order["state"] in ["live", "partially_filled"]:
                if symbol is None or order["instId"] == symbol:
                    pending.append(order)
        return pending

    def cancel_order(self, order_id: str) -> bool:
        """
        取消订单

        Args:
            order_id: 订单ID

        Returns:
            是否成功取消
        """
        if order_id not in self.orders:
            return False

        order = self.orders[order_id]

        # 只能取消未成交或部分成交的订单
        if order["state"] not in ["live", "partially_filled"]:
            return False

        # 取消自动成交任务
        if order_id in self.pending_tasks:
            task = self.pending_tasks[order_id]
            if not task.done():
                task.cancel()
            del self.pending_tasks[order_id]

        # 更新订单状态
        order["state"] = "canceled"
        order["uTime"] = str(int(time.time() * 1000))

        logger.info(f"取消模拟订单: {order_id}")

        return True

    def get_all_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """
        获取所有订单（包括已成交、已取消）

        Args:
            symbol: 交易对（可选）

        Returns:
            订单列表
        """
        if symbol is None:
            return list(self.orders.values())
        else:
            return [
                order for order in self.orders.values() if order["instId"] == symbol
            ]

    def clear_filled_orders(self, older_than_seconds: int = 3600):
        """
        清理已成交的旧订单（节省内存）

        Args:
            older_than_seconds: 清理多少秒之前的订单
        """
        current_time = int(time.time() * 1000)
        to_remove = []

        for order_id, order in self.orders.items():
            if order["state"] in ["filled", "canceled"]:
                update_time = int(order["uTime"])
                if current_time - update_time > older_than_seconds * 1000:
                    to_remove.append(order_id)

        for order_id in to_remove:
            del self.orders[order_id]
            if order_id in self.pending_tasks:
                del self.pending_tasks[order_id]

        if to_remove:
            logger.info(f"清理了 {len(to_remove)} 个旧的模拟订单")

    def reset(self):
        """重置管理器（清空所有订单）"""
        # 取消所有pending任务
        for task in self.pending_tasks.values():
            if not task.done():
                task.cancel()

        self.orders.clear()
        self.pending_tasks.clear()
        self.next_order_id = 1

        logger.info("重置模拟订单管理器")
