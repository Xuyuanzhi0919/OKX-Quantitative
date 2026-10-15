"""
双向持仓策略 - 支持多空双向交易

核心逻辑：
  - EMA快慢线判断趋势方向
  - 金叉（fast上穿slow）→ 开多仓
  - 死叉（fast下穿slow）→ 开空仓
  - 趋势反转时平仓并反向开仓
  - 支持固定止损/止盈 + 移动止损

参数说明：
  - leverage: 杠杆倍数（默认5x，建议3x-5x）
  - fast_period: EMA快线周期（默认12）
  - slow_period: EMA慢线周期（默认40）
  - stop_loss: 止损比例（默认0.02 = 2%）
  - take_profit: 止盈比例（默认0.06 = 6%）
  - trailing_stop: 移动止损比例（默认0.02 = 2%，0表示禁用）
  - position_ratio: 开仓资金比例（默认0.3 = 30%）
  - timeframe: K线周期（默认15m）
"""

import time
from typing import Dict, List, Optional
from decimal import Decimal
from loguru import logger

from app.services.strategy.base import StrategyBase
from app.services.notification import notification_service
from app.core.database import SessionLocal
from app.models.strategy import Strategy as DBStrategy


# ── 默认参数 ─────────────────────────────────────────────────────
_DEFAULT_FAST_PERIOD = 12
_DEFAULT_SLOW_PERIOD = 40
_DEFAULT_TIMEFRAME = "15m"
_DEFAULT_KLINE_LIMIT = 80
_DEFAULT_LEVERAGE = 5
_DEFAULT_STOP_LOSS = 0.02  # 2%
_DEFAULT_TAKE_PROFIT = 0.06  # 6%
_DEFAULT_TRAILING_STOP = 0.02  # 2%
_DEFAULT_POSITION_RATIO = 0.3  # 30%
_DEFAULT_PROFIT_LOCK_RATIO = 0.5  # 锁住峰值盈利的50%，0表示禁用


