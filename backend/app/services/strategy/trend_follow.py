"""
趋势跟踪策略 - EMA 双均线交叉（已优化）

最优参数（经 256 组网格搜索 + 交叉验证）：
  EMA 快线: 12
  EMA 慢线: 40
  止损:     1.0%（由实时 Ticker 价格触发）
  止盈:     8.0%（由实时 Ticker 价格触发）
  过滤:     RSI14 < 65（开仓前检查，过滤超买）
  方向:     Long-only（15m 时间周期最优）

信号逻辑：
  - 每 15 分钟取一次已确认 K 线的收盘价更新 EMA
  - 金叉（fast 上穿 slow）且 RSI < 65 → 开多
  - 死叉（fast 下穿 slow）→ 平多
  - 实时 Ticker 价格触发止损/止盈（无需等 K 线关闭）
"""

import time
from typing import Dict, List, Optional
from decimal import Decimal
from loguru import logger

from app.services.strategy.base import StrategyBase
from app.services.notification import notification_service
from app.core.database import SessionLocal
from app.models.strategy import Strategy as DBStrategy


# ── 最优超参数（不可随意修改，来自回测验证） ─────────────────────────
_FAST_PERIOD = 12
_SLOW_PERIOD = 40
_RSI_PERIOD = 14
_RSI_THRESHOLD = 65.0  # RSI 超过此值不开仓（超买过滤）
_TIMEFRAME = "15m"
_KLINE_LIMIT = 80  # 预热 K 线数（>= slow_period + warmup）
_LOOP_SECONDS = 15 * 60  # 15 分钟换一次 K 线周期


