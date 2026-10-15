"""
网格交易策略

核心逻辑：
  1. 在 [price_lower, price_upper] 范围内等分 grid_count 个网格
  2. 当前价格以下挂买单，以上挂卖单
  3. 买单成交后在上一格挂卖单，卖单成交后在下一格挂买单
  4. 每一轮买卖差价即为网格利润

参数说明：
  - price_upper:    网格上界
  - price_lower:    网格下界
  - grid_count:     网格数量（5~200）
  - total_amount:   总投资额（USDT）
  - leverage:       杠杆倍数（合约，默认1）
  - stop_loss:      止损比例（价格跌破下界多少比例时全部平仓，默认5%）
"""

import time
import asyncio
from typing import Dict, List, Optional
from decimal import Decimal, ROUND_DOWN
from loguru import logger

from app.services.strategy.base import StrategyBase
from app.services.notification import notification_service
from app.core.database import SessionLocal
from app.models.strategy import Strategy as DBStrategy


class GridStrategy(StrategyBase):
    """网格交易策略"""

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
        self.price_upper: float = float(p.get("price_upper", 0))
        self.price_lower: float = float(p.get("price_lower", 0))
        self.grid_count: int = int(p.get("grid_count", 10))
        self.total_amount: float = float(p.get("total_amount", 100))
        self.leverage: int = int(p.get("leverage", 1))
        self.stop_loss: float = float(p.get("stop_loss", 0.05))

        # 合约相关
        self._is_swap: bool = symbol.endswith("-SWAP") or symbol.endswith("-FUTURES")
        self._ct_val: float = 0.1
        self._lot_sz: float = 1.0
        self._min_sz: float = 1.0
        self._tick_sz: float = 0.01  # 价格精度

        # 网格状态
        self._grid_prices: List[float] = []  # 每个网格的价格（升序）
        self._grid_spacing: float = 0.0  # 网格间距
        self._amount_per_grid: float = 0.0  # 每格投资额（USDT）
        self._active_orders: Dict[str, dict] = (
            {}
        )  # {order_id: {side, price, grid_idx, amount}}
        self._filled_grids: Dict[int, str] = (
            {}
        )  # {grid_idx: "buy"/"sell"} 记录每格已成交的方向

        # 统计
        self.realized_pnl: float = 0.0
        self.total_trades: int = 0
        self._win_trades: int = 0
        self.win_rate: float = 0.0
        self._buy_count: int = 0
        self._sell_count: int = 0
        self._unrealized_pnl: float = 0.0
        self._in_position: bool = False
        self._entry_price: float = 0.0

        # 控制并发
        self._placing_orders: bool = False
        self._last_check_time: float = 0
        self._check_interval: float = 10  # 每10秒检查一次订单状态

        logger.info(
            f"GridStrategy 初始化: {symbol} "
            f"range=[{self.price_lower}, {self.price_upper}] "
            f"grids={self.grid_count} amount={self.total_amount} USDT"
        )

    # ═══════════════════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════════════════

    async def start(self):
        self.is_running = True

        if self.price_upper <= self.price_lower:
            logger.error(f"[{self.symbol}] 网格上界必须大于下界")
            self.is_running = False
            return

        if self.grid_count < 2:
            logger.error(f"[{self.symbol}] 网格数量至少为 2")
            self.is_running = False
            return

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
                    self._tick_sz = float(info.get("tickSz", self._tick_sz))
                    logger.info(
                        f"[{self.symbol}] 合约规格: ctVal={self._ct_val} "
                        f"lotSz={self._lot_sz} minSz={self._min_sz} tickSz={self._tick_sz}"
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
                logger.info(f"[{self.symbol}] 杠杆已设置为 {self.leverage}x")
            except Exception as e:
                logger.warning(f"[{self.symbol}] 设置杠杆失败: {e}")
        else:
            # 现货：获取交易精度
            try:
                instruments = await self.exchange.get_instruments(
                    inst_type="SPOT", inst_id=self.symbol
                )
                if instruments:
                    info = instruments[0]
                    self._lot_sz = float(info.get("lotSz", 0.0001))
                    self._min_sz = float(info.get("minSz", 0.0001))
                    self._tick_sz = float(info.get("tickSz", 0.01))
            except Exception as e:
                logger.warning(f"[{self.symbol}] 获取现货规格失败: {e}")

        # 计算网格
        self._calculate_grids()

        # 获取当前价格并初始下单
        try:
            ticker = await self.exchange.get_ticker(self.symbol)
            current_price = float(ticker.get("last", 0))
            if current_price <= 0:
                logger.error(f"[{self.symbol}] 无法获取当前价格")
                self.is_running = False
                return

            self._entry_price = current_price
            self._in_position = True

            logger.info(
                f"[{self.symbol}] 当前价格: {current_price:.4f}, "
                f"网格间距: {self._grid_spacing:.4f}, "
                f"每格金额: {self._amount_per_grid:.2f} USDT"
            )

            await self._place_initial_orders(current_price)

        except Exception as e:
            logger.error(f"[{self.symbol}] 初始下单失败: {e}")
            import traceback

            logger.error(traceback.format_exc())

        logger.info(f"策略 {self.strategy_id} [{self.symbol}] 网格策略已启动")

    async def stop(self, cancel_orders: bool = True, close_position: bool = True):
        self.is_running = False

        if cancel_orders:
            await self._cancel_all_orders()

        self._in_position = False
        logger.info(f"策略 {self.strategy_id} [{self.symbol}] 网格策略已停止")

    # ═══════════════════════════════════════════════════════════
    # 核心 Tick 回调（每5秒由 manager 调用）
    # ═══════════════════════════════════════════════════════════

    async def on_tick(self, ticker: Dict):
        if not self.is_running:
            return

        price = float(ticker.get("last", 0))
        if price <= 0:
            return

        # 止损检查：价格跌破下界 * (1 - stop_loss)
        stop_price = self.price_lower * (1 - self.stop_loss)
        if price <= stop_price:
            logger.warning(
                f"[{self.symbol}] 触发网格止损! 当前价={price:.4f} "
                f"止损价={stop_price:.4f}"
            )
            await self._cancel_all_orders()
            self._in_position = False
            try:
                await notification_service.notify_position_closed(
                    user_id=self.user_id,
                    strategy_id=self.strategy_id,
                    strategy_name=f"网格策略#{self.strategy_id}",
                    symbol=self.symbol,
                    side="buy",
                    entry_price=self._entry_price,
                    exit_price=price,
                    amount=0,
                    pnl=self.realized_pnl,
                    pnl_pct=0,
                    reason="网格止损",
                )
            except Exception:
                pass
            self.is_running = False
            return

        # 超出上界提醒（不止损，只记录日志）
        if price > self.price_upper * 1.05:
            logger.warning(
                f"[{self.symbol}] 价格({price:.4f})已超出网格上界({self.price_upper:.4f})"
            )

        # 定期检查订单状态并补单
        now = time.time()
        if (
            now - self._last_check_time >= self._check_interval
            and not self._placing_orders
        ):
            self._last_check_time = now
            await self._check_and_replace_orders(price)

    async def on_kline(self, kline: Dict):
        pass

    async def on_order_update(self, order: Dict):
        """处理订单成交更新"""
        order_id = order.get("ordId") or order.get("order_id")
        state = order.get("state") or order.get("status")

        if order_id not in self._active_orders:
            return

        if state == "filled":
            grid_order = self._active_orders.pop(order_id)
            side = grid_order["side"]
            grid_idx = grid_order["grid_idx"]
            fill_price = float(
                order.get("avgPx") or order.get("fillPx") or grid_order["price"]
            )

            if side == "buy":
                self._buy_count += 1
                self._filled_grids[grid_idx] = "buy"
                # 买单成交后，在上一格挂卖单
                sell_idx = grid_idx + 1
                if sell_idx < len(self._grid_prices):
                    sell_price = self._grid_prices[sell_idx]
                    await self._place_grid_order("sell", sell_price, sell_idx)

                    # 记录一次网格利润（预估）
                    grid_profit = (sell_price - fill_price) * self._qty_for_price(
                        fill_price
                    )
                    if self._is_swap:
                        grid_profit *= self._ct_val

                logger.info(
                    f"[{self.symbol}] 网格买单成交 grid[{grid_idx}] "
                    f"price={fill_price:.4f}"
                )

            elif side == "sell":
                self._sell_count += 1
                self._filled_grids[grid_idx] = "sell"
                # 卖单成交后，在下一格挂买单
                buy_idx = grid_idx - 1
                if buy_idx >= 0:
                    buy_price = self._grid_prices[buy_idx]
                    await self._place_grid_order("buy", buy_price, buy_idx)

                # 计算本次网格利润
                pnl = self._grid_spacing * self._qty_for_price(fill_price)
                if self._is_swap:
                    pnl *= self._ct_val
                self.realized_pnl += pnl
                self.total_trades += 1
                self._win_trades += 1
                self.win_rate = self._win_trades / self.total_trades * 100
                self.record_trade_result(pnl)

                logger.info(
                    f"[{self.symbol}] 网格卖单成交 grid[{grid_idx}] "
                    f"price={fill_price:.4f} pnl={pnl:+.4f} "
                    f"累计={self.realized_pnl:+.4f}"
                )

        elif state == "canceled":
            self._active_orders.pop(order_id, None)

    async def calculate_pnl(self) -> Dict:
        return {
            "total_pnl": round(self.realized_pnl, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "unrealized_pnl": 0,
            "total_fee": 0,
            "pnl_rate": 0,
            "buy_count": self._buy_count,
            "sell_count": self._sell_count,
            "win_rate": round(self.win_rate, 1),
            "in_position": self._in_position,
            "entry_price": self._entry_price,
            "active_orders": len(self._active_orders),
            "grid_count": self.grid_count,
        }

    # ═══════════════════════════════════════════════════════════
    # 网格计算
    # ═══════════════════════════════════════════════════════════

    def _calculate_grids(self):
        """计算网格价格级别"""
        self._grid_spacing = (self.price_upper - self.price_lower) / self.grid_count
        self._grid_prices = [
            round(self.price_lower + i * self._grid_spacing, 8)
            for i in range(self.grid_count + 1)
        ]
        # 每格投入金额
        self._amount_per_grid = self.total_amount / self.grid_count

        logger.info(
            f"[{self.symbol}] 网格计算完成: "
            f"{len(self._grid_prices)} 个价格级别, "
            f"间距={self._grid_spacing:.4f}, "
            f"每格={self._amount_per_grid:.2f} USDT"
        )

    def _qty_for_price(self, price: float) -> float:
        """根据价格计算每格的下单数量"""
        if self._is_swap:
            # 合约：名义价值 = 投入额 * 杠杆
            notional = self._amount_per_grid * self.leverage
            contracts = (
                notional / (price * self._ct_val) if (price * self._ct_val) > 0 else 0
            )
            qty = max(self._min_sz, int(contracts / self._lot_sz) * self._lot_sz)
            return qty
        else:
            # 现货：币数 = 投入额 / 价格
            raw_qty = self._amount_per_grid / price if price > 0 else 0
            # 按精度截断
            if self._lot_sz > 0:
                qty = int(raw_qty / self._lot_sz) * self._lot_sz
            else:
                qty = round(raw_qty, 6)
            return max(self._min_sz, qty)

    def _round_price(self, price: float) -> float:
        """按照交易所价格精度取整"""
        if self._tick_sz > 0:
            return round(round(price / self._tick_sz) * self._tick_sz, 8)
        return round(price, 4)

    # ═══════════════════════════════════════════════════════════
    # 下单逻辑
    # ═══════════════════════════════════════════════════════════

    async def _place_initial_orders(self, current_price: float):
        """根据当前价格在网格上下分别挂买卖单"""
        self._placing_orders = True
        try:
            buy_count = 0
            sell_count = 0

            for i, grid_price in enumerate(self._grid_prices):
                if not self.is_running:
                    break

                if grid_price < current_price:
                    # 当前价格以下挂买单
                    await self._place_grid_order("buy", grid_price, i)
                    buy_count += 1
                elif grid_price > current_price:
                    # 当前价格以上挂卖单（仅当有对应持仓或做市时）
                    # 网格策略通常只在下方挂买单，买入后才在上方挂卖单
                    # 但初始可以两端都挂以快速捕捉波动
                    pass

                # 避免下单过快触发API限制
                if (buy_count + sell_count) % 5 == 0 and (buy_count + sell_count) > 0:
                    await asyncio.sleep(0.2)

            logger.info(f"[{self.symbol}] 初始网格挂单完成: " f"买单={buy_count}")

        finally:
            self._placing_orders = False

    async def _place_grid_order(self, side: str, price: float, grid_idx: int):
        """在指定网格价格挂单"""
        try:
            rounded_price = self._round_price(price)
            qty = self._qty_for_price(rounded_price)

            if qty <= 0:
                logger.warning(f"[{self.symbol}] grid[{grid_idx}] 计算数量为0，跳过")
                return

            order = await self.place_order_with_retry(
                side=side,
                amount=Decimal(str(qty)),
                price=Decimal(str(rounded_price)),
                order_type="limit",
                max_retries=2,
                retry_delay=0.5,
            )

            if order:
                order_id = order.get("ordId")
                if order_id:
                    self._active_orders[order_id] = {
                        "side": side,
                        "price": rounded_price,
                        "grid_idx": grid_idx,
                        "amount": qty,
                    }
                    logger.debug(
                        f"[{self.symbol}] 网格{side}单已挂: "
                        f"grid[{grid_idx}] price={rounded_price} qty={qty}"
                    )
        except Exception as e:
            logger.error(f"[{self.symbol}] 网格挂单失败 grid[{grid_idx}]: {e}")

    async def _check_and_replace_orders(self, current_price: float):
        """检查活跃订单状态，处理已成交订单并补单"""
        if self._placing_orders:
            return

        self._placing_orders = True
        try:
            # 查询所有活跃订单状态
            order_ids = list(self._active_orders.keys())
            filled_orders = []

            for order_id in order_ids:
                if not self.is_running:
                    break
                try:
                    order_detail = await self.exchange.get_order(
                        symbol=self.symbol, order_id=order_id
                    )
                    state = order_detail.get("state", "")

                    if state == "filled":
                        filled_orders.append((order_id, order_detail))
                    elif state in ("canceled", "expired"):
                        self._active_orders.pop(order_id, None)

                except Exception as e:
                    logger.debug(f"[{self.symbol}] 查询订单 {order_id} 失败: {e}")

                # 避免API限频
                await asyncio.sleep(0.1)

            # 处理已成交订单
            for order_id, detail in filled_orders:
                await self.on_order_update(detail)

            # 检查是否需要补单（确保网格覆盖完整）
            active_buy_grids = set()
            active_sell_grids = set()
            for info in self._active_orders.values():
                if info["side"] == "buy":
                    active_buy_grids.add(info["grid_idx"])
                else:
                    active_sell_grids.add(info["grid_idx"])

            # 找到当前价格所在的网格
            current_grid = 0
            for i, gp in enumerate(self._grid_prices):
                if gp <= current_price:
                    current_grid = i

            # 补充缺失的买单（当前价格以下）
            for i in range(current_grid + 1):
                if (
                    i not in active_buy_grids
                    and self._grid_prices[i] < current_price
                    and self._filled_grids.get(i) != "buy"
                ):
                    await self._place_grid_order("buy", self._grid_prices[i], i)
                    await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"[{self.symbol}] 检查订单状态失败: {e}")
        finally:
            self._placing_orders = False

    async def _cancel_all_orders(self):
        """取消所有活跃订单"""
        order_ids = list(self._active_orders.keys())
        for order_id in order_ids:
            try:
                await self.exchange.cancel_order(symbol=self.symbol, order_id=order_id)
                logger.debug(f"[{self.symbol}] 已取消订单 {order_id}")
            except Exception as e:
                logger.warning(f"[{self.symbol}] 取消订单 {order_id} 失败: {e}")
            await asyncio.sleep(0.05)

        self._active_orders.clear()
        self._filled_grids.clear()
        logger.info(f"[{self.symbol}] 已取消全部 {len(order_ids)} 个活跃订单")
