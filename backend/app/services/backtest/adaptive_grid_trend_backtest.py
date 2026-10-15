"""
自适应趋势网格策略回测引擎。

与实盘策略保持同一套核心规则：
- EMA 快慢线过滤趋势
- 趋势成立后，价格回撤到快线附近才入场
- ATR 止损/止盈
- 按账户权益固定比例计算单笔风险
- 单仓位运行，不马丁、不补仓
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional

from loguru import logger

from app.services.strategy.adaptive_grid_trend_config import (
    normalize_adaptive_grid_trend_params,
)

from .backtest_engine import BacktestEngine, Position, Trade


class AdaptiveGridTrendBacktestEngine(BacktestEngine):
    """自适应趋势网格回测引擎。"""

    def __init__(
        self,
        symbol: str,
        initial_capital: float,
        direction: str = "both",
        fast_period: int = 20,
        slow_period: int = 80,
        atr_period: int = 14,
        entry_atr_multiple: float = 0.6,
        stop_atr_multiple: float = 2.8,
        take_profit_atr_multiple: float = 6.0,
        risk_per_trade: float = 0.01,
        max_position_usd: float = 500.0,
        fee_rate: float = 0.0005,
        leverage: int = 3,
        cooldown_seconds: int = 60 * 60,
    ):
        super().__init__(
            symbol=symbol,
            initial_capital=initial_capital,
            fee_rate=fee_rate,
            leverage=leverage,
            enable_short=True,
        )

        self.direction = direction.lower()
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.atr_period = atr_period
        self.entry_atr_multiple = entry_atr_multiple
        self.stop_atr_multiple = stop_atr_multiple
        self.take_profit_atr_multiple = take_profit_atr_multiple
        self.risk_per_trade = risk_per_trade
        self.max_position_usd = max_position_usd
        self.cooldown_ms = cooldown_seconds * 1000

        self._klines: List[Dict] = []
        self._ema_fast: Optional[float] = None
        self._ema_slow: Optional[float] = None
        self._prev_close: Optional[float] = None
        self._true_ranges = deque(maxlen=self.atr_period)
        self._true_range_sum = 0.0
        self._position_side = ""
        self._entry_price = 0.0
        self._position_qty = 0.0
        self._stop_px = 0.0
        self._take_profit_px = 0.0
        self._last_trade_ts = 0

        self._long_trades = 0
        self._short_trades = 0
        self._stop_count = 0
        self._take_profit_count = 0
        self._cooldown_skip_count = 0

        logger.info(
            f"自适应趋势网格回测初始化: fast={fast_period}, slow={slow_period}, atr={atr_period}, "
            f"risk={risk_per_trade:.2%}, max_position=${max_position_usd}, leverage={leverage}x"
        )

    @classmethod
    def from_params(
        cls, symbol: str, initial_capital: float, params: Dict
    ) -> "AdaptiveGridTrendBacktestEngine":
        params = normalize_adaptive_grid_trend_params(params)
        return cls(
            symbol=symbol,
            initial_capital=initial_capital,
            direction=str(params.get("direction", "both")),
            fast_period=int(params.get("fast_period", 30)),
            slow_period=int(params.get("slow_period", 60)),
            atr_period=int(params.get("atr_period", 14)),
            entry_atr_multiple=float(params.get("entry_atr_multiple", 0.6)),
            stop_atr_multiple=float(params.get("stop_atr_multiple", 2.8)),
            take_profit_atr_multiple=float(params.get("take_profit_atr_multiple", 3.2)),
            risk_per_trade=float(params.get("risk_per_trade", 0.02)),
            max_position_usd=float(params.get("max_position_usd", 800)),
            fee_rate=float(params.get("fee_rate", 0.0005)),
            leverage=int(params.get("leverage", 5)),
            cooldown_seconds=int(params.get("cooldown_seconds", 60 * 60)),
        )

    def reset(self):
        super().reset()
        self._klines = []
        self._ema_fast = None
        self._ema_slow = None
        self._prev_close = None
        self._true_ranges = deque(maxlen=self.atr_period)
        self._true_range_sum = 0.0
        self._position_side = ""
        self._entry_price = 0.0
        self._position_qty = 0.0
        self._stop_px = 0.0
        self._take_profit_px = 0.0
        self._last_trade_ts = 0
        self._long_trades = 0
        self._short_trades = 0
        self._stop_count = 0
        self._take_profit_count = 0
        self._cooldown_skip_count = 0

    def on_kline(self, kline: Dict) -> Optional[Trade]:
        close = float(kline.get("close", 0))
        if close <= 0:
            return None

        self._klines.append(kline)
        self._update_indicators(kline)
        if len(self._klines) < self.slow_period + self.atr_period + 2:
            return None

        if self._position_side:
            closed = self._manage_position(kline)
            if closed:
                return closed

        timestamp = int(kline["timestamp"])
        if timestamp - self._last_trade_ts < self.cooldown_ms:
            self._cooldown_skip_count += 1
            return None

        metrics = self._metrics()
        if not metrics or metrics["atr"] <= 0:
            return None

        high = float(kline["high"])
        low = float(kline["low"])
        trend = metrics["trend"]
        ema_fast = metrics["ema_fast"]
        atr = metrics["atr"]

        if trend == "bull" and self.direction in {"long", "both"}:
            if low <= ema_fast + atr * self.entry_atr_multiple:
                return self._open_position("long", close, atr, timestamp)

        if trend == "bear" and self.direction in {"short", "both"}:
            if high >= ema_fast - atr * self.entry_atr_multiple:
                return self._open_position("short", close, atr, timestamp)

        return None

    def _metrics(self) -> Optional[Dict]:
        if (
            len(self._klines) < self.slow_period + self.atr_period
            or len(self._true_ranges) < self.atr_period
            or self._ema_fast is None
            or self._ema_slow is None
        ):
            return None

        ema_fast = self._ema_fast
        ema_slow = self._ema_slow
        atr = self._true_range_sum / self.atr_period
        trend = (
            "bull" if ema_fast > ema_slow else "bear" if ema_fast < ema_slow else "flat"
        )
        return {"trend": trend, "ema_fast": ema_fast, "ema_slow": ema_slow, "atr": atr}

    def _update_indicators(self, kline: Dict):
        close = float(kline["close"])
        high = float(kline["high"])
        low = float(kline["low"])

        if self._ema_fast is None:
            self._ema_fast = close
            self._ema_slow = close
        else:
            fast_alpha = 2 / (self.fast_period + 1)
            slow_alpha = 2 / (self.slow_period + 1)
            self._ema_fast = close * fast_alpha + self._ema_fast * (1 - fast_alpha)
            self._ema_slow = close * slow_alpha + self._ema_slow * (1 - slow_alpha)

        if self._prev_close is not None:
            true_range = max(
                high - low,
                abs(high - self._prev_close),
                abs(low - self._prev_close),
            )
            if len(self._true_ranges) == self._true_ranges.maxlen:
                self._true_range_sum -= self._true_ranges[0]
            self._true_ranges.append(true_range)
            self._true_range_sum += true_range

        self._prev_close = close

    def _calc_qty(self, price: float, atr: float) -> float:
        equity = self.get_total_equity(price)
        stop_distance = max(atr * self.stop_atr_multiple, price * 0.002)
        risk_capital = min(equity * self.risk_per_trade, self.max_position_usd * 0.05)
        qty_by_risk = risk_capital / stop_distance
        qty_by_cap = self.max_position_usd / price
        return max(0.0, min(qty_by_risk, qty_by_cap))

    def _open_position(
        self, side: str, price: float, atr: float, timestamp: int
    ) -> Optional[Trade]:
        if self._position_side:
            return None

        qty = self._calc_qty(price, atr)
        if qty <= 0:
            return None

        notional = price * qty
        margin_required = notional / self.leverage
        fee = notional * self.fee_rate
        if margin_required + fee > self.capital:
            return None

        capital_before = self.capital
        position_before = self.position.amount
        self.capital -= margin_required + fee
        signed_qty = qty if side == "long" else -qty
        self.position = Position(
            amount=signed_qty,
            avg_price=price,
            direction=side,
            margin_used=margin_required,
        )

        self._position_side = side
        self._entry_price = price
        self._position_qty = qty
        if side == "long":
            self._stop_px = price - atr * self.stop_atr_multiple
            self._take_profit_px = price + atr * self.take_profit_atr_multiple
            self._long_trades += 1
        else:
            self._stop_px = price + atr * self.stop_atr_multiple
            self._take_profit_px = price - atr * self.take_profit_atr_multiple
            self._short_trades += 1

        trade = Trade(
            timestamp=timestamp,
            side="buy" if side == "long" else "sell",
            price=price,
            amount=qty,
            fee=fee,
            position_before=position_before,
            position_after=self.position.amount,
            capital_before=capital_before,
            capital_after=self.capital,
            direction=side,
            leverage=self.leverage,
            margin_used=margin_required,
        )
        self.trades.append(trade)
        return trade

    def _manage_position(self, kline: Dict) -> Optional[Trade]:
        high = float(kline["high"])
        low = float(kline["low"])
        close = float(kline["close"])
        timestamp = int(kline["timestamp"])

        if self._position_side == "long":
            if low <= self._stop_px:
                self._stop_count += 1
                return self._close_position(self._stop_px, timestamp)
            if high >= self._take_profit_px:
                self._take_profit_count += 1
                return self._close_position(self._take_profit_px, timestamp)

        if self._position_side == "short":
            if high >= self._stop_px:
                self._stop_count += 1
                return self._close_position(self._stop_px, timestamp)
            if low <= self._take_profit_px:
                self._take_profit_count += 1
                return self._close_position(self._take_profit_px, timestamp)

        self._update_unrealized(close)
        return None

    def _close_position(self, price: float, timestamp: int) -> Optional[Trade]:
        if not self._position_side or self._position_qty <= 0:
            return None

        qty = self._position_qty
        notional = price * qty
        fee = notional * self.fee_rate
        if self._position_side == "long":
            gross_pnl = (price - self._entry_price) * qty
            order_side = "sell"
        else:
            gross_pnl = (self._entry_price - price) * qty
            order_side = "buy"

        pnl = gross_pnl - fee
        capital_before = self.capital
        position_before = self.position.amount
        margin_released = self.position.margin_used
        self.capital += margin_released + pnl

        trade = Trade(
            timestamp=timestamp,
            side=order_side,
            price=price,
            amount=qty,
            fee=fee,
            position_before=position_before,
            position_after=0.0,
            capital_before=capital_before,
            capital_after=self.capital,
            pnl=pnl,
            pnl_percent=(pnl / margin_released * 100) if margin_released > 0 else 0.0,
            direction=self._position_side,
            leverage=self.leverage,
            margin_used=margin_released,
        )
        self.trades.append(trade)

        self.position = Position()
        self._position_side = ""
        self._entry_price = 0.0
        self._position_qty = 0.0
        self._stop_px = 0.0
        self._take_profit_px = 0.0
        self._last_trade_ts = timestamp
        return trade

    def _update_unrealized(self, current_price: float):
        if self.position.amount > 0:
            self.position.unrealized_pnl = (
                current_price - self.position.avg_price
            ) * self.position.amount
        elif self.position.amount < 0:
            qty = abs(self.position.amount)
            self.position.unrealized_pnl = (
                self.position.avg_price - current_price
            ) * qty
        else:
            self.position.unrealized_pnl = 0.0

    def update_equity(self, current_price: float, timestamp: int):
        self._update_unrealized(current_price)
        total_equity = (
            self.capital + self.position.margin_used + self.position.unrealized_pnl
        )
        self.equity_curve.append(
            {
                "timestamp": timestamp,
                "equity": total_equity,
                "capital": self.capital,
                "position_value": self.position.margin_used,
                "unrealized_pnl": self.position.unrealized_pnl,
                "position_direction": self.position.direction,
                "leverage": self.leverage,
            }
        )

    def get_total_equity(self, current_price: float) -> float:
        self._update_unrealized(current_price)
        return self.capital + self.position.margin_used + self.position.unrealized_pnl

    def run(self, klines: List[Dict], progress_callback=None) -> Dict:
        logger.info(
            f"开始自适应趋势网格回测: {self.symbol}, 初始资金: {self.initial_capital}, "
            f"K线数量: {len(klines)}, 杠杆: {self.leverage}x"
        )
        self.reset()

        total_klines = len(klines)
        for i, kline in enumerate(klines):
            self.current_index = i
            self.current_kline = kline

            close_price = float(kline["close"])
            timestamp = int(kline["timestamp"])

            if self.leverage > 1 and self.check_liquidation(close_price):
                self._close_position(close_price, timestamp)
                self.liquidation_count += 1
                self.liquidated = True

            if not self.liquidated:
                self.on_kline(kline)

            self.update_equity(close_price, timestamp)

            if progress_callback and i % 100 == 0:
                progress_callback(i + 1, total_klines)

        if klines and self._position_side:
            final_price = float(klines[-1]["close"])
            final_ts = int(klines[-1]["timestamp"])
            self._close_position(final_price, final_ts)
            self.update_equity(final_price, final_ts)

        if progress_callback:
            progress_callback(total_klines, total_klines)

        final_equity = (
            self.get_total_equity(float(klines[-1]["close"]))
            if klines
            else self.initial_capital
        )
        logger.info(
            f"自适应趋势网格回测完成: 最终权益={final_equity:.2f}, "
            f"交易次数={len(self.trades)}, 强平次数={self.liquidation_count}"
        )
        return {
            "final_equity": final_equity,
            "total_trades": len(self.trades),
            "initial_capital": self.initial_capital,
            "liquidation_count": self.liquidation_count,
            "leverage": self.leverage,
        }

    def get_statistics(self) -> Dict:
        return {
            "strategy_type": "adaptive_grid_trend",
            "long_trades": self._long_trades,
            "short_trades": self._short_trades,
            "stop_count": self._stop_count,
            "take_profit_count": self._take_profit_count,
            "cooldown_skip_count": self._cooldown_skip_count,
        }
