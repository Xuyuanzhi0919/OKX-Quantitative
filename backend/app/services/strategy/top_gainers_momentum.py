"""
涨幅榜前三短线动量实盘策略。

策略动态跟踪 OKX USDT 永续 24h 涨幅榜前 N 名，用 15m/5m EMA 动量信号做多。
这是高风险策略，默认使用逐仓、单仓位、小名义金额和运行期熔断。
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional

from loguru import logger

from app.core.database import SessionLocal
from app.models.strategy import StrategyEvent
from app.services.backtest.top_gainers_momentum import (
    EXCLUDED_SYMBOLS,
    TopGainersMomentumAnalyzer,
)
from app.services.strategy.base import StrategyBase


@dataclass
class MomentumPosition:
    symbol: str
    side: str
    qty: float
    entry_price: float
    stop_px: float
    take_profit_px: float
    open_time: float
    ct_val: float
    highest_price: float
    current_price: float
    lowest_price: float


class TopGainersMomentumStrategy(StrategyBase):
    """动态涨幅榜 + EMA 动量 + ATR 风控的多币种实盘执行器。"""

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

        self.timeframe = str(p.get("timeframe", "15m"))
        if self.timeframe not in {"15m", "5m"}:
            self.timeframe = "15m"
        self.top_n = max(1, min(int(p.get("top_n", 3)), 10))
        self.direction = str(p.get("direction", "both")).lower()
        if self.direction not in {"long", "short", "both"}:
            self.direction = "both"
        self.loop_interval_seconds = max(15, int(p.get("loop_interval_seconds", 60)))
        self.margin_mode = str(p.get("margin_mode", "isolated")).lower()
        if self.margin_mode not in {"isolated", "cross"}:
            self.margin_mode = "isolated"

        defaults = TopGainersMomentumAnalyzer._params(self.timeframe)
        self.risk_per_trade = float(p.get("risk_per_trade", defaults["risk_pct"]))
        self.max_leverage = int(p.get("max_leverage", defaults["max_leverage"]))
        self.stop_atr = float(p.get("stop_atr", defaults["stop_atr"]))
        self.take_profit_r = float(p.get("take_profit_r", defaults["take_profit_r"]))
        self.trailing_atr = float(p.get("trailing_atr", defaults["trailing_atr"]))
        self.max_hold_bars = int(p.get("max_hold_bars", defaults["max_hold_bars"]))

        self.max_position_usd = float(p.get("max_position_usd", 300))
        self.max_total_position_usd = float(
            p.get("max_total_position_usd", self.max_position_usd)
        )
        self.max_open_positions = max(1, min(int(p.get("max_open_positions", 1)), 3))
        self.cooldown_seconds = max(0, int(p.get("cooldown_seconds", 15 * 60)))
        self.min_24h_change_pct = float(p.get("min_24h_change_pct", 0))
        self.close_when_out_of_top = bool(p.get("close_when_out_of_top", False))
        self.observe_first_scan = bool(p.get("observe_first_scan", True))
        self.use_attached_tp_sl = bool(p.get("use_attached_tp_sl", True))

        # 固定百分比止盈止损模式（与 ATR 动态止损二选一）
        self.use_fixed_pct = bool(p.get("use_fixed_pct", False))
        self.fixed_sl_pct = float(p.get("fixed_sl_pct", 1.0))  # 止损百分比，默认1%
        self.fixed_tp_pct = float(p.get("fixed_tp_pct", 1.0))  # 止盈百分比，默认1%

        self.positions: Dict[str, MomentumPosition] = {}
        self._self_driven = True
        self._has_completed_first_scan = False
        self._instrument_cache: Dict[str, Dict[str, float]] = {}
        self._last_trade_at: Dict[str, float] = {}
        self._runner_task: Optional[asyncio.Task] = None
        self._signal_status: Dict = {}
        self._last_event_key = ""
        self._last_event_time = 0.0
        self.realized_pnl = 0.0
        self.total_trades = 0
        self._win_trades = 0
        self.win_rate = 0.0

    async def start(self):
        self.is_running = True
        self._runner_task = asyncio.create_task(self._run_loop())
        logger.info(
            f"策略 {self.strategy_id} 涨幅榜动量已启动: tf={self.timeframe} "
            f"top_n={self.top_n} direction={self.direction} "
            f"max_position=${self.max_position_usd} leverage={self.max_leverage}x"
        )

    async def stop(self, cancel_orders: bool = True, close_position: bool = False):
        self.is_running = False
        if self._runner_task:
            self._runner_task.cancel()
            try:
                await self._runner_task
            except asyncio.CancelledError:
                pass
            self._runner_task = None
        if close_position:
            for symbol in list(self.positions.keys()):
                await self._close_position(symbol, "manual_stop")
        logger.info(f"策略 {self.strategy_id} 涨幅榜动量已停止")

    async def on_tick(self, ticker: Dict):
        return None

    async def on_kline(self, kline: Dict):
        return None

    async def on_order_update(self, order: Dict):
        logger.debug(f"[TopGainersMomentum] 订单更新: {order}")

    async def _run_loop(self):
        while self.is_running:
            try:
                await self._scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error_at = time.time()
                self.last_error_message = str(exc)
                logger.error(f"涨幅榜动量循环异常: {exc}")
                self._log_event(
                    event_type="runtime_error",
                    title="涨幅榜动量循环异常",
                    message=str(exc),
                    level="error",
                )
            await asyncio.sleep(self.loop_interval_seconds)

    async def _scan_once(self):
        tickers = await self.exchange.get_tickers("SWAP")
        top_gainers = self._top_usdt_swap_gainers(tickers)
        top_symbols = {item["symbol"] for item in top_gainers}
        latest_signal = (
            self._signal_status if isinstance(self._signal_status, dict) else {}
        )

        for symbol in list(self.positions.keys()):
            ticker = next(
                (item for item in top_gainers if item["symbol"] == symbol), None
            )
            if ticker is None:
                try:
                    raw_ticker = await self.exchange.get_ticker(symbol)
                    last = self._safe_float(raw_ticker.get("last"))
                except Exception:
                    last = 0.0
                await self._manage_position(symbol, last, out_of_top=True)
            else:
                await self._manage_position(symbol, ticker["last"], out_of_top=False)

        for item in top_gainers:
            if len(self.positions) >= self.max_open_positions:
                break
            symbol = item["symbol"]
            if symbol in self.positions:
                continue
            if item["change_24h_pct"] < self.min_24h_change_pct:
                continue
            if (
                time.time() - self._last_trade_at.get(symbol, 0.0)
                < self.cooldown_seconds
            ):
                continue

            candles = await self._load_candles(symbol)
            if len(candles) < 90:
                continue
            signal = self._signal(candles)
            self._update_signal_status(symbol, item, signal)
            latest_signal = self._signal_status
            if self.observe_first_scan and not self._has_completed_first_scan:
                continue
            if signal["action"] not in {"small_entry", "watch_or_small_entry"}:
                continue
            await self._open_position(symbol, signal)

        self._has_completed_first_scan = True
        self._signal_status = {
            "top_symbols": list(top_symbols),
            "direction": self.direction,
            "observe_first_scan": self.observe_first_scan,
            "symbol": latest_signal.get("symbol"),
            "status": latest_signal.get("status"),
            "action": latest_signal.get("action"),
            "side": latest_signal.get("side"),
            "last": latest_signal.get("last"),
            "rsi": latest_signal.get("rsi"),
            "atr_pct": latest_signal.get("atr_pct"),
            "open_positions": {
                symbol: {
                    "side": pos.side,
                    "qty": pos.qty,
                    "entry_price": pos.entry_price,
                    "stop_px": pos.stop_px,
                    "take_profit_px": pos.take_profit_px,
                    "highest_price": pos.highest_price,
                    "lowest_price": pos.lowest_price,
                    "current_price": pos.current_price,
                }
                for symbol, pos in self.positions.items()
            },
            "message": f"已扫描涨幅榜前{self.top_n}，持仓 {len(self.positions)} 个",
        }

    def _top_usdt_swap_gainers(self, tickers: List[Dict]) -> List[Dict]:
        gainers = []
        for ticker in tickers:
            symbol = str(ticker.get("instId") or "")
            if not symbol.endswith("-USDT-SWAP") or symbol in EXCLUDED_SYMBOLS:
                continue
            last = self._safe_float(ticker.get("last"))
            open_24h = self._safe_float(ticker.get("open24h"))
            if last <= 0 or open_24h <= 0:
                continue
            gainers.append(
                {
                    "symbol": symbol,
                    "last": last,
                    "change_24h_pct": (last - open_24h) / open_24h * 100,
                    "volume_24h": self._safe_float(
                        ticker.get("volCcy24h") or ticker.get("vol24h")
                    ),
                }
            )
        gainers.sort(key=lambda item: item["change_24h_pct"], reverse=True)
        return gainers[: self.top_n]

    async def _load_candles(self, symbol: str) -> List[Dict]:
        raw = await self.exchange.get_kline(symbol, self.timeframe, limit=220)
        candles = [
            {
                "ts": int(item["ts"]),
                "high": float(item["h"]),
                "low": float(item["l"]),
                "close": float(item["c"]),
            }
            for item in raw
            if str(item.get("confirm", "1")) == "1"
        ]
        return sorted(candles, key=lambda candle: candle["ts"])

    def _signal(self, candles: List[Dict]) -> Dict:
        high = [c["high"] for c in candles]
        low = [c["low"] for c in candles]
        close = [c["close"] for c in candles]
        e5 = self._ema(close, 5)
        e9 = self._ema(close, 9)
        e21 = self._ema(close, 21)
        e55 = self._ema(close, 55)
        e144 = self._ema(close, 144 if len(close) > 180 else 89)
        atr = self._atr(high, low, close)
        rsi = self._rsi(close)
        i = len(close) - 1

        long_trend = close[i] > e55[i] and e9[i] > e21[i]
        short_trend = close[i] < e55[i] and e9[i] < e21[i]
        major = close[i] > e144[i] if len(close) > 160 else True
        short_major = close[i] < e144[i] if len(close) > 160 else True
        cross = e5[i - 1] <= e9[i - 1] and e5[i] > e9[i]
        short_cross = e5[i - 1] >= e9[i - 1] and e5[i] < e9[i]
        recent_cross = any(
            e5[j - 1] <= e9[j - 1] and e5[j] > e9[j]
            for j in range(max(1, i - 3), i + 1)
        )
        recent_short_cross = any(
            e5[j - 1] >= e9[j - 1] and e5[j] < e9[j]
            for j in range(max(1, i - 3), i + 1)
        )
        dist_e21_pct = (close[i] - e21[i]) / close[i] * 100
        near_e21_pct = abs(dist_e21_pct)
        overheat = rsi[i] > 74 or dist_e21_pct > 2.5
        atr_pct = atr[i] / close[i] * 100
        atr_ok = 0.2 <= atr_pct <= 8

        side = "none"
        short_reversal = (
            overheat and close[i] < e9[i] and e5[i] < e9[i] and rsi[i] >= 55
        )

        if (
            self.direction in {"short", "both"}
            and atr_ok
            and (
                (short_trend and short_major and short_cross and 28 <= rsi[i] <= 60)
                or short_reversal
            )
        ):
            side = "short"
            action = "small_entry"
            status = "空头触发"
        elif (
            self.direction in {"short", "both"}
            and atr_ok
            and short_trend
            and short_major
            and recent_short_cross
            and 28 <= rsi[i] <= 64
        ):
            side = "short"
            action = "watch_or_small_entry"
            status = "空头刚触发"
        elif (
            self.direction in {"long", "both"}
            and long_trend
            and major
            and cross
            and 45 <= rsi[i] <= 74
            and atr_ok
        ):
            side = "long"
            action = "small_entry"
            status = "多头触发"
        elif (
            self.direction in {"long", "both"}
            and long_trend
            and major
            and recent_cross
            and 45 <= rsi[i] <= 74
            and atr_ok
        ):
            side = "long"
            action = "watch_or_small_entry"
            status = "多头刚触发"
        elif long_trend and major and near_e21_pct < 0.8 and rsi[i] <= 70:
            action = "wait"
            status = "等回踩/上穿"
        elif long_trend and major and overheat:
            action = "wait_pullback"
            status = "过热等回踩"
        else:
            action = "skip"
            status = "暂缓"

        if self.use_fixed_pct:
            if side == "short":
                stop = close[i] * (1 + self.fixed_sl_pct / 100)
                take_profit = close[i] * (1 - self.fixed_tp_pct / 100)
            else:
                stop = close[i] * (1 - self.fixed_sl_pct / 100)
                take_profit = close[i] * (1 + self.fixed_tp_pct / 100)
        elif side == "short":
            stop = close[i] + self.stop_atr * atr[i]
            risk = stop - close[i]
            take_profit = close[i] - self.take_profit_r * risk
        else:
            stop = close[i] - self.stop_atr * atr[i]
            risk = close[i] - stop
            take_profit = close[i] + self.take_profit_r * risk
        return {
            "action": action,
            "side": side,
            "status": status,
            "last": close[i],
            "atr": atr[i],
            "atr_pct": atr_pct,
            "rsi": rsi[i],
            "dist_e21_pct": dist_e21_pct,
            "stop": stop,
            "take_profit": take_profit,
            "last_candle_ts": candles[-1]["ts"],
        }

    async def _open_position(self, symbol: str, signal: Dict):
        info = await self._instrument(symbol)
        price = float(signal["last"])
        atr = float(signal["atr"])
        side = str(signal.get("side") or "long")
        if side not in {"long", "short"}:
            return
        qty = await self._calc_contract_qty(symbol, price, atr, info)
        if qty <= 0:
            return

        await self._ensure_leverage(symbol, side)
        stop_px, take_profit_px = self._risk_prices(price, atr, side)
        order_side = "buy" if side == "long" else "sell"
        order = await self.exchange.create_order(
            symbol=symbol,
            side=order_side,
            order_type="market",
            amount=Decimal(str(qty)),
            td_mode=self.margin_mode,
            pos_side=await self._pos_side(side),
            attach_algo_ords=(
                self._attached_tp_sl(take_profit_px, stop_px)
                if self.use_attached_tp_sl
                else None
            ),
        )
        detail = await self._load_order_detail(symbol, order)
        fill_price = self._safe_float(detail.get("avgPx")) or price
        stop_px, take_profit_px = self._risk_prices(fill_price, atr, side)
        self.positions[symbol] = MomentumPosition(
            symbol=symbol,
            side=side,
            qty=qty,
            entry_price=fill_price,
            stop_px=stop_px,
            take_profit_px=take_profit_px,
            open_time=time.time(),
            ct_val=info["ct_val"],
            highest_price=fill_price,
            current_price=fill_price,
            lowest_price=fill_price,
        )
        self._last_trade_at[symbol] = time.time()
        await self._save_symbol_order_to_db(
            symbol, detail, order_side, "market", None, Decimal(str(qty))
        )
        self._log_event(
            event_type="open_position",
            title=f"涨幅榜动量开{side}",
            message=f"{symbol} 开{side} {qty} 张，入场 {fill_price:.8f}",
            level="success",
            data={
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "entry": fill_price,
                "stop": stop_px,
                "take_profit": take_profit_px,
            },
        )

    async def _manage_position(self, symbol: str, price: float, out_of_top: bool):
        pos = self.positions.get(symbol)
        if not pos or price <= 0:
            return

        candles = await self._load_candles(symbol)
        atr = self._signal(candles)["atr"] if len(candles) >= 90 else 0.0
        pos.current_price = price
        pos.highest_price = max(pos.highest_price, price)
        pos.lowest_price = min(pos.lowest_price, price)
        if not self.use_fixed_pct:
            if atr > 0 and pos.side == "long" and price > pos.entry_price:
                pos.stop_px = max(pos.stop_px, price - self.trailing_atr * atr)
            elif atr > 0 and pos.side == "short" and price < pos.entry_price:
                pos.stop_px = min(pos.stop_px, price + self.trailing_atr * atr)

        self._unrealized_pnl = sum(
            self._position_pnl(p) for p in self.positions.values()
        )

        elapsed_bars = (time.time() - pos.open_time) / self._timeframe_seconds()
        close_reason = None
        if pos.side == "long":
            if price <= pos.stop_px:
                close_reason = "atr_stop"
            elif price >= pos.take_profit_px:
                close_reason = "take_profit"
        else:
            if price >= pos.stop_px:
                close_reason = "atr_stop"
            elif price <= pos.take_profit_px:
                close_reason = "take_profit"
        if close_reason is None and elapsed_bars >= self.max_hold_bars:
            close_reason = "time_exit"
        if close_reason is None and out_of_top and self.close_when_out_of_top:
            close_reason = "out_of_top"
        if close_reason:
            await self._close_position(symbol, close_reason)

    async def _close_position(self, symbol: str, reason: str):
        pos = self.positions.get(symbol)
        if not pos:
            return

        order_side = "sell" if pos.side == "long" else "buy"
        try:
            order = await self.exchange.create_order(
                symbol=symbol,
                side=order_side,
                order_type="market",
                amount=Decimal(str(pos.qty)),
                td_mode=self.margin_mode,
                pos_side=await self._pos_side(pos.side),
                reduce_only=True,
            )
        except Exception as exc:
            error_msg = str(exc)
            if "51169" in error_msg or "don't have any positions" in error_msg:
                logger.warning(
                    f"[{symbol}] 持仓已被外部平仓（止盈止损单触发），清理本地记录: {error_msg}"
                )
                self.positions.pop(symbol, None)
                self._last_trade_at[symbol] = time.time()
                self._log_event(
                    event_type="close_position",
                    title="涨幅榜动量平仓(外部触发)",
                    message=f"{symbol} 持仓已被止盈止损单平仓，清理本地记录",
                    level="warning",
                    data={
                        "symbol": symbol,
                        "side": pos.side,
                        "reason": "external_close",
                        "error": error_msg,
                    },
                )
                return
            raise
        detail = await self._load_order_detail(symbol, order)
        exit_price = self._safe_float(detail.get("avgPx")) or pos.stop_px
        pos.current_price = exit_price
        pnl = self._position_pnl(pos)
        await self._save_symbol_order_to_db(
            symbol, detail, order_side, "market", None, Decimal(str(pos.qty))
        )

        self.realized_pnl += pnl
        self.total_trades += 1
        if pnl > 0:
            self._win_trades += 1
        self.win_rate = (
            self._win_trades / self.total_trades * 100 if self.total_trades else 0
        )
        self.record_trade_result(pnl)
        self._last_trade_at[symbol] = time.time()
        self.positions.pop(symbol, None)

        self._log_event(
            event_type="close_position",
            title="涨幅榜动量平仓",
            message=f"{symbol} {reason} 平仓，盈亏 {pnl:.4f} USDT",
            level="success" if pnl >= 0 else "warning",
            data={
                "symbol": symbol,
                "side": pos.side,
                "reason": reason,
                "exit": exit_price,
                "pnl": pnl,
            },
        )

    async def _calc_contract_qty(
        self, symbol: str, price: float, atr: float, info: Dict[str, float]
    ) -> float:
        if price <= 0 or atr <= 0:
            return 0.0
        balance = await self.exchange.get_balance()
        total_eq = self._safe_float(balance.get("totalEq"))
        details = balance.get("details", [])
        usdt = next((d for d in details if d.get("ccy") == "USDT"), {})
        available = self._safe_float(usdt.get("availBal"))
        equity = total_eq or available
        if equity <= 0 or available <= 0:
            return 0.0

        stop_distance = (
            price * self.fixed_sl_pct / 100
            if self.use_fixed_pct
            else max(self.stop_atr * atr, price * 0.002)
        )
        risk_capital = min(equity * self.risk_per_trade, self.max_position_usd * 0.08)
        qty_by_risk = risk_capital / (stop_distance * info["ct_val"])
        remaining_total_usd = max(
            0.0, self.max_total_position_usd - self._current_notional_usd()
        )
        if remaining_total_usd <= 0:
            return 0.0
        qty_by_cap = min(self.max_position_usd, remaining_total_usd) / (
            price * info["ct_val"]
        )
        qty_by_margin = (
            available * 0.75 * max(self.max_leverage, 1) / (price * info["ct_val"])
        )
        return self._round_qty(min(qty_by_risk, qty_by_cap, qty_by_margin), info)

    def _current_notional_usd(self) -> float:
        return sum(
            max(pos.current_price, pos.entry_price) * pos.qty * pos.ct_val
            for pos in self.positions.values()
        )

    def _position_pnl(self, pos: MomentumPosition) -> float:
        if pos.side == "short":
            return (pos.entry_price - pos.current_price) * pos.qty * pos.ct_val
        return (pos.current_price - pos.entry_price) * pos.qty * pos.ct_val

    def _risk_prices(
        self, entry_price: float, atr: float, side: str
    ) -> tuple[float, float]:
        if self.use_fixed_pct:
            if side == "short":
                stop_px = entry_price * (1 + self.fixed_sl_pct / 100)
                take_profit_px = entry_price * (1 - self.fixed_tp_pct / 100)
            else:
                stop_px = entry_price * (1 - self.fixed_sl_pct / 100)
                take_profit_px = entry_price * (1 + self.fixed_tp_pct / 100)
            return stop_px, take_profit_px
        if side == "short":
            stop_px = entry_price + self.stop_atr * atr
            take_profit_px = entry_price - self.take_profit_r * (stop_px - entry_price)
            return stop_px, take_profit_px
        stop_px = entry_price - self.stop_atr * atr
        take_profit_px = entry_price + self.take_profit_r * (entry_price - stop_px)
        return stop_px, take_profit_px

    @staticmethod
    def _attached_tp_sl(take_profit_px: float, stop_px: float) -> List[Dict]:
        return [
            {
                "tpTriggerPx": str(round(take_profit_px, 12)),
                "tpOrdPx": "-1",
                "slTriggerPx": str(round(stop_px, 12)),
                "slOrdPx": "-1",
            }
        ]

    async def _instrument(self, symbol: str) -> Dict[str, float]:
        if symbol in self._instrument_cache:
            return self._instrument_cache[symbol]
        raw = await self.exchange.get_instrument(symbol)
        info = {
            "ct_val": self._safe_float(raw.get("ctVal")) or 1.0,
            "lot_sz": self._safe_float(raw.get("lotSz")) or 1.0,
            "min_sz": self._safe_float(raw.get("minSz")) or 1.0,
        }
        self._instrument_cache[symbol] = info
        return info

    async def _ensure_leverage(self, symbol: str, side: str):
        try:
            await self.exchange.set_leverage(
                lever=str(self.max_leverage),
                mgn_mode=self.margin_mode,
                inst_id=symbol,
                pos_side=await self._pos_side(side),
            )
        except Exception as exc:
            logger.warning(f"[{symbol}] 设置杠杆失败，继续尝试下单: {exc}")

    async def _pos_side(self, side: str) -> Optional[str]:
        try:
            config = await self.exchange.get_account_config()
            return side if config.get("posMode") == "long_short_mode" else "net"
        except Exception:
            return "net"

    async def _load_order_detail(self, symbol: str, order: Dict) -> Dict:
        order_id = order.get("ordId")
        if not order_id:
            return order
        try:
            await asyncio.sleep(0.8)
            return await self.exchange.get_order(symbol, order_id=order_id)
        except Exception as exc:
            logger.warning(f"[{symbol}] 查询订单详情失败，使用下单返回: {exc}")
            return order

    def _round_qty(self, qty: float, info: Dict[str, float]) -> float:
        if qty <= 0:
            return 0.0
        lot_sz = info["lot_sz"]
        min_sz = info["min_sz"]
        rounded = math.floor(qty / lot_sz) * lot_sz
        if rounded < min_sz:
            return 0.0
        return round(rounded, 8)

    def _timeframe_seconds(self) -> int:
        return 5 * 60 if self.timeframe == "5m" else 15 * 60

    def get_signal_status(self) -> Dict:
        return self._signal_status or {"message": "等待涨幅榜扫描"}

    async def calculate_pnl(self) -> Dict:
        return {
            "total_pnl": self.realized_pnl + self._unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self._unrealized_pnl,
            "total_trades": self.total_trades,
            "buy_count": self.total_trades,
            "sell_count": self.total_trades,
            "win_rate": self.win_rate,
            "direction": self.direction,
            "top_n": self.top_n,
            "last_signal": self._signal_status,
            "open_positions": len(self.positions),
            "positions": {
                symbol: pos.__dict__ for symbol, pos in self.positions.items()
            },
        }

    def _update_signal_status(self, symbol: str, item: Dict, signal: Dict):
        status = {
            "symbol": symbol,
            "change_24h_pct": round(item["change_24h_pct"], 4),
            "action": signal["action"],
            "side": signal.get("side"),
            "status": signal["status"],
            "last": signal["last"],
            "rsi": round(signal["rsi"], 2),
            "atr_pct": round(signal["atr_pct"], 4),
            "message": f"{symbol} {signal['status']}，方向 {signal.get('side')}，动作 {signal['action']}",
        }
        self._signal_status = status
        key = f"{symbol}|{signal['action']}|{signal['status']}"
        now = time.time()
        if key != self._last_event_key or now - self._last_event_time > 15 * 60:
            self._last_event_key = key
            self._last_event_time = now
            self._log_event("signal", "涨幅榜动量信号", status["message"], data=status)

    def _log_event(
        self,
        event_type: str,
        title: str,
        message: str,
        level: str = "info",
        data: Optional[Dict] = None,
    ):
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
            logger.debug(f"涨幅榜动量写入事件失败: {exc}")
        finally:
            db.close()

    async def _save_symbol_order_to_db(
        self,
        symbol: str,
        order_data: Dict,
        side: str,
        order_type: str,
        price: Optional[Decimal],
        amount: Decimal,
    ):
        original_symbol = self.symbol
        self.symbol = symbol
        try:
            return await self._save_order_to_db(
                order_data, side, order_type, price, amount
            )
        finally:
            self.symbol = original_symbol

    @staticmethod
    def _ema(values: List[float], period: int) -> List[float]:
        output = []
        multiplier = 2 / (period + 1)
        previous = None
        for value in values:
            previous = (
                value
                if previous is None
                else previous + (value - previous) * multiplier
            )
            output.append(previous)
        return output

    @classmethod
    def _atr(
        cls,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14,
    ) -> List[float]:
        true_ranges = []
        for i, close in enumerate(closes):
            if i == 0:
                true_ranges.append(highs[i] - lows[i])
            else:
                true_ranges.append(
                    max(
                        highs[i] - lows[i],
                        abs(highs[i] - closes[i - 1]),
                        abs(lows[i] - closes[i - 1]),
                    )
                )
        return cls._ema(true_ranges, period)

    @staticmethod
    def _rsi(closes: List[float], period: int = 14) -> List[float]:
        output = []
        gains = []
        losses = []
        for i, close in enumerate(closes):
            if i == 0:
                output.append(50.0)
                continue
            delta = close - closes[i - 1]
            gains.append(max(delta, 0.0))
            losses.append(max(-delta, 0.0))
            if len(gains) > period:
                gains.pop(0)
                losses.pop(0)
            avg_gain = sum(gains) / len(gains)
            avg_loss = sum(losses) / len(losses)
            output.append(
                100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
            )
        return output

    @staticmethod
    def _safe_float(value) -> float:
        try:
            if value in (None, ""):
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0
