"""
双向持仓策略回测引擎

支持多空双向交易，EMA双均线判断趋势方向：
- 金叉（快线上穿慢线）→ 开多
- 死叉（快线下穿慢线）→ 开空
- 趋势反转时平仓并反向开仓
"""

from typing import Dict, List, Optional
from loguru import logger
from .backtest_engine import BacktestEngine, Trade, Position
from .indicators import TechnicalIndicators, KlineBuffer


class DualSideBacktestEngine(BacktestEngine):
    """双向持仓策略回测引擎"""

    def __init__(
        self,
        symbol: str,
        initial_capital: float,
        fast_period: int = 12,
        slow_period: int = 40,
        position_ratio: float = 0.3,  # 每次开仓资金比例
        fee_rate: float = 0.001,
        leverage: int = 5,
        stop_loss: float = 0.02,  # 止损比例
        take_profit: float = 0.06,  # 止盈比例
        trailing_stop: float = 0.02,  # 移动止损比例
    ):
        """
        初始化双向持仓策略回测引擎

        Args:
            symbol: 交易对
            initial_capital: 初始资金
            fast_period: EMA快线周期
            slow_period: EMA慢线周期
            position_ratio: 每次开仓资金比例
            fee_rate: 手续费率
            leverage: 杠杆倍数
            stop_loss: 止损比例
            take_profit: 止盈比例
            trailing_stop: 移动止损比例
        """
        super().__init__(
            symbol=symbol,
            initial_capital=initial_capital,
            fee_rate=fee_rate,
            leverage=leverage,
            enable_short=True,  # 双向策略必须支持做空
        )

        self.fast_period = fast_period
        self.slow_period = slow_period
        self.position_ratio = position_ratio
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.trailing_stop = trailing_stop

        # K线缓冲区
        self.kline_buffer = KlineBuffer(max_size=max(fast_period, slow_period) + 10)

        # EMA历史
        self.fast_ema_history: List[float] = []
        self.slow_ema_history: List[float] = []

        # 持仓状态
        self._position_side: str = ""  # "long" / "short" / ""
        self._entry_price: float = 0.0
        self._extreme_price: float = 0.0  # 多仓=最高价，空仓=最低价
        self._trail_stop_px: float = 0.0

        # 统计
        self._long_trades: int = 0
        self._short_trades: int = 0
        self._stop_loss_count: int = 0
        self._take_profit_count: int = 0
        self._trailing_stop_count: int = 0
        self._signal_reverse_count: int = 0

        logger.info(
            f"双向持仓策略初始化: 快线={fast_period}, 慢线={slow_period}, "
            f"仓位比例={position_ratio*100}%, 杠杆={leverage}x, "
            f"止损={stop_loss*100}%, 止盈={take_profit*100}%, 移动止损={trailing_stop*100}%"
        )

    def reset(self):
        """重置回测状态"""
        super().reset()
        self.kline_buffer = KlineBuffer(
            max_size=max(self.fast_period, self.slow_period) + 10
        )
        self.fast_ema_history = []
        self.slow_ema_history = []
        self._position_side = ""
        self._entry_price = 0.0
        self._extreme_price = 0.0
        self._trail_stop_px = 0.0
        self._long_trades = 0
        self._short_trades = 0
        self._stop_loss_count = 0
        self._take_profit_count = 0
        self._trailing_stop_count = 0
        self._signal_reverse_count = 0

    @classmethod
    def from_params(
        cls, symbol: str, initial_capital: float, params: Dict
    ) -> "DualSideBacktestEngine":
        """从参数字典创建引擎实例"""
        return cls(
            symbol=symbol,
            initial_capital=initial_capital,
            fast_period=int(params.get("fast_period", 12)),
            slow_period=int(params.get("slow_period", 40)),
            position_ratio=float(params.get("position_ratio", 0.3)),
            fee_rate=float(params.get("fee_rate", 0.001)),
            leverage=int(params.get("leverage", 5)),
            stop_loss=float(params.get("stop_loss", 0.02)),
            take_profit=float(params.get("take_profit", 0.06)),
            trailing_stop=float(params.get("trailing_stop", 0.02)),
        )

    def _calculate_ema(self, data: List[float], period: int) -> float:
        """计算EMA"""
        if len(data) < period:
            return 0.0
        multiplier = 2 / (period + 1)
        ema = sum(data[:period]) / period
        for price in data[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def on_kline(self, kline: Dict) -> Optional[Trade]:
        """
        处理K线数据

        Args:
            kline: K线数据 {timestamp, open, high, low, close, volume}

        Returns:
            交易记录（如果有）
        """
        close = float(kline.get("close", 0))
        if close <= 0:
            return None

        # 添加到缓冲区
        self.kline_buffer.add(close)
        self.current_kline = kline

        # 获取收盘价序列
        closes = self.kline_buffer.get_all()
        if len(closes) < self.slow_period + 2:
            return None

        # 计算EMA
        fast_ema = self._calculate_ema(closes, self.fast_period)
        slow_ema = self._calculate_ema(closes, self.slow_period)

        self.fast_ema_history.append(fast_ema)
        self.slow_ema_history.append(slow_ema)

        # 需要至少2个EMA值来检测交叉
        if len(self.fast_ema_history) < 2:
            return None

        fast_prev = self.fast_ema_history[-2]
        slow_prev = self.slow_ema_history[-2]

        # 检测交叉
        golden_cross = fast_prev <= slow_prev and fast_ema > slow_ema
        death_cross = fast_prev >= slow_prev and fast_ema < slow_ema

        trade = None

        # 检查止损止盈（如果有持仓）
        if self._position_side:
            trade = self._check_stop_loss_take_profit(kline)

        # 处理信号
        if golden_cross:
            if self._position_side == "short":
                # 平空并开多
                trade = self._close_position(kline, reason="golden_cross")
                trade = self._open_position(kline, "long")
            elif not self._position_side:
                trade = self._open_position(kline, "long")

        elif death_cross:
            if self._position_side == "long":
                # 平多并开空
                trade = self._close_position(kline, reason="death_cross")
                trade = self._open_position(kline, "short")
            elif not self._position_side:
                trade = self._open_position(kline, "short")

        return trade

    def _check_stop_loss_take_profit(self, kline: Dict) -> Optional[Trade]:
        """检查止损止盈"""
        high = float(kline.get("high", 0))
        low = float(kline.get("low", 0))
        close = float(kline.get("close", 0))

        if not self._position_side or self._entry_price <= 0:
            return None

        # 计算盈亏比例
        if self._position_side == "long":
            pnl_pct = (close - self._entry_price) / self._entry_price
            extreme = high
        else:
            pnl_pct = (self._entry_price - close) / self._entry_price
            extreme = low

        # 更新极值价格
        if self._position_side == "long" and high > self._extreme_price:
            self._extreme_price = high
            if self.trailing_stop > 0:
                self._trail_stop_px = high * (1 - self.trailing_stop)
        elif self._position_side == "short" and low < self._extreme_price:
            self._extreme_price = low
            if self.trailing_stop > 0:
                self._trail_stop_px = low * (1 + self.trailing_stop)

        # 移动止损检查
        if self.trailing_stop > 0 and self._trail_stop_px > 0:
            if self._position_side == "long" and low <= self._trail_stop_px:
                self._trailing_stop_count += 1
                return self._close_position(kline, reason="trailing_stop")
            elif self._position_side == "short" and high >= self._trail_stop_px:
                self._trailing_stop_count += 1
                return self._close_position(kline, reason="trailing_stop")

        # 固定止损
        if pnl_pct <= -self.stop_loss:
            self._stop_loss_count += 1
            return self._close_position(kline, reason="stop_loss")

        # 止盈
        if pnl_pct >= self.take_profit:
            self._take_profit_count += 1
            return self._close_position(kline, reason="take_profit")

        return None

    def _open_position(self, kline: Dict, side: str) -> Optional[Trade]:
        """开仓"""
        close = float(kline.get("close", 0))
        timestamp = int(kline.get("timestamp", 0))

        # 计算开仓数量
        available = self.capital * self.position_ratio
        position_value = available * self.leverage
        amount = position_value / close

        # 执行开仓
        if side == "long":
            trade = self.open_long(
                price=close, amount=amount, timestamp=timestamp, leverage=self.leverage
            )
            if trade:
                self._position_side = "long"
                self._entry_price = close
                self._extreme_price = close
                self._trail_stop_px = 0
                self._long_trades += 1
        else:
            trade = self.open_short(
                price=close, amount=amount, timestamp=timestamp, leverage=self.leverage
            )
            if trade:
                self._position_side = "short"
                self._entry_price = close
                self._extreme_price = close
                self._trail_stop_px = 0
                self._short_trades += 1

        return trade

    def _close_position(self, kline: Dict, reason: str = "signal") -> Optional[Trade]:
        """平仓"""
        if not self._position_side:
            return None

        close = float(kline.get("close", 0))
        timestamp = int(kline.get("timestamp", 0))

        if reason in ["golden_cross", "death_cross"]:
            self._signal_reverse_count += 1

        if self._position_side == "long":
            trade = self.close_long(
                price=close, amount=self.position.amount, timestamp=timestamp
            )
        else:
            trade = self.close_short(
                price=close, amount=abs(self.position.amount), timestamp=timestamp
            )

        # 重置状态
        self._position_side = ""
        self._entry_price = 0.0
        self._extreme_price = 0.0
        self._trail_stop_px = 0.0

        return trade

    def get_statistics(self) -> Dict:
        """获取回测统计信息"""
        base_stats = super().get_statistics()

        base_stats.update(
            {
                "strategy_type": "dual_side",
                "fast_period": self.fast_period,
                "slow_period": self.slow_period,
                "leverage": self.leverage,
                "position_ratio": self.position_ratio,
                "stop_loss": self.stop_loss,
                "take_profit": self.take_profit,
                "trailing_stop": self.trailing_stop,
                "long_trades": self._long_trades,
                "short_trades": self._short_trades,
                "stop_loss_count": self._stop_loss_count,
                "take_profit_count": self._take_profit_count,
                "trailing_stop_count": self._trailing_stop_count,
                "signal_reverse_count": self._signal_reverse_count,
            }
        )

        return base_stats
