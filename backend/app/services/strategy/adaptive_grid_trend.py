"""
自适应趋势网格策略。

设计目标不是“稳赚”，而是把 OKX 交易规则里的几个硬约束落进策略：
- 合约下单前读取 ctVal/lotSz/minSz，按张数下单
- 用 ATR 计算止损距离，再用账户权益的固定风险比例反推仓位
- 趋势过滤通过后，只在回撤到 EMA 附近时入场
- 单仓位运行，不无限补仓，不马丁
"""

from __future__ import annotations

import math
import time
from decimal import Decimal
from typing import Dict, List, Optional

from loguru import logger

from app.core.database import SessionLocal
from app.models.strategy import Strategy as DBStrategy, StrategyEvent
from app.services.notification.notification_service import notification_service
from app.services.strategy.adaptive_grid_trend_config import (
    normalize_adaptive_grid_trend_params,
)
from app.services.strategy.base import StrategyBase


class AdaptiveGridTrendStrategy(StrategyBase):
    """趋势过滤 + ATR 回撤入场 + 固定风险仓位的保守策略。"""

    def __init__(
        self,
        strategy_id: int,
        exchange,
        symbol: str,
        parameters: Dict,
        user_id: int = 1,
    ):
        super().__init__(strategy_id, exchange, symbol, parameters, user_id)

        p = normalize_adaptive_grid_trend_params(parameters)
        self.parameters = p
        self.direction: str = str(p.get("direction", "both")).lower()
        self.timeframe: str = str(p.get("trend_timeframe", p.get("timeframe", "15m")))
        self.fast_period: int = int(p.get("fast_period", 30))
        self.slow_period: int = int(p.get("slow_period", 60))
        self.atr_period: int = int(p.get("atr_period", 14))
        self.entry_atr_multiple: float = float(p.get("entry_atr_multiple", 0.6))
        self.stop_atr_multiple: float = float(p.get("stop_atr_multiple", 2.8))
        self.take_profit_atr_multiple: float = float(
            p.get("take_profit_atr_multiple", 3.2)
        )
        self.risk_per_trade: float = float(p.get("risk_per_trade", 0.02))
        self.max_position_usd: float = float(p.get("max_position_usd", 800))
        self.leverage: int = int(p.get("leverage", 5))
        self.margin_mode: str = str(p.get("margin_mode", "isolated")).lower()
        self.margin_usage_ratio: float = float(p.get("margin_usage_ratio", 0.85))
        self.min_seconds_between_trades: int = int(p.get("cooldown_seconds", 60 * 60))
        self.notify_near_trigger: bool = bool(p.get("notify_near_trigger", True))
        self.near_trigger_pct: float = float(p.get("near_trigger_pct", 0.003))
        self.near_trigger_cooldown_seconds: int = int(
            p.get("near_trigger_cooldown_seconds", 10 * 60)
        )

        self._is_derivative = symbol.endswith("-SWAP") or self._looks_like_futures(
            symbol
        )
        self._ct_val = 1.0
        self._lot_sz = 1.0
        self._min_sz = 1.0
        self._position_mode = "net_mode"
        self._use_pos_side = False

        self._position_side = ""
        self._entry_price = 0.0
        self._position_qty = 0.0
        self._open_time = 0.0
        self._stop_px = 0.0
        self._take_profit_px = 0.0
        self._last_trade_time = 0.0
        self._unrealized_pnl = 0.0
        self._signal_status: Dict = {}
        self._last_event_key = ""
        self._last_event_time = 0.0
        self._last_near_trigger_alerts: Dict[str, float] = {}

        self.realized_pnl = 0.0
        self.total_trades = 0
        self._win_trades = 0
        self.win_rate = 0.0

        logger.info(
            f"AdaptiveGridTrend 初始化: {symbol} tf={self.timeframe} "
            f"fast={self.fast_period} slow={self.slow_period} atr={self.atr_period} "
            f"risk={self.risk_per_trade:.3%} maxPos=${self.max_position_usd}"
        )

    @staticmethod
    def _looks_like_futures(symbol: str) -> bool:
        parts = symbol.split("-")
        return len(parts) >= 3 and parts[-1].isdigit()

    async def start(self):
        self.is_running = True
        await self._restore_position_state()
        await self._init_instrument()
        logger.info(f"策略 {self.strategy_id} [{self.symbol}] 自适应趋势网格已启动")

    async def stop(self, cancel_orders: bool = True, close_position: bool = True):
        self.is_running = False
        if close_position and self._position_side:
            await self._close_position("manual_stop")
        logger.info(f"策略 {self.strategy_id} [{self.symbol}] 自适应趋势网格已停止")

    async def on_tick(self, ticker: Dict):
        if not self.is_running:
            return

        price = float(ticker.get("last") or 0)
        if price <= 0:
            return

        if self._position_side:
            self._signal_status = {
                "trend": "position",
                "waiting_for": "exit",
                "current_price": round(price, 8),
                "position_side": self._position_side,
                "message": f"已有{self._position_side}持仓，等待止盈/止损",
            }
            self._log_signal_event(self._signal_status)
            await self._manage_position(price)
            return

        if time.time() - self._last_trade_time < self.min_seconds_between_trades:
            remaining = max(
                0,
                self.min_seconds_between_trades - (time.time() - self._last_trade_time),
            )
            self._signal_status = {
                "trend": "cooldown",
                "waiting_for": "cooldown",
                "current_price": round(price, 8),
                "cooldown_remaining_seconds": round(remaining),
                "message": f"冷却中，剩余约 {round(remaining / 60)} 分钟",
            }
            self._log_signal_event(self._signal_status)
            return

        metrics = await self._get_metrics()
        if not metrics:
            self._signal_status = {
                "trend": "unknown",
                "waiting_for": "kline_data",
                "current_price": round(price, 8),
                "message": "K线数据不足，等待指标初始化",
            }
            self._log_signal_event(self._signal_status)
            return

        trend = metrics["trend"]
        ema_fast = metrics["ema_fast"]
        atr = metrics["atr"]
        if atr <= 0:
            self._signal_status = {
                "trend": trend,
                "waiting_for": "atr",
                "current_price": round(price, 8),
                "ema_fast": round(ema_fast, 8),
                "ema_slow": round(metrics["ema_slow"], 8),
                "atr": round(atr, 8),
                "message": "ATR无效，等待波动数据",
            }
            self._log_signal_event(self._signal_status)
            return

        long_trigger = ema_fast + atr * self.entry_atr_multiple
        short_trigger = ema_fast - atr * self.entry_atr_multiple
        waiting_for = "flat"
        trigger_price = None
        distance_pct = None
        message = "趋势不明确，等待信号"

        if trend == "bull" and self.direction in ("long", "both"):
            # 上升趋势中等回撤到快线附近，不追高。
            waiting_for = "long"
            trigger_price = long_trigger
            distance_pct = (price - trigger_price) / price * 100 if price > 0 else None
            message = "上升趋势中等待回撤到快线附近，不追高"
            if price <= trigger_price:
                self._signal_status = self._build_signal_status(
                    trend,
                    waiting_for,
                    price,
                    trigger_price,
                    distance_pct,
                    metrics,
                    "多头入场条件已触发，准备开多",
                )
                await self._open_position("long", price, atr)
        elif (
            trend == "bear"
            and self._is_derivative
            and self.direction in ("short", "both")
        ):
            # 下降趋势中反弹到快线附近，不在低位追空。
            waiting_for = "short"
            trigger_price = short_trigger
            distance_pct = (trigger_price - price) / price * 100 if price > 0 else None
            message = "下跌趋势中等待反弹到快线附近，不追空"
            if price >= trigger_price:
                self._signal_status = self._build_signal_status(
                    trend,
                    waiting_for,
                    price,
                    trigger_price,
                    distance_pct,
                    metrics,
                    "空头入场条件已触发，准备开空",
                )
                await self._open_position("short", price, atr)
        else:
            if trend == "bull" and self.direction == "short":
                message = "当前为上升趋势，但策略设置为只做空"
            elif trend == "bear" and self.direction == "long":
                message = "当前为下跌趋势，但策略设置为只做多"
            elif trend == "bear" and not self._is_derivative:
                message = "现货不支持做空，等待多头趋势"

        if not self._position_side:
            self._signal_status = self._build_signal_status(
                trend, waiting_for, price, trigger_price, distance_pct, metrics, message
            )
            self._log_signal_event(self._signal_status)

    async def on_kline(self, kline: Dict):
        return None

    async def on_order_update(self, order: Dict):
        logger.debug(f"[{self.symbol}] 订单更新: {order}")

    def _build_signal_status(
        self,
        trend: str,
        waiting_for: str,
        price: float,
        trigger_price: Optional[float],
        distance_pct: Optional[float],
        metrics: Dict,
        message: str,
    ) -> Dict:
        return {
            "trend": trend,
            "waiting_for": waiting_for,
            "current_price": round(price, 8),
            "trigger_price": (
                round(trigger_price, 8) if trigger_price is not None else None
            ),
            "distance_pct": (
                round(distance_pct, 4) if distance_pct is not None else None
            ),
            "ema_fast": round(metrics.get("ema_fast", 0), 8),
            "ema_slow": round(metrics.get("ema_slow", 0), 8),
            "atr": round(metrics.get("atr", 0), 8),
            "message": message,
        }

    def get_signal_status(self) -> Dict:
        return self._signal_status or {
            "trend": "unknown",
            "waiting_for": "tick",
            "message": "等待下一次行情检查",
        }

    def _log_event(
        self,
        event_type: str,
        title: str,
        message: str,
        level: str = "info",
        data: Optional[Dict] = None,
    ) -> None:
        db = SessionLocal()
        try:
            db.add(
                StrategyEvent(
                    strategy_id=self.strategy_id,
                    user_id=self.user_id,
                    event_type=event_type,
                    level=level,
                    title=title,
                    message=message,
                    data=data or {},
                    parameter_snapshot=(
                        self.parameters if isinstance(self.parameters, dict) else None
                    ),
                )
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.debug(f"[{self.symbol}] 写入策略事件失败: {exc}")
        finally:
            db.close()

    def _log_signal_event(self, status: Dict) -> None:
        key = (
            f"{status.get('trend')}|{status.get('waiting_for')}|{status.get('message')}"
        )
        now = time.time()
        if key == self._last_event_key and now - self._last_event_time < 15 * 60:
            return
        self._last_event_key = key
        self._last_event_time = now
        self._log_event(
            event_type="signal",
            title="策略信号更新",
            message=status.get("message") or "",
            data=status,
        )

    async def _restore_position_state(self):
        db = SessionLocal()
        try:
            db_s = (
                db.query(DBStrategy).filter(DBStrategy.id == self.strategy_id).first()
            )
            if db_s and db_s.position_in_position:
                self._position_side = db_s.position_side or ""
                self._entry_price = float(db_s.position_entry_price or 0)
                self._position_qty = float(db_s.position_qty or 0)
                self._open_time = float(db_s.position_open_time or 0)
                logger.warning(
                    f"[{self.symbol}] 恢复持仓: side={self._position_side} "
                    f"qty={self._position_qty} entry={self._entry_price}"
                )
        finally:
            db.close()

    async def _init_instrument(self):
        info = await self.exchange.get_instrument(self.symbol)
        self._is_derivative = info.get("instType") in {"SWAP", "FUTURES", "OPTION"}
        self._ct_val = float(info.get("ctVal") or self._ct_val)
        self._lot_sz = float(info.get("lotSz") or self._lot_sz)
        self._min_sz = float(info.get("minSz") or self._min_sz)

        if self._is_derivative:
            await self._init_position_mode()
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
            except Exception as exc:
                logger.warning(f"[{self.symbol}] 设置杠杆失败，继续运行: {exc}")

        logger.info(
            f"[{self.symbol}] 产品规格: derivative={self._is_derivative} "
            f"ctVal={self._ct_val} lotSz={self._lot_sz} minSz={self._min_sz} "
            f"posMode={self._position_mode}"
        )

    async def _init_position_mode(self):
        try:
            config = await self.exchange.get_account_config()
            self._position_mode = config.get("posMode") or "net_mode"
        except Exception as exc:
            logger.warning(
                f"[{self.symbol}] 获取持仓模式失败，按 net_mode 兼容下单: {exc}"
            )
            self._position_mode = "net_mode"

        if self._position_mode != "long_short_mode":
            try:
                await self.exchange.set_position_mode("long_short_mode")
                self._position_mode = "long_short_mode"
                logger.info(
                    f"[{self.symbol}] 持仓模式已设置为双向持仓 (long_short_mode)"
                )
            except Exception as exc:
                logger.warning(
                    f"[{self.symbol}] 无法切换双向持仓，使用当前 net_mode 下单；"
                    f"如果需要同时多空，请先在 OKX 平掉持仓/挂单后手动切换: {exc}"
                )

        self._use_pos_side = self._position_mode == "long_short_mode"

    async def _get_metrics(self) -> Optional[Dict]:
        limit = max(self.slow_period + self.atr_period + 10, 100)
        klines = await self.exchange.get_kline(self.symbol, self.timeframe, limit)
        confirmed = [k for k in reversed(klines) if k.get("confirm") == "1"]
        if len(confirmed) < self.slow_period + self.atr_period:
            return None

        closes = [float(k["c"]) for k in confirmed]
        highs = [float(k["h"]) for k in confirmed]
        lows = [float(k["l"]) for k in confirmed]
        ema_fast = self._ema(closes, self.fast_period)
        ema_slow = self._ema(closes, self.slow_period)
        atr = self._atr(highs, lows, closes, self.atr_period)

        if ema_fast > ema_slow:
            trend = "bull"
        elif ema_fast < ema_slow:
            trend = "bear"
        else:
            trend = "flat"

        return {"trend": trend, "ema_fast": ema_fast, "ema_slow": ema_slow, "atr": atr}

    @staticmethod
    def _ema(values: List[float], period: int) -> float:
        alpha = 2 / (period + 1)
        ema = values[0]
        for value in values[1:]:
            ema = value * alpha + ema * (1 - alpha)
        return ema

    @staticmethod
    def _atr(
        highs: List[float], lows: List[float], closes: List[float], period: int
    ) -> float:
        true_ranges = []
        for i in range(1, len(closes)):
            true_ranges.append(
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )
            )
        recent = true_ranges[-period:]
        return sum(recent) / len(recent) if recent else 0.0

    async def _account_equity_usd(self) -> float:
        funds = await self._account_funds_usd()
        return funds["equity"]

    async def _account_funds_usd(self) -> Dict[str, float]:
        balance = await self.exchange.get_balance()
        total = float(balance.get("totalEq") or 0)
        details = balance.get("details", [])
        usdt = next((d for d in details if d.get("ccy") == "USDT"), None)
        available = float((usdt or {}).get("availBal") or 0)
        if total > 0:
            return {"equity": total, "available_usdt": available}
        return {"equity": available, "available_usdt": available}

    def _round_qty(self, qty: float) -> float:
        if qty <= 0:
            return 0.0
        steps = math.floor(qty / self._lot_sz)
        rounded = steps * self._lot_sz
        if rounded < self._min_sz:
            return 0.0
        return round(rounded, 8)

    async def _calc_qty(self, price: float, atr: float) -> float:
        funds = await self._account_funds_usd()
        equity = funds["equity"]
        available_usdt = funds["available_usdt"]
        stop_distance = max(atr * self.stop_atr_multiple, price * 0.002)
        risk_capital = min(equity * self.risk_per_trade, self.max_position_usd * 0.05)

        if self._is_derivative:
            qty_by_risk = risk_capital / (stop_distance * self._ct_val)
            qty_by_cap = self.max_position_usd / (price * self._ct_val)
            usable_margin = max(0.0, available_usdt * self.margin_usage_ratio)
            qty_by_margin = (usable_margin * max(self.leverage, 1)) / (
                price * self._ct_val
            )
            qty = self._round_qty(min(qty_by_risk, qty_by_cap, qty_by_margin))
            if qty <= 0:
                logger.warning(
                    f"[{self.symbol}] 可用保证金不足，跳过开仓: "
                    f"available_usdt={available_usdt:.4f}, price={price:.8f}, "
                    f"ctVal={self._ct_val}, lotSz={self._lot_sz}, minSz={self._min_sz}"
                )
            return qty

        qty_by_risk = risk_capital / stop_distance
        qty_by_cap = self.max_position_usd / price
        qty_by_available = (available_usdt * self.margin_usage_ratio) / price
        return self._round_qty(min(qty_by_risk, qty_by_cap, qty_by_available))

    async def _open_position(self, side: str, price: float, atr: float):
        qty = await self._calc_qty(price, atr)
        if qty <= 0:
            logger.warning(f"[{self.symbol}] 计算仓位过小，跳过开仓")
            return

        order_side = "buy" if side == "long" else "sell"
        pos_side = self._order_pos_side(side)
        td_mode = self.margin_mode if self._is_derivative else "cash"

        order = await self.exchange.create_order(
            symbol=self.symbol,
            side=order_side,
            order_type="market",
            amount=Decimal(str(qty)),
            td_mode=td_mode,
            pos_side=pos_side,
        )
        order_detail = await self._load_order_detail(order)
        fill_price = float(order_detail.get("avgPx") or price)

        await self._save_order_to_db(
            order_detail, order_side, "market", None, Decimal(str(qty))
        )

        self._position_side = side
        self._entry_price = fill_price
        self._position_qty = qty
        self._open_time = time.time()
        self._last_trade_time = self._open_time
        self._last_near_trigger_alerts.clear()
        if side == "long":
            self._stop_px = fill_price - atr * self.stop_atr_multiple
            self._take_profit_px = fill_price + atr * self.take_profit_atr_multiple
        else:
            self._stop_px = fill_price + atr * self.stop_atr_multiple
            self._take_profit_px = fill_price - atr * self.take_profit_atr_multiple

        logger.info(
            f"[{self.symbol}] 开{side}: qty={qty} entry={fill_price:.6f} "
            f"stop={self._stop_px:.6f} tp={self._take_profit_px:.6f}"
        )
        self._log_event(
            event_type="open_position",
            level="success",
            title=f"开{side}仓成功",
            message=f"开仓价 {fill_price:.6f}，止损 {self._stop_px:.6f}，止盈 {self._take_profit_px:.6f}",
            data={
                "symbol": self.symbol,
                "side": side,
                "qty": qty,
                "entry_price": fill_price,
                "stop_px": self._stop_px,
                "take_profit_px": self._take_profit_px,
                "atr": atr,
                "order_id": order_detail.get("ordId"),
            },
        )

    async def _manage_position(self, price: float):
        if self._stop_px <= 0 or self._take_profit_px <= 0:
            if not await self._rebuild_risk_levels():
                logger.warning(
                    f"[{self.symbol}] 持仓风控价缺失且无法重建，暂停本轮管理"
                )
                return

        if self._position_side == "long":
            pnl = (price - self._entry_price) * self._position_qty
            if self._is_derivative:
                pnl *= self._ct_val
            self._unrealized_pnl = pnl
            await self._notify_near_exit_trigger(price)
            if price <= self._stop_px:
                await self._close_position("atr_stop")
            elif price >= self._take_profit_px:
                await self._close_position("atr_take_profit")
        elif self._position_side == "short":
            pnl = (self._entry_price - price) * self._position_qty
            if self._is_derivative:
                pnl *= self._ct_val
            self._unrealized_pnl = pnl
            await self._notify_near_exit_trigger(price)
            if price >= self._stop_px:
                await self._close_position("atr_stop")
            elif price <= self._take_profit_px:
                await self._close_position("atr_take_profit")

    async def _notify_near_exit_trigger(self, price: float):
        if (
            not self.notify_near_trigger
            or price <= 0
            or not self._position_side
            or self._stop_px <= 0
            or self._take_profit_px <= 0
            or self.near_trigger_pct <= 0
        ):
            return

        if self._position_side == "long":
            stop_distance_pct = (price - self._stop_px) / price
            tp_distance_pct = (self._take_profit_px - price) / price
        else:
            stop_distance_pct = (self._stop_px - price) / price
            tp_distance_pct = (price - self._take_profit_px) / price

        checks = [
            ("stop", "止损", self._stop_px, stop_distance_pct, "warning"),
            ("take_profit", "止盈", self._take_profit_px, tp_distance_pct, "success"),
        ]
        for trigger_key, trigger_name, trigger_price, distance_pct, level in checks:
            if distance_pct < 0 or distance_pct > self.near_trigger_pct:
                continue
            alert_key = f"{self._position_side}:{trigger_key}"
            if not self._can_send_near_trigger_alert(alert_key):
                continue

            distance_text = f"{distance_pct * 100:.3f}%"
            title = f"{self.symbol} 快触发{trigger_name}"
            message = (
                f"{self.symbol} {self._position_side} 当前价 {price:.6f}，"
                f"{trigger_name}价 {trigger_price:.6f}，距离 {distance_text}"
            )
            data = {
                "symbol": self.symbol,
                "side": self._position_side,
                "current_price": round(price, 8),
                "trigger": trigger_name,
                "trigger_price": round(trigger_price, 8),
                "distance_pct": distance_text,
                "entry_price": round(self._entry_price, 8),
                "qty": self._position_qty,
                "unrealized_pnl": round(self._unrealized_pnl, 4),
            }
            await notification_service.send_strategy_notification(
                strategy_id=self.strategy_id,
                title=title,
                message=message,
                level=level,
                data=data,
            )
            self._log_event(
                event_type="near_exit_trigger",
                level=level,
                title=title,
                message=message,
                data=data,
            )

    def _can_send_near_trigger_alert(self, alert_key: str) -> bool:
        now = time.time()
        last_sent = self._last_near_trigger_alerts.get(alert_key, 0)
        if now - last_sent < self.near_trigger_cooldown_seconds:
            return False
        self._last_near_trigger_alerts[alert_key] = now
        return True

    async def _rebuild_risk_levels(self) -> bool:
        if not self._position_side or self._entry_price <= 0:
            return False

        metrics = await self._get_metrics()
        if not metrics or metrics["atr"] <= 0:
            return False

        atr = metrics["atr"]
        if self._position_side == "long":
            self._stop_px = self._entry_price - atr * self.stop_atr_multiple
            self._take_profit_px = (
                self._entry_price + atr * self.take_profit_atr_multiple
            )
        else:
            self._stop_px = self._entry_price + atr * self.stop_atr_multiple
            self._take_profit_px = (
                self._entry_price - atr * self.take_profit_atr_multiple
            )

        logger.warning(
            f"[{self.symbol}] 重建持仓风控价: side={self._position_side} "
            f"entry={self._entry_price:.6f} stop={self._stop_px:.6f} tp={self._take_profit_px:.6f}"
        )
        return True

    async def _close_position(self, reason: str):
        side = "sell" if self._position_side == "long" else "buy"
        pos_side = self._order_pos_side(self._position_side)
        td_mode = self.margin_mode if self._is_derivative else "cash"

        order = await self.exchange.create_order(
            symbol=self.symbol,
            side=side,
            order_type="market",
            amount=Decimal(str(self._position_qty)),
            td_mode=td_mode,
            pos_side=pos_side,
            reduce_only=self._is_derivative,
        )
        order_detail = await self._load_order_detail(order)
        exit_price = float(order_detail.get("avgPx") or 0)
        if exit_price <= 0:
            exit_price = (
                self._take_profit_px
                if reason.endswith("take_profit")
                else self._stop_px
            )

        pnl = (exit_price - self._entry_price) * self._position_qty
        if self._position_side == "short":
            pnl = -pnl
        if self._is_derivative:
            pnl *= self._ct_val

        await self._save_order_to_db(
            order_detail, side, "market", None, Decimal(str(self._position_qty))
        )
        self.realized_pnl += pnl
        self.total_trades += 1
        if pnl > 0:
            self._win_trades += 1
        self.win_rate = (
            self._win_trades / self.total_trades * 100 if self.total_trades else 0
        )
        self.record_trade_result(pnl)

        logger.info(
            f"[{self.symbol}] 平仓({reason}): exit={exit_price:.6f} pnl={pnl:.4f}"
        )
        self._log_event(
            event_type="close_position",
            level="success" if pnl >= 0 else "warning",
            title="平仓完成",
            message=f"{reason}: 平仓价 {exit_price:.6f}，盈亏 {pnl:.4f} USDT",
            data={
                "symbol": self.symbol,
                "reason": reason,
                "side": self._position_side,
                "entry_price": self._entry_price,
                "exit_price": exit_price,
                "qty": self._position_qty,
                "pnl": pnl,
                "order_id": order_detail.get("ordId"),
            },
        )

        self._position_side = ""
        self._entry_price = 0.0
        self._position_qty = 0.0
        self._open_time = 0.0
        self._stop_px = 0.0
        self._take_profit_px = 0.0
        self._last_trade_time = time.time()
        self._unrealized_pnl = 0.0
        self._last_near_trigger_alerts.clear()

    def _order_pos_side(self, side: str) -> Optional[str]:
        if not self._is_derivative:
            return None
        return side if self._use_pos_side else "net"

    async def _load_order_detail(self, order: Dict) -> Dict:
        order_id = order.get("ordId")
        if not order_id:
            return order
        try:
            import asyncio

            await asyncio.sleep(0.8)
            return await self.exchange.get_order(self.symbol, order_id=order_id)
        except Exception as exc:
            logger.warning(f"[{self.symbol}] 查询订单详情失败，使用下单返回: {exc}")
            return order

    async def calculate_pnl(self) -> Dict:
        exchange_position = await self._get_exchange_position_pnl()
        if exchange_position:
            self._unrealized_pnl = exchange_position["unrealized_pnl"]
            self._position_qty = exchange_position["qty"] or self._position_qty
            self._entry_price = exchange_position["entry_price"] or self._entry_price
            if not self._position_side:
                self._position_side = exchange_position["side"]

        in_position = bool(self._position_side)
        return {
            "total_pnl": self.realized_pnl + self._unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self._unrealized_pnl,
            "total_trades": self.total_trades,
            "total_orders": self.total_trades * 2 + (1 if in_position else 0),
            "buy_count": self.total_trades,
            "sell_count": self.total_trades,
            "win_rate": self.win_rate,
            "in_position": in_position,
            "position_side": self._position_side,
            "entry_price": self._entry_price,
            "position_qty": self._position_qty,
            "stop_px": self._stop_px,
            "take_profit_px": self._take_profit_px,
            "exchange_position": exchange_position,
        }

    async def _get_exchange_position_pnl(self) -> Optional[Dict]:
        """优先使用 OKX 官方持仓 upl，避免合约张数/ctVal/标记价口径不一致。"""
        try:
            positions = await self.exchange.get_positions(inst_id=self.symbol)
        except Exception as exc:
            logger.debug(
                f"[{self.symbol}] 获取交易所持仓盈亏失败，使用策略内存估算: {exc}"
            )
            return None

        def as_float(value, default=0.0) -> float:
            try:
                if value in (None, ""):
                    return default
                return float(value)
            except (TypeError, ValueError):
                return default

        expected_side = self._position_side
        for pos in positions:
            qty = as_float(pos.get("pos"))
            if qty == 0:
                continue
            pos_side = pos.get("posSide") or "net"
            side = (
                pos_side
                if pos_side in ("long", "short")
                else ("long" if qty > 0 else "short")
            )
            if expected_side and side != expected_side:
                continue

            return {
                "side": side,
                "qty": abs(qty),
                "entry_price": as_float(pos.get("avgPx")),
                "mark_price": as_float(pos.get("markPx") or pos.get("last")),
                "unrealized_pnl": as_float(pos.get("upl")),
                "unrealized_pnl_pct": as_float(pos.get("uplRatio")) * 100,
                "notional_usd": as_float(pos.get("notionalUsd")),
                "margin": as_float(pos.get("margin")),
                "leverage": as_float(pos.get("lever")),
                "pos_side": pos_side,
            }

        return None