class TrendFollowStrategy(StrategyBase):
    """
    EMA 双均线趋势跟踪策略（实盘版）

    支持通过 parameters 字典覆盖默认参数：
      - fast_period:   EMA 快线周期（默认 12）
      - slow_period:   EMA 慢线周期（默认 40）
      - stop_loss:     止损比例（默认 0.01 = 1%）
      - take_profit:   止盈比例（默认 0.08 = 8%）
      - position_ratio: 每次开仓占可用资金的比例（默认 0.4 = 40%）
      - use_rsi_filter: 是否启用 RSI 过滤（默认 True）
      - rsi_threshold:  RSI 阈值（默认 65.0）
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
        self.fast_period: int = int(p.get("fast_period", _FAST_PERIOD))
        self.slow_period: int = int(p.get("slow_period", _SLOW_PERIOD))
        self.stop_loss: float = float(p.get("stop_loss", 0.01))
        self.take_profit: float = float(p.get("take_profit", 0.08))
        self.pos_ratio: float = float(p.get("position_ratio", 0.4))
        self.use_rsi: bool = bool(p.get("use_rsi_filter", True))
        self.rsi_threshold: float = float(p.get("rsi_threshold", _RSI_THRESHOLD))
        self.leverage: int = int(p.get("leverage", 10))  # 默认 10x

        # EMA 状态（仅保留最近两个值用于交叉判断）
        self._fast_prev: Optional[float] = None
        self._fast_curr: Optional[float] = None
        self._slow_prev: Optional[float] = None
        self._slow_curr: Optional[float] = None

        # 合约规格（在 start() 时动态获取）
        self._ct_val: float = 0.1  # 合约面值（默认 ETH-USDT-SWAP）
        self._lot_sz: float = 1.0  # 下单数量精度（张）
        self._min_sz: float = 1.0  # 最小下单量（张）
        self._is_swap: bool = symbol.endswith("-SWAP") or symbol.endswith("-FUTURES")

        # 移动止损参数
        self.trailing_stop: float = float(
            p.get("trailing_stop", 0.0)
        )  # 0 表示禁用，例如 0.02 = 2%

        # 仓位状态
        self._in_position: bool = False
        self._entry_price: float = 0.0
        self._position_qty: float = 0.0  # 持仓数量（合约张数 or 币数）
        self._open_time: float = 0.0  # 开仓时间（unix 秒），用于最短持仓保护
        self._highest_price: float = 0.0  # 持仓期间最高价（移动止损用）
        self._trail_stop_px: float = 0.0  # 当前移动止损触发价

        # K 线周期追踪（毫秒级时间戳，以 15min 对齐）
        self._last_kline_period: int = 0

        # 统计数据（供 manager 广播）
        self.realized_pnl: float = 0.0
        self.total_trades: int = 0  # 完整开平仓轮次（用于胜率）
        self._win_trades: int = 0
        self.win_rate: float = 0.0
        self._buy_count: int = 0  # 买入订单次数
        self._sell_count: int = 0  # 卖出订单次数
        self._unrealized_pnl: float = 0.0  # 当前未实现盈亏缓存（每 tick 更新）

        logger.info(
            f"TrendFollowStrategy 初始化: {symbol} "
            f"fast={self.fast_period} slow={self.slow_period} "
            f"sl={self.stop_loss*100:.1f}% tp={self.take_profit*100:.1f}% "
            f"RSI过滤={'是' if self.use_rsi else '否'}"
        )

    # ═══════════════════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════════════════

    async def start(self):
        self.is_running = True
        self._last_kline_period = 0

        # ── 从数据库恢复持仓状态（防止重启后持仓信息丢失）────────────
        self._in_position = False
        self._entry_price = 0.0
        self._position_qty = 0.0
        self._open_time = 0.0
        self._highest_price = 0.0
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
                    self._in_position = True
                    self._entry_price = float(db_s.position_entry_price or 0)
                    self._position_qty = float(db_s.position_qty or 0)
                    self._open_time = float(db_s.position_open_time or 0)
                    self._highest_price = float(
                        db_s.position_highest_price or self._entry_price
                    )
                    self._trail_stop_px = float(db_s.position_trail_stop_px or 0)
                    logger.warning(
                        f"[{self.symbol}] 🔄 重启后恢复持仓: qty={self._position_qty} "
                        f"entry={self._entry_price:.2f} highest={self._highest_price:.2f}"
                    )
            finally:
                _db.close()
        except Exception as e:
            logger.warning(f"[{self.symbol}] 从数据库恢复持仓状态失败，视为无持仓: {e}")

        # 获取合约规格（SWAP/FUTURES 需要知道合约面值和最小手数）
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

        # 用历史 K 线预热 EMA
        await self._init_ema()

        # 立即入场：如果 fast > slow（当前处于上升趋势），直接开多
        # 避免启动后要等下一次金叉才能入场，错过已有趋势
        # 注意：如果重启后已恢复持仓，跳过自动开仓
        if (
            self._fast_curr is not None
            and self._slow_curr is not None
            and self._fast_curr > self._slow_curr
            and not self._in_position
        ):
            try:
                ticker = await self.exchange.get_ticker(self.symbol)
                price = float(ticker.get("last", 0))
                if price > 0:
                    # 仍然检查 RSI 过滤
                    klines = await self.exchange.get_kline(
                        self.symbol, _TIMEFRAME, _KLINE_LIMIT
                    )
                    confirmed = [k for k in reversed(klines) if k.get("confirm") == "1"]
                    closes = [float(k["c"]) for k in confirmed]
                    if (
                        self.use_rsi
                        and closes
                        and self._rsi(closes) >= self.rsi_threshold
                    ):
                        logger.info(
                            f"[{self.symbol}] 启动时处于上升趋势但 RSI 超买({self._rsi(closes):.1f})，等待回落后金叉再入场"
                        )
                    else:
                        logger.info(
                            f"[{self.symbol}] 启动时处于上升趋势 (fast={self._fast_curr:.2f} > slow={self._slow_curr:.2f})，立即开多"
                        )
                        await self._open_position(price)
            except Exception as e:
                logger.warning(f"[{self.symbol}] 启动时立即入场失败: {e}")

        # ── Fix: 将 _last_kline_period 初始化为当前周期，避免首次 tick 立即触发信号 ──
        now_ms = int(time.time() * 1000)
        period_ms = 15 * 60 * 1000
        self._last_kline_period = (now_ms // period_ms) * period_ms

        logger.info(f"策略 {self.strategy_id} [{self.symbol}] 已启动")

    async def stop(self, cancel_orders: bool = True, close_position: bool = True):
        self.is_running = False
        if close_position and self._in_position:
            await self._close_position(reason="stop")
        logger.info(
            f"策略 {self.strategy_id} [{self.symbol}] 已停止 (平仓={close_position})"
        )

    # ═══════════════════════════════════════════════════════════
    # 核心 Tick 回调（由 manager 每 5 秒调用）
    # ═══════════════════════════════════════════════════════════

    async def on_tick(self, ticker: Dict):
        """
        每 5 秒由 manager 调用一次。
        1. 用实时价格检查止损/止盈（快速响应）。
        2. 每 15 分钟刷新一次 EMA 并检查交叉信号。
        """
        if not self.is_running:
            return

        price = float(ticker.get("last", 0))
        if price <= 0:
            return

        # ── 更新未实现盈亏缓存（每 tick，供 manager 广播）────────
        if self._in_position and self._entry_price > 0 and self._position_qty > 0:
            ct_val = self._ct_val if self._is_swap else 1.0
            self._unrealized_pnl = (
                (price - self._entry_price) * self._position_qty * ct_val
            )
        else:
            self._unrealized_pnl = 0.0

        # ── 止损 / 止盈（实时触发）───────────────────────────────
        if self._in_position and self._entry_price > 0:
            pnl_pct = (price - self._entry_price) / self._entry_price

            # 移动止损：更新最高价，并随之上移止损价
            if self.trailing_stop > 0:
                if price > self._highest_price:
                    self._highest_price = price
                    self._trail_stop_px = price * (1 - self.trailing_stop)
                    logger.debug(
                        f"[{self.symbol}] 移动止损上移: 最高价={self._highest_price:.2f}"
                        f" 止损价={self._trail_stop_px:.2f}"
                    )
                if price <= self._trail_stop_px:
                    logger.info(
                        f"[{self.symbol}] 触发移动止损 当前={price:.2f}"
                        f" 止损价={self._trail_stop_px:.2f}"
                        f" 持仓盈亏={pnl_pct*100:.2f}%"
                    )
                    await self._close_position(reason="trailing_stop")
                    return
            else:
                # 固定止损
                if pnl_pct <= -self.stop_loss:
                    logger.info(f"[{self.symbol}] 触发止损 {pnl_pct*100:.2f}%")
                    await self._close_position(reason="stop_loss")
                    return

            if pnl_pct >= self.take_profit:
                logger.info(f"[{self.symbol}] 触发止盈 {pnl_pct*100:.2f}%")
                await self._close_position(reason="take_profit")
                return

        # ── 15 分钟 K 线信号（每周期只处理一次）──────────────────
        now_ms = int(time.time() * 1000)
        period_ms = 15 * 60 * 1000
        current_period = (now_ms // period_ms) * period_ms

        if current_period != self._last_kline_period:
            self._last_kline_period = current_period
            await self._process_kline_signal()

    async def calculate_pnl(self) -> Dict:
        """
        返回当前盈亏统计，供 /api/v1/strategies/{id}/pnl 接口调用。
        """
        # 优先使用实时 ticker 计算；失败则用缓存值
        unrealized = self._unrealized_pnl
        try:
            if self._in_position and self._entry_price > 0 and self._position_qty > 0:
                ticker = await self.exchange.get_ticker(self.symbol)
                current_price = float(ticker.get("last", 0))
                if current_price > 0:
                    ct_val = self._ct_val if self._is_swap else 1.0
                    unrealized = (
                        (current_price - self._entry_price)
                        * self._position_qty
                        * ct_val
                    )
        except Exception as e:
            logger.warning(f"[{self.symbol}] 计算未实现盈亏失败，使用缓存值: {e}")

        return {
            "total_pnl": round(self.realized_pnl + unrealized, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "unrealized_pnl": round(unrealized, 4),
            "total_fee": 0,
            "pnl_rate": 0,
            "buy_count": self._buy_count,
            "sell_count": self._sell_count,
            "win_rate": round(self.win_rate, 1),
            "in_position": self._in_position,
            "entry_price": self._entry_price,
        }

    async def on_kline(self, kline: Dict):
        """K 线推送回调（当前架构未使用，保留接口兼容）"""
        pass

    async def on_order_update(self, order: Dict):
        """订单成交回调（当前策略使用市价单，无需额外处理）"""
        logger.debug(
            f"[{self.symbol}] 订单更新: {order.get('order_id')} status={order.get('status')}"
        )

    # ═══════════════════════════════════════════════════════════
    # 信号逻辑
    # ═══════════════════════════════════════════════════════════

    async def _process_kline_signal(self):
        """获取已确认 K 线，更新 EMA，检测金叉/死叉并下单"""
        try:
            klines = await self.exchange.get_kline(
                self.symbol, _TIMEFRAME, _KLINE_LIMIT
            )
        except Exception as e:
            logger.error(f"[{self.symbol}] 获取 K 线失败: {e}")
            return

        if not klines or len(klines) < self.slow_period + 2:
            logger.warning(
                f"[{self.symbol}] K 线数据不足: {len(klines) if klines else 0}"
            )
            return

        # OKX 返回最新在前（降序），需反转为升序（最旧在前）供 EMA 使用
        # confirm=='1' 代表已完结 K 线，过滤掉当前未完成的那根
        confirmed = [k for k in reversed(klines) if k.get("confirm") == "1"]
        if len(confirmed) < self.slow_period + 2:
            logger.warning(f"[{self.symbol}] 已确认 K 线数量不足: {len(confirmed)}")
            return

        closes = [float(k["c"]) for k in confirmed]
        self._update_ema_from_closes(closes)

        if self._fast_curr is None or self._slow_curr is None:
            return

        golden = (
            self._fast_prev is not None
            and self._slow_prev is not None
            and self._fast_prev <= self._slow_prev
            and self._fast_curr > self._slow_curr
        )

        death = (
            self._fast_prev is not None
            and self._slow_prev is not None
            and self._fast_prev >= self._slow_prev
            and self._fast_curr < self._slow_curr
        )

        # 用最新 K 线收盘价作为参考价（klines[0] 是最新那根）
        current_price = float(klines[0]["c"])

        logger.debug(
            f"[{self.symbol}] EMA fast={self._fast_curr:.4f} slow={self._slow_curr:.4f} "
            f"golden={golden} death={death} price={current_price:.2f}"
        )

        if golden and not self._in_position:
            if self.use_rsi and self._rsi(closes) >= self.rsi_threshold:
                logger.info(
                    f"[{self.symbol}] 金叉但 RSI 超买({self._rsi(closes):.1f})，跳过开仓"
                )
                return
            await self._open_position(current_price)

        elif death and self._in_position:
            # Fix: 至少持有一根完整 15m K 线后才允许死叉平仓，防止开仓几秒后被信号抖动立即平仓
            min_hold_sec = 15 * 60
            held_sec = time.time() - self._open_time
            if held_sec < min_hold_sec:
                logger.info(
                    f"[{self.symbol}] 死叉信号，但持仓时间仅 {held_sec:.0f}s < {min_hold_sec}s，跳过"
                )
            else:
                await self._close_position(reason="death_cross")

    # ═══════════════════════════════════════════════════════════
    # EMA 计算
    # ═══════════════════════════════════════════════════════════

    def _update_ema_from_closes(self, closes: List[float]):
        """从历史收盘价序列重新计算 EMA，保留最后两个值用于交叉判断"""
        if len(closes) < self.slow_period:
            return

        fast_k = 2 / (self.fast_period + 1)
        slow_k = 2 / (self.slow_period + 1)

        # 用前 slow_period 根做 SMA 初始化
        fast_ema = sum(closes[: self.fast_period]) / self.fast_period
        slow_ema = sum(closes[: self.slow_period]) / self.slow_period

        prev_fast = fast_ema
        prev_slow = slow_ema

        for price in closes[self.slow_period :]:
            prev_fast, fast_ema = fast_ema, (price - fast_ema) * fast_k + fast_ema
            prev_slow, slow_ema = slow_ema, (price - slow_ema) * slow_k + slow_ema

        self._fast_prev = prev_fast
        self._fast_curr = fast_ema
        self._slow_prev = prev_slow
        self._slow_curr = slow_ema

    async def _init_ema(self):
        """启动时用历史 K 线预热 EMA"""
        try:
            klines = await self.exchange.get_kline(
                self.symbol, _TIMEFRAME, _KLINE_LIMIT
            )
            if klines and len(klines) >= self.slow_period + 2:
                # OKX 返回降序，反转为升序；过滤已确认 K 线
                confirmed = [k for k in reversed(klines) if k.get("confirm") == "1"]
                closes = [float(k["c"]) for k in confirmed]
                self._update_ema_from_closes(closes)
                if self._fast_curr and self._slow_curr:
                    logger.info(
                        f"[{self.symbol}] EMA 预热完成: fast={self._fast_curr:.2f} slow={self._slow_curr:.2f}"
                    )
        except Exception as e:
            logger.warning(f"[{self.symbol}] EMA 预热失败（首次 tick 时会重试）: {e}")

    @staticmethod
    def _rsi(closes: List[float], period: int = _RSI_PERIOD) -> float:
        """计算 RSI"""
        if len(closes) < period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(-period, 0):
            d = closes[i] - closes[i - 1]
            (gains if d > 0 else losses).append(abs(d))
        avg_g = sum(gains) / period
        avg_l = sum(losses) / period
        if avg_l == 0:
            return 100.0
        return 100.0 - 100.0 / (1 + avg_g / avg_l)

    # ═══════════════════════════════════════════════════════════
    # 开平仓
    # ═══════════════════════════════════════════════════════════

    async def _open_position(self, price: float):
        """开多仓（市价）"""
        try:
            balance = await self.exchange.get_balance()

            # OKX 余额格式: balance['details'] 是列表，每个元素含 ccy/availBal
            available = 0.0
            for d in balance.get("details", []):
                if d.get("ccy") == "USDT":
                    available = float(d.get("availBal", 0))
                    break

            if available <= 10:
                logger.warning(
                    f"[{self.symbol}] 可用 USDT 余额不足({available:.2f})，跳过开仓"
                )
                return

            # pos_ratio 表示用账户可用资金的 X% 作为保证金
            margin_budget = available * self.pos_ratio

            if self._is_swap:
                # 合约名义价值 = 保证金预算 × 杠杆倍数
                # 合约张数 = 名义价值 ÷ (价格 × 合约面值)
                notional = margin_budget * self.leverage
                contracts = notional / (price * self._ct_val) if self._ct_val > 0 else 1
                qty = max(self._min_sz, int(contracts / self._lot_sz) * self._lot_sz)
            else:
                qty = round(margin_budget / price, 6)

            if qty <= 0:
                logger.warning(
                    f"[{self.symbol}] 计算数量为 0（margin={margin_budget:.2f} price={price:.2f}），跳过"
                )
                return

            logger.info(
                f"[{self.symbol}] 准备开多: qty={qty} "
                f"保证金={margin_budget:.2f} USDT 名义价值={margin_budget * self.leverage:.2f} USDT @ {price:.2f}"
            )

            order = await self.place_order_with_retry(
                side="buy",
                amount=Decimal(str(qty)),
                order_type="market",
            )
            if order:
                self._in_position = True
                self._open_time = time.time()
                # 使用实际成交均价（place_order_with_retry 已查询订单详情）
                avg_px = order.get("avgPx") or order.get("fillPx")
                self._entry_price = (
                    float(avg_px) if avg_px and float(avg_px) > 0 else price
                )
                self._position_qty = qty
                self._buy_count += 1
                # 初始化移动止损
                self._highest_price = self._entry_price
                if self.trailing_stop > 0:
                    self._trail_stop_px = self._entry_price * (1 - self.trailing_stop)
                    logger.info(
                        f"[{self.symbol}] 开多成功 qty={qty} entry={self._entry_price:.2f}"
                        f" 移动止损初始价={self._trail_stop_px:.2f}"
                    )
                else:
                    self._trail_stop_px = 0.0
                    logger.info(
                        f"[{self.symbol}] 开多成功 qty={qty} entry={self._entry_price:.2f}（均价）"
                    )
                # Telegram 开仓通知
                try:
                    await notification_service.notify_position_opened(
                        user_id=self.user_id,
                        strategy_id=self.strategy_id,
                        strategy_name=f"趋势策略#{self.strategy_id}",
                        symbol=self.symbol,
                        side="buy",
                        entry_price=self._entry_price,
                        amount=qty,
                        leverage=self.leverage,
                        margin=margin_budget,
                    )
                except Exception as e:
                    logger.warning(f"[{self.symbol}] 开仓通知发送失败: {e}")
        except Exception as e:
            logger.error(f"[{self.symbol}] 开多失败: {e}")

    async def _close_position(self, reason: str = "signal"):
        """平多仓（市价）"""
        if not self._in_position or self._position_qty <= 0:
            return

        # Fix: 在第一个 await 之前立即清除持仓标志，彻底防止并发重复平仓
        # 若后续下单失败则在 except 里恢复
        saved_entry = self._entry_price
        saved_qty = self._position_qty
        self._in_position = False
        self._entry_price = 0.0
        self._position_qty = 0.0

        try:
            # 查询实际持仓数量（防止因其他原因数量变化）
            qty = saved_qty
            try:
                positions = await self.exchange.get_positions()
                for pos in positions:
                    if (
                        pos.get("symbol") == self.symbol
                        and float(pos.get("size", 0)) > 0
                    ):
                        qty = float(pos["size"])
                        break
            except Exception:
                pass  # 用缓存的 qty

            order = await self.place_order_with_retry(
                side="sell",
                amount=Decimal(str(qty)),
                order_type="market",
            )
            if order:
                close_price = float(
                    order.get("avgPx") or order.get("fillPx") or saved_entry
                )
                ct_val = self._ct_val if self._is_swap else 1.0
                pnl = (close_price - saved_entry) * qty * ct_val
                self._sell_count += 1

                # 更新统计
                self.realized_pnl += pnl
                self.total_trades += 1
                if pnl > 0:
                    self._win_trades += 1
                self.win_rate = self._win_trades / self.total_trades * 100
                self.record_trade_result(pnl)

                logger.info(
                    f"[{self.symbol}] 平多({reason}) qty={qty:.6f} "
                    f"entry={saved_entry:.2f} close={close_price:.2f} "
                    f"pnl={pnl:+.4f} 累计={self.realized_pnl:+.4f}"
                )
                # Telegram 平仓通知
                reason_map = {
                    "stop_loss": "止损平仓",
                    "trailing_stop": "移动止损",
                    "take_profit": "止盈平仓",
                    "death_cross": "死叉平仓",
                    "stop": "手动停止",
                }
                reason_text = reason_map.get(reason, reason)
                pnl_pct = (
                    (close_price - saved_entry) / saved_entry * 100
                    if saved_entry > 0
                    else 0
                )
                try:
                    await notification_service.notify_position_closed(
                        user_id=self.user_id,
                        strategy_id=self.strategy_id,
                        strategy_name=f"趋势策略#{self.strategy_id}",
                        symbol=self.symbol,
                        side="buy",
                        entry_price=saved_entry,
                        exit_price=close_price,
                        amount=qty,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        reason=reason_text,
                    )
                except Exception as e:
                    logger.warning(f"[{self.symbol}] 平仓通知发送失败: {e}")
            else:
                # 下单失败，恢复持仓状态
                logger.error(f"[{self.symbol}] 平仓下单失败，恢复持仓状态")
                self._in_position = True
                self._entry_price = saved_entry
                self._position_qty = saved_qty

        except Exception as e:
            logger.error(f"[{self.symbol}] 平多失败: {e}")
            # 异常时恢复持仓状态，避免持仓丢失
            self._in_position = True
            self._entry_price = saved_entry
            self._position_qty = saved_qty
