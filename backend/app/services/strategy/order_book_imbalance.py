"""
订单簿不平衡高频策略 (Order Book Imbalance Strategy)

核心原理：
- 监控买卖盘深度变化，计算订单簿不平衡度
- 当买盘明显大于卖盘时，预测短期价格上涨，做多
- 当卖盘明显大于买盘时，预测短期价格下跌，做空
- 持仓时间短（秒级到分钟级），高频交易

信号逻辑：
- 不平衡度 = (买盘总量 - 卖盘总量) / (买盘总量 + 卖盘总量)
- 不平衡度 > 阈值 → 做多
- 不平衡度 < -阈值 → 做空
- 结合价格动量和成交量确认信号

风控机制：
- 固定止损止盈
- 最长持仓时间限制
- 交易冷却期
- 连续亏损保护
"""

import time
import asyncio
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from loguru import logger
from datetime import datetime

from app.services.strategy.base import StrategyBase, InsufficientBalanceError


# ── 默认参数 ─────────────────────────────────────────────────────────
_DEFAULT_IMBALANCE_THRESHOLD = 0.25  # 订单簿不平衡阈值 (25%)
_DEFAULT_MIN_DEPTH = 15  # 分析的订单簿深度
_DEFAULT_STOP_LOSS = 0.003  # 止损 0.3%
_DEFAULT_TAKE_PROFIT = 0.006  # 止盈 0.6%
_DEFAULT_HOLDING_SECONDS = 60  # 最长持仓时间(秒)
_DEFAULT_COOLDOWN_SECONDS = 20  # 交易冷却期(秒)
_DEFAULT_POSITION_RATIO = 0.2  # 仓位比例 (20%)
_DEFAULT_LEVERAGE = 10  # 默认杠杆
_DEFAULT_MIN_IMBALANCE_COUNT = 2  # 最小连续不平衡信号次数
_DEFAULT_VOLUME_SPIKE_MULT = 1.5  # 成交量突增倍数