class DualSideStrategy(StrategyBase):
    """
    双向持仓策略 - 支持做多和做空

    状态机：
    - 无持仓 → 检测趋势信号 → 开多/开空
    - 持有多仓 → 检测死叉 → 平多+开空
    - 持有空仓 → 检测金叉 → 平空+开多
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
        self.fast_period: int = int(p.get("fast_period", _DEFAULT_FAST_PERIOD))
        self.slow_period: int = int(p.get("slow_period", _DEFAULT_SLOW_PERIOD))
        self.timeframe: str = p.get("timeframe", _DEFAULT_TIMEFRAME)
        self.leverage: int = int(p.get("leverage", _DEFAULT_LEVERAGE))

        # 风控参数
        self.stop_loss: float = float(p.get("stop_loss", _DEFAULT_STOP_LOSS))
        self.take_profit: float = float(p.get("take_profit", _DEFAULT_TAKE_PROFIT))
        self.trailing_stop: float = float(
            p.get("trailing_stop", _DEFAULT_TRAILING_STOP)
        )
        self.position_ratio: float = float(
            p.get("position_ratio", _DEFAULT_POSITION_RATIO)
        )
        # 盈利保护：峰值盈利的多少比例作为止损下限，0=禁用
        self.profit_lock_ratio: float = float(
            p.get("profit_lock_ratio", _DEFAULT_PROFIT_LOCK_RATIO)
        )

        # 保证金模式
        self.margin_mode: str = p.get("margin_mode", "isolated")  # isolated 或 cross

        # EMA状态
        self._fast_prev: Optional[float] = None
        self._fast_curr: Optional[float] = None
        self._slow_prev: Optional[float] = None
        self._slow_curr: Optional[float] = None

        # 合约规格
        self._ct_val: float = 0.1  # 合约面值
        self._lot_sz: float = 1.0  # 下单精度
        self._min_sz: float = 1.0  # 最小下单量
        self._is_swap: bool = symbol.endswith("-SWAP") or symbol.endswith("-FUTURES")
        self._position_mode: str = "net_mode"
        self._use_pos_side: bool = False

        # 仓位状态
        self._position_side: str = ""  # "long" / "short" / ""
        self._entry_price: float = 0.0
        self._position_qty: float = 0.0
        self._open_time: float = 0.0
        self._extreme_price: float = 0.0  # 多仓=最高价，空仓=最低价
        self._trail_stop_px: float = 0.0
        self._peak_pnl_pct: float = 0.0  # 本次持仓期间的浮盈峰值百分比

        # K线周期追踪
        self._last_kline_period: int = 0

        # 统计数据
        self.realized_pnl: float = 0.0
        self.total_trades: int = 0
        self._win_trades: int = 0
        self.win_rate: float = 0.0
        self._long_count: int = 0
        self._short_count: int = 0
        self._unrealized_pnl: float = 0.0

        logger.info(
            f"DualSideStrategy 初始化: {symbol} "
            f"fast={self.fast_period} slow={self.slow_period} "
            f"leverage={self.leverage}x "
            f"sl={self.stop_loss*100:.1f}% tp={self.take_profit*100:.1f}% "
            f"trail={self.trailing_stop*100:.1f}%"
        )

    # ═══════════════════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════════════════

    async def start(self):
        """启动策略"""
        self.is_running = True
        self._last_kline_period = 0

        # 从数据库恢复持仓状态
        await self._restore_position_state()

        # 获取合约规格
        if self._is_swap:
            await self._init_contract_specs()

        # 预热EMA
        await self._init_ema()

        # 根据当前趋势方向自动开仓（如果无持仓）
        await self._check_initial_entry()

        # 初始化K线周期
        await self._init_kline_period()

        logger.info(f"策略 {self.strategy_id} [{self.symbol}] 双向持仓策略已启动")

    async def stop(self, cancel_orders: bool = True, close_position: bool = True):
        """停止策略"""
        self.is_running = False
        if close_position and self._position_side:
            await self._close_position(reason="stop")
        logger.info(
            f"策略 {self.strategy_id} [{self.symbol}] 已停止 (平仓={close_position})"
        )

    # ═══════════════════════════════════════════════════════════
    # 核心回调
    # ═══════════════════════════════════════════════════════════

    async def on_tick(self, ticker: Dict):
        """每5秒调用一次，处理止损止盈和K线信号"""
        if not self.is_running:
            return

        price = float(ticker.get("last", 0))
        if price <= 0:
            return

        # 更新未实现盈亏
        self._update_unrealized_pnl(price)

        # 检查止损止盈
        if self._position_side:
            await self._check_stop_loss_take_profit(price)

        # 检查K线信号（每周期一次）
        await self._check_kline_signal()

    async def on_kline(self, kline: Dict):
        """K线推送回调（保留接口兼容）"""
        pass

    async def on_order_update(self, order: Dict):
        """订单成交回调"""
        logger.debug(
            f"[{self.symbol}] 订单更新: {order.get('ordId')} status={order.get('state')}"
        )

    async def calculate_pnl(self) -> Dict:
        """返回当前盈亏统计"""
        unrealized = self._unrealized_pnl
        try:
            if self._position_side and self._entry_price > 0 and self._position_qty > 0:
                ticker = await self.exchange.get_ticker(self.symbol)
                current_price = float(ticker.get("last", 0))
                if current_price > 0:
                    unrealized = self._calculate_pnl_for_price(current_price)
        except Exception as e:
            logger.warning(f"[{self.symbol}] 计算未实现盈亏失败: {e}")

        return {
            "total_pnl": round(self.realized_pnl + unrealized, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "unrealized_pnl": round(unrealized, 4),
            "total_fee": 0,
            "pnl_rate": 0,
            "long_count": self._long_count,
            "short_count": self._short_count,
            "win_rate": round(self.win_rate, 1),
            "in_position": bool(self._position_side),
            "position_side": self._position_side,
            "entry_price": self._entry_price,
        }

    # ═══════════════════════════════════════════════════════════
    # 初始化方法
    # ═══════════════════════════════════════════════════════════

    async def _restore_position_state(self):
        """从数据库恢复持仓状态"""
        self._position_side = ""
        self._entry_price = 0.0
        self._position_qty = 0.0
        self._open_time = 0.0
        self._extreme_price = 0.0
        self._trail_stop_px = 0.0

        try:
            _db = SessionLocal()
            try:
                db_s = (
                    _db.query(DBStrategy)
                    .filter(DBStrategy.id == self.strategy_id)
                    .first()
                )
                if db_s and db_s.position_in_position:
                    self._position_side = db_s.position_side or ""
                    self._entry_price = float(db_s.position_entry_price or 0)
                    self._position_qty = float(db_s.position_qty or 0)
                    self._open_time = float(db_s.position_open_time or 0)
                    self._extreme_price = float(
                        db_s.position_highest_price or self._entry_price
                    )
                    self._trail_stop_px = float(db_s.position_trail_stop_px or 0)
                    logger.warning(
                        f"[{self.symbol}] 🔄 恢复持仓: side={self._position_side} "
                        f"qty={self._position_qty} entry={self._entry_price:.2f}"
                    )
            finally:
                _db.close()
        except Exception as e:
            logger.warning(f"[{self.symbol}] 恢复持仓状态失败: {e}")

    async def _init_contract_specs(self):
        """初始化合约规格"""
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
            logger.warning(f"[{self.symbol}] 获取合约规格失败: {e}")

        # 设置/检测持仓模式（开平仓模式优先，失败则兼容 net mode）
        try:
            config = await self.exchange.get_account_config()
            self._position_mode = config.get("posMode") or "net_mode"
        except Exception as e:
            self._position_mode = "net_mode"
            logger.warning(
                f"[{self.symbol}] 获取持仓模式失败，按 net_mode 兼容下单: {e}"
            )

        try:
            if self._position_mode != "long_short_mode":
                await self.exchange.set_position_mode("long_short_mode")
                self._position_mode = "long_short_mode"
            logger.info(f"[{self.symbol}] 持仓模式已设置为双向持仓 (long_short_mode)")
        except Exception as e:
            logger.warning(
                f"[{self.symbol}] 设置双向持仓失败，使用当前 net_mode 下单；"
                f"如需同时持有多空，请先在 OKX 平掉持仓/挂单后切换: {e}"
            )

        self._use_pos_side = self._position_mode == "long_short_mode"

        # 设置杠杆
        try:
            if self._use_pos_side:
                await self.exchange.set_leverage(
                    lever=str(self.leverage),
                    mgn_mode=self.margin_mode,
                    inst_id=self.symbol,
                    pos_side="long",
                )
                await self.exchange.set_leverage(
                    lever=str(self.leverage),
                    mgn_mode=self.margin_mode,
                    inst_id=self.symbol,
                    pos_side="short",
                )
            else:
                await self.exchange.set_leverage(
                    lever=str(self.leverage),
                    mgn_mode=self.margin_mode,
                    inst_id=self.symbol,
                )
            logger.info(
                f"[{self.symbol}] 杠杆已设置为 {self.leverage}x ({self.margin_mode})"
            )
        except Exception as e:
            logger.warning(f"[{self.symbol}] 设置杠杆失败: {e}")

    async def _init_ema(self):
        """用历史K线预热EMA"""
        try:
            klines = await self.exchange.get_kline(
                self.symbol, self.timeframe, _DEFAULT_KLINE_LIMIT
            )
            if not klines or len(klines) < self.slow_period + 2:
                logger.warning(f"[{self.symbol}] K线数据不足，无法预热EMA")
                return

            confirmed = [k for k in reversed(klines) if k.get("confirm") == "1"]
            closes = [float(k["c"]) for k in confirmed]

            if len(closes) < self.slow_period + 2:
                logger.warning(f"[{self.symbol}] 已确认K线不足")
                return

            # 计算EMA
            self._fast_curr = self._ema(closes, self.fast_period)
            self._slow_curr = self._ema(closes, self.slow_period)

            # 计算前一个周期的EMA（用于交叉检测）
            prev_closes = closes[:-1]
            self._fast_prev = self._ema(prev_closes, self.fast_period)
            self._slow_prev = self._ema(prev_closes, self.slow_period)

            logger.info(
                f"[{self.symbol}] EMA预热完成: "
                f"fast={self._fast_curr:.2f} slow={self._slow_curr:.2f} "
                f"趋势={'上升' if self._fast_curr > self._slow_curr else '下降'}"
            )
        except Exception as e:
            logger.error(f"[{self.symbol}] EMA预热失败: {e}")

    async def _check_initial_entry(self):
        """启动时检查是否需要自动开仓"""
        if self._position_side:  # 数据库已恢复持仓，跳过
            return

        if self._fast_curr is None or self._slow_curr is None:
            logger.warning(f"[{self.symbol}] EMA未初始化，跳过自动开仓")
            return

        # 先查交易所实际持仓，防止重启时重复开仓
        try:
            positions = await self.exchange.get_positions(inst_id=self.symbol)
            for pos in positions:
                qty = float(pos.get("pos", 0))
                if qty == 0:
                    continue
                pos_side = pos.get("posSide", "")  # long / short / net
                avg_px = float(pos.get("avgPx", 0))
                if pos_side in ("long", "short") and avg_px > 0:
                    # 交易所有持仓，直接恢复，不开新仓
                    self._position_side = pos_side
                    self._entry_price = avg_px
                    self._position_qty = abs(qty)
                    self._extreme_price = avg_px
                    await self._save_position_state()
                    logger.warning(
                        f"[{self.symbol}] 🔄 从交易所恢复持仓: side={pos_side} "
                        f"qty={abs(qty)} entry={avg_px:.4f}"
                    )
                    return
        except Exception as e:
            logger.warning(f"[{self.symbol}] 查询交易所持仓失败，继续开仓逻辑: {e}")

        try:
            ticker = await self.exchange.get_ticker(self.symbol)
            price = float(ticker.get("last", 0))
            if price <= 0:
                return

            if self._fast_curr > self._slow_curr:
                logger.info(f"[{self.symbol}] 启动时趋势向上，开多")
                await self._open_position(price, "long")
            else:
                logger.info(f"[{self.symbol}] 启动时趋势向下，开空")
                await self._open_position(price, "short")
        except Exception as e:
            logger.warning(f"[{self.symbol}] 自动开仓失败: {e}")

    async def _init_kline_period(self):
        """初始化K线周期追踪"""
        now_ms = int(time.time() * 1000)
        period_ms = self._get_period_ms()
        self._last_kline_period = (now_ms // period_ms) * period_ms

    def _get_period_ms(self) -> int:
        """获取K线周期对应的毫秒数"""
        tf = self.timeframe.lower()
        multipliers = {"m": 60 * 1000, "h": 60 * 60 * 1000, "d": 24 * 60 * 60 * 1000}
        unit = tf[-1]
        value = int(tf[:-1]) if len(tf) > 1 else 1
        return value * multipliers.get(unit, 60 * 1000)

    # ═══════════════════════════════════════════════════════════
    # 信号处理
    # ═══════════════════════════════════════════════════════════

    async def _check_kline_signal(self):
        """检查K线信号（每周期一次）"""
        now_ms = int(time.time() * 1000)
        period_ms = self._get_period_ms()
        current_period = (now_ms // period_ms) * period_ms

        if current_period == self._last_kline_period:
            return

        self._last_kline_period = current_period
        await self._process_kline_signal()

    async def _process_kline_signal(self):
        """处理K线信号，检测趋势变化"""
        try:
            klines = await self.exchange.get_kline(
                self.symbol, self.timeframe, _DEFAULT_KLINE_LIMIT
            )
        except Exception as e:
            logger.error(f"[{self.symbol}] 获取K线失败: {e}")
            return

        if not klines or len(klines) < self.slow_period + 2:
            return

        confirmed = [k for k in reversed(klines) if k.get("confirm") == "1"]
        if len(confirmed) < self.slow_period + 2:
            return

        closes = [float(k["c"]) for k in confirmed]

        # 保存旧的EMA值
        self._fast_prev = self._fast_curr
        self._slow_prev = self._slow_curr

        # 计算新的EMA
        self._fast_curr = self._ema(closes, self.fast_period)
        self._slow_curr = self._ema(closes, self.slow_period)

        if self._fast_prev is None or self._slow_prev is None:
            return

        # 检测交叉
        golden_cross = (
            self._fast_prev <= self._slow_prev and self._fast_curr > self._slow_curr
        )
        death_cross = (
            self._fast_prev >= self._slow_prev and self._fast_curr < self._slow_curr
        )

        current_price = closes[-1]

        if golden_cross:
            logger.info(
                f"[{self.symbol}] 📈 金叉信号: fast={self._fast_curr:.2f} > slow={self._slow_curr:.2f}"
            )
            if self._position_side == "short":
                # 平空并开多
                await self._close_position(reason="golden_cross")
                await self._open_position(current_price, "long")
            elif not self._position_side:
                await self._open_position(current_price, "long")

        elif death_cross:
            logger.info(
                f"[{self.symbol}] 📉 死叉信号: fast={self._fast_curr:.2f} < slow={self._slow_curr:.2f}"
            )
            if self._position_side == "long":
                # 平多并开空
                await self._close_position(reason="death_cross")
                await self._open_position(current_price, "short")
            elif not self._position_side:
                await self._open_position(current_price, "short")

    # ═══════════════════════════════════════════════════════════
    # 止损止盈
    # ═══════════════════════════════════════════════════════════

    async def _check_stop_loss_take_profit(self, price: float):
        """检查止损止盈"""
        if not self._position_side or self._entry_price <= 0:
            return

        if self._position_side == "long":
            pnl_pct = (price - self._entry_price) / self._entry_price
        else:
            pnl_pct = (self._entry_price - price) / self._entry_price

        # 更新峰值盈利（只升不降）
        if pnl_pct > self._peak_pnl_pct:
            self._peak_pnl_pct = pnl_pct

        # 移动止损（基于价格峰值）
        if self.trailing_stop > 0:
            await self._update_trailing_stop(price, pnl_pct)

        # 盈利保护止损：峰值盈利超过 stop_loss 才激活，避免小波动误触发
        if self.profit_lock_ratio > 0 and self._peak_pnl_pct >= self.stop_loss:
            profit_lock_floor = self._peak_pnl_pct * self.profit_lock_ratio
            if pnl_pct < profit_lock_floor:
                logger.info(
                    f"[{self.symbol}] 触发盈利保护止损: "
                    f"当前盈利={pnl_pct*100:.2f}% "
                    f"低于保护线={profit_lock_floor*100:.2f}% "
                    f"(峰值={self._peak_pnl_pct*100:.2f}% × {self.profit_lock_ratio})"
                )
                await self._close_position(reason="profit_lock")
                return

        # 固定止损
        if pnl_pct <= -self.stop_loss:
            logger.info(f"[{self.symbol}] 触发止损 {pnl_pct*100:.2f}%")
            await self._close_position(reason="stop_loss")
            return

        # 止盈
        if pnl_pct >= self.take_profit:
            logger.info(f"[{self.symbol}] 触发止盈 {pnl_pct*100:.2f}%")
            await self._close_position(reason="take_profit")
            return

    async def _update_trailing_stop(self, price: float, pnl_pct: float):
        """更新移动止损"""
        if self._position_side == "long":
            # 多仓：价格上涨时上移止损
            if price > self._extreme_price:
                self._extreme_price = price
                self._trail_stop_px = price * (1 - self.trailing_stop)
                logger.debug(
                    f"[{self.symbol}] 移动止损上移: 最高价={self._extreme_price:.2f}"
                    f" 止损价={self._trail_stop_px:.2f}"
                )
            if price <= self._trail_stop_px:
                logger.info(f"[{self.symbol}] 触发移动止损 {pnl_pct*100:.2f}%")
                await self._close_position(reason="trailing_stop")
        else:
            # 空仓：价格下跌时下移止损
            if price < self._extreme_price:
                self._extreme_price = price
                self._trail_stop_px = price * (1 + self.trailing_stop)
                logger.debug(
                    f"[{self.symbol}] 移动止损下移: 最低价={self._extreme_price:.2f}"
                    f" 止损价={self._trail_stop_px:.2f}"
                )
            if price >= self._trail_stop_px:
                logger.info(f"[{self.symbol}] 触发移动止损 {pnl_pct*100:.2f}%")
                await self._close_position(reason="trailing_stop")

    # ═══════════════════════════════════════════════════════════
    # 交易执行
    # ═══════════════════════════════════════════════════════════

    def _order_pos_side(self, side: str) -> str:
        return side if self._use_pos_side else "net"

    async def _open_position(self, price: float, side: str):
        """开仓"""
        if not self.is_running:
            return

        try:
            # 获取可用余额
            balance = await self.exchange.get_balance("USDT")
            details = balance.get("details", [])
            available = float(details[0].get("availBal", 0)) if details else 0.0
            if available <= 0:
                logger.warning(f"[{self.symbol}] 余额不足，无法开仓")
                return

            # 计算开仓数量
            position_value = available * self.position_ratio * self.leverage
            if self._is_swap:
                qty = round(position_value / self._ct_val / price)
                qty = max(qty, int(self._min_sz))
                qty = int(qty / int(self._lot_sz)) * int(self._lot_sz)
            else:
                qty = round(position_value / price, 6)

            if qty <= 0:
                logger.warning(f"[{self.symbol}] 计算的仓位数量为0")
                return

            # 下单（通过基类方法，自动保存到数据库）
            order_side = "buy" if side == "long" else "sell"
            pos_side = self._order_pos_side(side)

            result = await self.place_order_with_retry(
                side=order_side,
                amount=Decimal(str(qty)),
                order_type="market",
                pos_side=pos_side,
            )

            if result:
                self._position_side = side
                self._entry_price = price
                self._position_qty = qty
                self._open_time = time.time()
                self._extreme_price = price
                self._trail_stop_px = 0
                self._peak_pnl_pct = 0.0  # 重置峰值盈利

                if side == "long":
                    self._long_count += 1
                else:
                    self._short_count += 1

                # 保存到数据库
                await self._save_position_state()

                logger.info(
                    f"[{self.symbol}] ✅ 开{side}成功: qty={qty} "
                    f"price={price:.2f} value={position_value:.2f} USDT"
                )

                # 发送通知
                await self._send_notification(
                    f"📢 开{side}通知",
                    f"交易对: {self.symbol}\n"
                    f"方向: {'做多' if side == 'long' else '做空'}\n"
                    f"数量: {qty}\n"
                    f"价格: {price:.2f}\n"
                    f"杠杆: {self.leverage}x",
                )
        except Exception as e:
            logger.error(f"[{self.symbol}] 开仓失败: {e}")

    async def _close_position(self, reason: str = "signal"):
        """平仓"""
        if not self._position_side:
            return

        try:
            # 获取当前价格
            ticker = await self.exchange.get_ticker(self.symbol)
            price = float(ticker.get("last", 0))
            if price <= 0:
                return

            # 计算盈亏
            pnl = self._calculate_pnl_for_price(price)

            # 下单平仓（通过基类方法，自动保存到数据库）
            order_side = "sell" if self._position_side == "long" else "buy"
            pos_side = self._order_pos_side(self._position_side)

            result = await self.place_order_with_retry(
                side=order_side,
                amount=Decimal(str(self._position_qty)),
                order_type="market",
                pos_side=pos_side,
            )

            if result:
                # 更新统计
                self.realized_pnl += pnl
                self.total_trades += 1
                if pnl > 0:
                    self._win_trades += 1
                self.win_rate = self._win_trades / self.total_trades * 100

                # 记录交易结果（用于连续亏损追踪）
                self.record_trade_result(pnl)

                logger.info(
                    f"[{self.symbol}] ✅ 平仓成功: reason={reason} "
                    f"pnl={pnl:.4f} USDT ({pnl/(self._entry_price*self._position_qty*self._ct_val if self._is_swap else self._entry_price*self._position_qty)*100:.2f}%)"
                )

                # 发送通知
                await self._send_notification(
                    f"📢 平仓通知 ({reason})",
                    f"交易对: {self.symbol}\n"
                    f"方向: {'平多' if self._position_side == 'long' else '平空'}\n"
                    f"盈亏: {pnl:.4f} USDT\n"
                    f"累计盈亏: {self.realized_pnl:.4f} USDT",
                )

                # 重置状态
                self._position_side = ""
                self._entry_price = 0
                self._position_qty = 0
                self._open_time = 0
                self._extreme_price = 0
                self._trail_stop_px = 0

                # 保存到数据库
                await self._save_position_state()

                # 止损/止盈/移动止损触发后，按EMA趋势方向重新入场
                # 需同时满足：fast与slow的相对位置 AND fast自身的运动方向一致
                if reason in ("stop_loss", "take_profit", "trailing_stop"):
                    if (
                        self._fast_curr is not None
                        and self._slow_curr is not None
                        and self._fast_prev is not None
                    ):
                        fast_above_slow = self._fast_curr > self._slow_curr
                        fast_rising = self._fast_curr > self._fast_prev
                        if fast_above_slow and fast_rising:
                            # 金叉向上：fast在slow上方且仍在上升 → 开多
                            logger.info(
                                f"[{self.symbol}] 止损止盈后重入多: "
                                f"fast={self._fast_curr:.2f}↑ slow={self._slow_curr:.2f}"
                            )
                            await self._open_position(price, "long")
                        elif not fast_above_slow and not fast_rising:
                            # 死叉向下：fast在slow下方且仍在下降 → 开空
                            logger.info(
                                f"[{self.symbol}] 止损止盈后重入空: "
                                f"fast={self._fast_curr:.2f}↓ slow={self._slow_curr:.2f}"
                            )
                            await self._open_position(price, "short")
                        else:
                            logger.info(
                                f"[{self.symbol}] 止损止盈后信号不明确，等待下一个K线信号 "
                                f"(fast={self._fast_curr:.2f} slow={self._slow_curr:.2f} "
                                f"fast_prev={self._fast_prev:.2f})"
                            )
        except Exception as e:
            logger.error(f"[{self.symbol}] 平仓失败: {e}")

    # ═══════════════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════════════

    def _ema(self, data: List[float], period: int) -> float:
        """计算EMA"""
        if len(data) < period:
            return 0.0
        multiplier = 2 / (period + 1)
        ema = sum(data[:period]) / period
        for price in data[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _calculate_pnl_for_price(self, price: float) -> float:
        """计算指定价格的未实现盈亏"""
        if not self._position_side or self._entry_price <= 0 or self._position_qty <= 0:
            return 0.0

        ct_val = self._ct_val if self._is_swap else 1.0

        if self._position_side == "long":
            return (price - self._entry_price) * self._position_qty * ct_val
        else:
            return (self._entry_price - price) * self._position_qty * ct_val

    def _update_unrealized_pnl(self, price: float):
        """更新未实现盈亏缓存"""
        self._unrealized_pnl = self._calculate_pnl_for_price(price)

    async def _save_position_state(self):
        """保存持仓状态到数据库"""
        try:
            _db = SessionLocal()
            try:
                db_s = (
                    _db.query(DBStrategy)
                    .filter(DBStrategy.id == self.strategy_id)
                    .first()
                )
                if db_s:
                    db_s.position_in_position = bool(self._position_side)
                    db_s.position_side = self._position_side
                    db_s.position_entry_price = self._entry_price
                    db_s.position_qty = self._position_qty
                    db_s.position_open_time = self._open_time
                    db_s.position_highest_price = self._extreme_price
                    db_s.position_trail_stop_px = self._trail_stop_px
                    _db.commit()
            finally:
                _db.close()
        except Exception as e:
            logger.error(f"[{self.symbol}] 保存持仓状态失败: {e}")

    async def _send_notification(self, title: str, message: str):
        """发送通知"""
        try:
            await notification_service.send_strategy_notification(
                strategy_id=self.strategy_id,
                title=title,
                message=message,
            )
        except Exception as e:
            logger.warning(f"[{self.symbol}] 发送通知失败: {e}")
