"""
固定止盈止损趋势回测引擎

默认用于验证 5x 杠杆、上涨 1% 止盈、下跌 0.5% 止损的短线策略。
"""
from typing import Dict, List

from .backtest_engine import BacktestEngine


class FixedTpSlTrendBacktestEngine(BacktestEngine):
    """EMA 上穿开多，固定百分比止盈止损。"""

    def __init__(
        self,
        symbol: str,
        initial_capital: float = 10000.0,
        fee_rate: float = 0.0005,
        leverage: int = 5,
        position_ratio: float = 0.4,
        take_profit_pct: float = 0.01,
        stop_loss_pct: float = 0.005,
        fast_period: int = 12,
        slow_period: int = 40,
    ):
        super().__init__(
            symbol=symbol,
            initial_capital=initial_capital,
            fee_rate=fee_rate,
            leverage=leverage,
            enable_short=False,
        )
        self.position_ratio = min(max(position_ratio, 0.0), 1.0)
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.prices: List[float] = []
        self.fast_ema: List[float] = []
        self.slow_ema: List[float] = []
        self.entry_price = 0.0

    @classmethod
    def from_params(cls, symbol: str, initial_capital: float, params: Dict):
        return cls(
            symbol=symbol,
            initial_capital=initial_capital,
            fee_rate=float(params.get("fee_rate", 0.0005)),
            leverage=int(params.get("leverage", 5)),
            position_ratio=float(params.get("position_ratio", 0.4)),
            take_profit_pct=float(params.get("take_profit_pct", 0.01)),
            stop_loss_pct=float(params.get("stop_loss_pct", 0.005)),
            fast_period=int(params.get("fast_period", 12)),
            slow_period=int(params.get("slow_period", 40)),
        )

    def reset(self):
        super().reset()
        self.prices = []
        self.fast_ema = []
        self.slow_ema = []
        self.entry_price = 0.0

    @staticmethod
    def _next_ema(previous: float | None, price: float, period: int, prices: List[float]) -> float:
        if previous is None:
            window = prices[-period:] if len(prices) >= period else prices
            return sum(window) / len(window)
        multiplier = 2 / (period + 1)
        return previous + (price - previous) * multiplier

    def _position_amount(self, price: float) -> float:
        notional = self.capital * self.position_ratio * self.leverage
        return notional / price if price > 0 else 0.0

    def _account_equity(self, current_price: float) -> float:
        if self.position.amount <= 0:
            return self.capital
        unrealized_pnl = (current_price - self.position.avg_price) * self.position.amount
        return self.capital + self.position.margin_used + unrealized_pnl

    def update_equity(self, current_price: float, timestamp: int):
        if self.position.amount > 0:
            self.position.unrealized_pnl = (
                current_price - self.position.avg_price
            ) * self.position.amount
            position_value = current_price * self.position.amount
        else:
            self.position.unrealized_pnl = 0.0
            position_value = 0.0

        self.equity_curve.append({
            "timestamp": timestamp,
            "equity": self._account_equity(current_price),
            "capital": self.capital,
            "position_value": position_value,
            "unrealized_pnl": self.position.unrealized_pnl,
            "position_direction": self.position.direction,
            "leverage": self.leverage,
        })

    def get_total_equity(self, current_price: float) -> float:
        return self._account_equity(current_price)

    def _close_if_exit_hit(self, low_price: float, high_price: float, timestamp: int) -> bool:
        if self.position.amount <= 0 or self.entry_price <= 0:
            return False

        stop_price = self.entry_price * (1 - self.stop_loss_pct)
        take_price = self.entry_price * (1 + self.take_profit_pct)

        # 保守处理：同一根 K 线同时碰到止盈止损时，优先按止损成交。
        if low_price <= stop_price:
            self.sell(stop_price, self.position.amount, timestamp)
            self.entry_price = 0.0
            return True
        if high_price >= take_price:
            self.sell(take_price, self.position.amount, timestamp)
            self.entry_price = 0.0
            return True
        return False

    def on_kline(self, kline: Dict):
        timestamp = int(kline["timestamp"])
        high_price = float(kline["high"])
        low_price = float(kline["low"])
        close_price = float(kline["close"])

        if self._close_if_exit_hit(low_price, high_price, timestamp):
            return

        self.prices.append(close_price)
        fast_previous = self.fast_ema[-1] if self.fast_ema else None
        slow_previous = self.slow_ema[-1] if self.slow_ema else None
        fast = self._next_ema(fast_previous, close_price, self.fast_period, self.prices)
        slow = self._next_ema(slow_previous, close_price, self.slow_period, self.prices)
        self.fast_ema.append(fast)
        self.slow_ema.append(slow)

        if len(self.prices) < self.slow_period + 1 or self.position.amount != 0:
            return

        fast_prev = self.fast_ema[-2]
        slow_prev = self.slow_ema[-2]
        golden_cross = fast_prev <= slow_prev and fast > slow

        if golden_cross:
            amount = self._position_amount(close_price)
            trade = self.buy(close_price, amount, timestamp)
            if trade:
                self.entry_price = close_price