class OrderBookImbalanceStrategy(StrategyBase):
    """
    订单簿不平衡高频策略

    支持通过 parameters 字典覆盖默认参数：
        - imbalance_threshold: 订单簿不平衡阈值（默认 0.25）
        - min_depth: 分析的订单簿深度（默认 15）
        - stop_loss: 止损比例（默认 0.003 = 0.3%）
        - take_profit: 止盈比例（默认 0.006 = 0.6%）
        - holding_seconds: 最长持仓时间（默认 60秒）
        - cooldown_seconds: 交易冷却期（默认 20秒）
        - position_ratio: 仓位比例（默认 0.2）
        - leverage: 杠杆倍数（默认 10）
        - min_imbalance_count: 最小连续信号次数（默认 2）
        - volume_spike_mult: 成交量突增倍数（默认 1.5）
    """

    def __init__(
        self,
        strategy_id: int,
        exchange,
        symbol: str,
        parameters: Dict,
        user_id: int = 1,
    ):
        super().__init__(strategy_id, exchange, symbol, parameters, user_id)

        p = parameters or {}

        # 策略参数
        self.imbalance_threshold: float = float(
            p.get("imbalance_threshold", _DEFAULT_IMBALANCE_THRESHOLD)
        )
        self.min_depth: int = int(p.get("min_depth", _DEFAULT_MIN_DEPTH))
        self.stop_loss: float = float(p.get("stop_loss", _DEFAULT_STOP_LOSS))
        self.take_profit: float = float(p.get("take_profit", _DEFAULT_TAKE_PROFIT))
        self.holding_seconds: int = int(
            p.get("holding_seconds", _DEFAULT_HOLDING_SECONDS)
        )
        self.cooldown_seconds: int = int(
            p.get("cooldown_seconds", _DEFAULT_COOLDOWN_SECONDS)
        )
        self.pos_ratio: float = float(p.get("position_ratio", _DEFAULT_POSITION_RATIO))
        self.leverage: int = int(p.get("leverage", _DEFAULT_LEVERAGE))
        self.min_imbalance_count: int = int(
            p.get("min_imbalance_count", _DEFAULT_MIN_IMBALANCE_COUNT)
        )
        self.volume_spike_mult: float = float(
            p.get("volume_spike_mult", _DEFAULT_VOLUME_SPIKE_MULT)
        )

        # 合约规格
        self._ct_val: float = 0.1
        self._lot_sz: float = 1.0
        self._min_sz: float = 1.0
        self._is_swap: bool = symbol.endswith("-SWAP") or symbol.endswith("-FUTURES")

        # 仓位状态
        self._in_position: bool = False
        self._position_side: str = ""  # "long" or "short"
        self._entry_price: float = 0.0
        self._position_qty: float = 0.0
        self._open_time: float = 0.0

        # 信号追踪
        self._imbalance_history: List[float] = []  # 最近N次不平衡度
        self._last_trade_time: float = 0.0
        self._last_orderbook: Optional[Dict] = None
        self._avg_volume: float = 0.0  # 平均成交量（用于成交量突增检测）

        # 统计数据
        self.realized_pnl: float = 0.0
        self.total_trades: int = 0
        self._win_trades: int = 0
        self.win_rate: float = 0.0
        self._unrealized_pnl: float = 0.0

        logger.info(
            f"OrderBookImbalanceStrategy 初始化: {symbol} "
            f"threshold=±{self.imbalance_threshold*100:.1f}% "
            f"depth={self.min_depth} "
            f"sl={self.stop_loss*100:.2f}% tp={self.take_profit*100:.2f}% "
            f"holding={self.holding_seconds}s cooldown={self.cooldown_seconds}s"
        )

    # ═══════════════════════════════════════════════════════════
    # 生命周期方法
    # ═══════════════════════════════════════════════════════════

    async def start(self):
        """启动策略"""
        self.is_running = True
        self._in_position = False
        self._position_side = ""
        self._entry_price = 0.0
        self._position_qty = 0.0
        self._imbalance_history = []
        self._last_trade_time = 0.0

        # 获取合约规格
        if self._is_swap:
            try:
                inst_type = "SWAP" if self.symbol.endswith("-SWAP") else "FUTURES"
                instruments = await self.exchange.get_instruments(
                    inst_type=inst_type, inst_id=self.symbol
                )
                if instruments:
                    info = instruments[0]
                    self._ct_val = float(info.get("ctVal", self._ct_val))
                    self._lot_sz = float(info.get("lotSz", self._lot_sz))
                    self._min_sz = float(info.get("minSz", self._min_sz))
                    logger.info(
                        f"[{self.symbol}] 合约规格: ctVal={self._ct_val} "
                        f"lotSz={self._lot_sz} minSz={self._min_sz}"
                    )
            except Exception as e:
                logger.warning(f"[{self.symbol}] 获取合约规格失败，使用默认值: {e}")

            # 设置杠杆
            try:
                margin_mode = self.parameters.get("margin_mode", "isolated")
                await self.exchange.set_leverage(
                    lever=str(self.leverage),
                    mgn_mode=margin_mode,
                    inst_id=self.symbol,
                )
                logger.info(
                    f"[{self.symbol}] 杠杆已设置为 {self.leverage}x ({margin_mode})"
                )
            except Exception as e:
                logger.warning(f"[{self.symbol}] 设置杠杆失败: {e}")

        # 初始化平均成交量
        await self._init_avg_volume()

        # 启动监控循环
        asyncio.create_task(self._monitor_loop())

        logger.info(f"[{self.symbol}] 订单簿不平衡策略已启动")

    async def stop(self):
        """停止策略"""
        logger.info(f"[{self.symbol}] 正在停止订单簿不平衡策略...")
        self.is_running = False

        # 平掉当前持仓
        if self._in_position:
            await self._close_position("策略停止")

        logger.info(f"[{self.symbol}] 订单簿不平衡策略已停止")

    async def on_tick(self, ticker: Dict):
        """处理实时行情 - 用于止损止盈检查"""
        if not self.is_running or not self._in_position:
            return

        current_price = float(ticker.get("last", 0))
        if current_price <= 0:
            return

        # 更新未实现盈亏
        if self._position_side == "long":
            self._unrealized_pnl = (
                current_price - self._entry_price
            ) / self._entry_price
        else:
            self._unrealized_pnl = (
                self._entry_price - current_price
            ) / self._entry_price

        # 检查止损止盈
        await self._check_stop_loss_take_profit(current_price)

    async def on_kline(self, kline: Dict):
        """处理K线数据 - 更新平均成交量"""
        volume = float(kline.get("volume", 0))
        if volume > 0:
            # 指数移动平均更新
            alpha = 0.1
            self._avg_volume = alpha * volume + (1 - alpha) * self._avg_volume

    async def on_order_update(self, order: Dict):
        """处理订单更新"""
        ordId = order.get("ordId")
        state = order.get("state")

        logger.info(f"[{self.symbol}] 订单更新: ordId={ordId}, state={state}")

        # 订单完全成交
        if state == "filled":
            fillPx = float(order.get("fillPx", order.get("avgPx", 0)))
            fillSz = float(order.get("fillSz", order.get("accFillSz", 0)))
            side = order.get("side")

            if side == "buy" and not self._in_position:
                # 开多仓
                self._in_position = True
                self._position_side = "long"
                self._entry_price = fillPx
                self._position_qty = fillSz
                self._open_time = time.time()
                logger.info(
                    f"[{self.symbol}] 📈 开多仓成功: price={fillPx}, qty={fillSz}"
                )

            elif side == "sell" and not self._in_position:
                # 开空仓
                self._in_position = True
                self._position_side = "short"
                self._entry_price = fillPx
                self._position_qty = fillSz
                self._open_time = time.time()
                logger.info(
                    f"[{self.symbol}] 📉 开空仓成功: price={fillPx}, qty={fillSz}"
                )

            elif (side == "sell" and self._position_side == "long") or (
                side == "buy" and self._position_side == "short"
            ):
                # 平仓
                pnl = self._unrealized_pnl
                self._close_position_record(pnl, fillPx)
                logger.info(
                    f"[{self.symbol}] ✅ 平仓成功: price={fillPx}, pnl={pnl*100:.2f}%"
                )

    # ═══════════════════════════════════════════════════════════
    # 核心策略逻辑
    # ═══════════════════════════════════════════════════════════

    async def _monitor_loop(self):
        """监控循环 - 定期获取订单簿并分析"""
        while self.is_running:
            try:
                # 获取订单簿
                orderbook = await self.exchange.get_orderbook(
                    self.symbol, self.min_depth
                )
                self._last_orderbook = orderbook

                # 计算订单簿不平衡度
                imbalance = self._calculate_imbalance(orderbook)

                # 记录历史
                self._imbalance_history.append(imbalance)
                if len(self._imbalance_history) > 10:
                    self._imbalance_history.pop(0)

                # 检查持仓超时
                if self._in_position:
                    await self._check_holding_timeout()

                # 如果没有持仓且冷却期已过，检查信号
                if not self._in_position and self._is_cooldown_over():
                    await self._check_trading_signal(imbalance, orderbook)

                # 短暂休眠（高频策略，间隔短）
                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"[{self.symbol}] 监控循环错误: {e}")
                await asyncio.sleep(2)

    def _calculate_imbalance(self, orderbook: Dict) -> float:
        """
        计算订单簿不平衡度

        不平衡度 = (买盘总量 - 卖盘总量) / (买盘总量 + 卖盘总量)
        范围: [-1, 1]
        - 正值表示买盘强势
        - 负值表示卖盘强势
        """
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])

        if not bids or not asks:
            return 0.0

        # 计算买盘总量（按金额加权）
        bid_volume = 0.0
        for i, (price, amount) in enumerate(bids[: self.min_depth]):
            bid_volume += float(price) * float(amount)

        # 计算卖盘总量
        ask_volume = 0.0
        for i, (price, amount) in enumerate(asks[: self.min_depth]):
            ask_volume += float(price) * float(amount)

        total_volume = bid_volume + ask_volume
        if total_volume == 0:
            return 0.0

        imbalance = (bid_volume - ask_volume) / total_volume

        logger.debug(
            f"[{self.symbol}] 订单簿不平衡度: {imbalance:.4f} "
            f"(买盘={bid_volume:.2f}, 卖盘={ask_volume:.2f})"
        )

        return imbalance

    def _is_cooldown_over(self) -> bool:
        """检查冷却期是否已过"""
        return time.time() - self._last_trade_time >= self.cooldown_seconds

    def _is_signal_confirmed(self, signal: float) -> bool:
        """
        检查信号是否确认（连续多次同向信号）

        Args:
            signal: 当前信号方向 (1=做多, -1=做空)

        Returns:
            是否确认
        """
        if len(self._imbalance_history) < self.min_imbalance_count:
            return False

        # 检查最近N次信号是否同向
        recent = self._imbalance_history[-self.min_imbalance_count :]

        if signal > 0:
            # 做多信号：最近N次不平衡度都应大于阈值
            return all(imb > self.imbalance_threshold for imb in recent)
        else:
            # 做空信号：最近N次不平衡度都应小于负阈值
            return all(imb < -self.imbalance_threshold for imb in recent)

    async def _check_trading_signal(self, imbalance: float, orderbook: Dict):
        """检查交易信号"""
        # 判断信号方向
        signal = 0
        if imbalance > self.imbalance_threshold:
            signal = 1  # 做多信号
        elif imbalance < -self.imbalance_threshold:
            signal = -1  # 做空信号

        if signal == 0:
            return

        # 检查信号确认
        if not self._is_signal_confirmed(signal):
            logger.debug(
                f"[{self.symbol}] 信号未确认: signal={signal}, imbalance={imbalance:.4f}"
            )
            return

        # 获取当前价格
        ticker = await self.exchange.get_ticker(self.symbol)
        current_price = float(ticker.get("last", 0))
        if current_price <= 0:
            return

        # 成交量确认（可选）
        volume_24h = float(ticker.get("vol24h", 0))
        if (
            self._avg_volume > 0
            and volume_24h < self._avg_volume * self.volume_spike_mult
        ):
            logger.debug(f"[{self.symbol}] 成交量不足，跳过信号")
            return

        # 执行交易
        if signal > 0:
            await self._open_long(current_price, imbalance)
        else:
            await self._open_short(current_price, imbalance)

    async def _open_long(self, price: float, imbalance: float):
        """开多仓"""
        logger.info(
            f"[{self.symbol}] 🔔 做多信号: price={price}, imbalance={imbalance:.4f}"
        )

        try:
            # 计算仓位大小
            amount = await self._calculate_position_size(price)
            if amount <= 0:
                logger.warning(f"[{self.symbol}] 计算仓位大小失败")
                return

            # 下市价单（高频策略使用市价单确保成交）
            order = await self.exchange.create_order(
                symbol=self.symbol,
                side="buy",
                order_type="market",
                amount=Decimal(str(amount)),
                price=None,
            )

            self._last_trade_time = time.time()
            logger.info(f"[{self.symbol}] 📤 开多单已提交: amount={amount}")

        except InsufficientBalanceError:
            logger.warning(f"[{self.symbol}] 余额不足，无法开多")
        except Exception as e:
            logger.error(f"[{self.symbol}] 开多失败: {e}")

    async def _open_short(self, price: float, imbalance: float):
        """开空仓"""
        logger.info(
            f"[{self.symbol}] 🔔 做空信号: price={price}, imbalance={imbalance:.4f}"
        )

        try:
            # 计算仓位大小
            amount = await self._calculate_position_size(price)
            if amount <= 0:
                logger.warning(f"[{self.symbol}] 计算仓位大小失败")
                return

            # 下市价单
            order = await self.exchange.create_order(
                symbol=self.symbol,
                side="sell",
                order_type="market",
                amount=Decimal(str(amount)),
                price=None,
            )

            self._last_trade_time = time.time()
            logger.info(f"[{self.symbol}] 📤 开空单已提交: amount={amount}")

        except InsufficientBalanceError:
            logger.warning(f"[{self.symbol}] 余额不足，无法开空")
        except Exception as e:
            logger.error(f"[{self.symbol}] 开空失败: {e}")

    async def _close_position(self, reason: str = ""):
        """平仓"""
        if not self._in_position:
            return

        logger.info(f"[{self.symbol}] 🔄 平仓: reason={reason}")

        try:
            side = "sell" if self._position_side == "long" else "buy"

            order = await self.exchange.create_order(
                symbol=self.symbol,
                side=side,
                order_type="market",
                amount=Decimal(str(self._position_qty)),
                price=None,
            )

            self._last_trade_time = time.time()
            logger.info(
                f"[{self.symbol}] 📤 平仓单已提交: side={side}, qty={self._position_qty}"
            )

        except Exception as e:
            logger.error(f"[{self.symbol}] 平仓失败: {e}")

    def _close_position_record(self, pnl: float, close_price: float):
        """记录平仓结果"""
        self._in_position = False
        self._position_side = ""
        self.realized_pnl += pnl
        self.total_trades += 1

        if pnl > 0:
            self._win_trades += 1

        self.win_rate = (
            self._win_trades / self.total_trades if self.total_trades > 0 else 0
        )
        self._unrealized_pnl = 0
        self._entry_price = 0
        self._position_qty = 0

        # 记录交易结果（用于连续亏损追踪）
        self.record_trade_result(pnl)

    async def _check_stop_loss_take_profit(self, current_price: float):
        """检查止损止盈"""
        if not self._in_position:
            return

        pnl_ratio = self._unrealized_pnl

        # 止损
        if pnl_ratio <= -self.stop_loss:
            logger.info(f"[{self.symbol}] 🛑 触发止损: pnl={pnl_ratio*100:.2f}%")
            await self._close_position("止损")

        # 止盈
        elif pnl_ratio >= self.take_profit:
            logger.info(f"[{self.symbol}] 🎯 触发止盈: pnl={pnl_ratio*100:.2f}%")
            await self._close_position("止盈")

    async def _check_holding_timeout(self):
        """检查持仓超时"""
        if not self._in_position:
            return

        holding_time = time.time() - self._open_time
        if holding_time >= self.holding_seconds:
            logger.info(
                f"[{self.symbol}] ⏰ 持仓超时: {holding_time:.0f}s >= {self.holding_seconds}s"
            )
            await self._close_position("持仓超时")

    async def _calculate_position_size(self, price: float) -> float:
        """计算仓位大小"""
        try:
            balance_info = await self.exchange.get_balance()

            # 获取可用USDT
            available = 0.0
            for item in balance_info:
                if item.get("ccy") == "USDT":
                    available = float(item.get("availBal", 0))
                    break

            if available <= 0:
                logger.warning(f"[{self.symbol}] 可用余额为0")
                return 0

            # 计算仓位金额
            position_value = available * self.pos_ratio * self.leverage

            if self._is_swap:
                # 合约：计算张数
                contracts = position_value / (self._ct_val * price)
                contracts = max(contracts, self._min_sz)
                # 对齐精度
                contracts = round(contracts / self._lot_sz) * self._lot_sz
                return contracts
            else:
                # 现货：计算币数
                amount = position_value / price
                return amount

        except Exception as e:
            logger.error(f"[{self.symbol}] 计算仓位大小失败: {e}")
            return 0

    async def _init_avg_volume(self):
        """初始化平均成交量"""
        try:
            ticker = await self.exchange.get_ticker(self.symbol)
            self._avg_volume = (
                float(ticker.get("vol24h", 0)) / 1440
            )  # 粗略估算每分钟成交量
            logger.info(f"[{self.symbol}] 初始化平均成交量: {self._avg_volume:.2f}")
        except Exception as e:
            logger.warning(f"[{self.symbol}] 初始化平均成交量失败: {e}")
            self._avg_volume = 0

    def get_stats(self) -> Dict:
        """获取策略统计数据"""
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "is_running": self.is_running,
            "in_position": self._in_position,
            "position_side": self._position_side,
            "entry_price": self._entry_price,
            "position_qty": self._position_qty,
            "unrealized_pnl": self._unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "consecutive_losses": self.consecutive_losses,
            "last_imbalance": (
                self._imbalance_history[-1] if self._imbalance_history else 0
            ),
            "holding_time": time.time() - self._open_time if self._in_position else 0,
        }
