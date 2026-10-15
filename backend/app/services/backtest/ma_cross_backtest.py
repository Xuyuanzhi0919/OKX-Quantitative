"""
均线交叉策略回测实现
支持做多和做空，支持杠杆
"""

from typing import Dict, List, Optional
from loguru import logger
from .backtest_engine import BacktestEngine
from .indicators import TechnicalIndicators, KlineBuffer


class MACrossBacktestEngine(BacktestEngine):
    """均线交叉策略回测引擎"""

    def __init__(
        self,
        symbol: str,
        initial_capital: float,
        fast_period: int = 5,
        slow_period: int = 20,
        ma_type: str = "EMA",  # SMA 或 EMA
        amount_per_trade: float = 0.01,  # 每次交易数量
        fee_rate: float = 0.001,
        leverage: int = 1,
        enable_short: bool = False,
        use_price_filter: bool = False,  # 是否使用价格过滤
    ):
        """
        初始化均线交叉策略回测引擎

        Args:
            symbol: 交易对
            initial_capital: 初始资金
            fast_period: 快速均线周期
            slow_period: 慢速均线周期
            ma_type: 均线类型 (SMA/EMA)
            amount_per_trade: 每次交易数量
            fee_rate: 手续费率
            leverage: 杠杆倍数
            enable_short: 是否启用做空
            use_price_filter: 是否使用价格过滤（价格需在均线之上才做多）
        """
        super().__init__(
            symbol=symbol,
            initial_capital=initial_capital,
            fee_rate=fee_rate,
            leverage=leverage,
            enable_short=enable_short,
        )

        self.fast_period = fast_period
        self.slow_period = slow_period
        self.ma_type = ma_type.upper()
        self.amount_per_trade = amount_per_trade
        self.use_price_filter = use_price_filter

        # K线缓冲区
        self.kline_buffer = KlineBuffer(max_size=max(fast_period, slow_period) + 10)

        # 均线历史
        self.fast_ma_history: List[float] = []
        self.slow_ma_history: List[float] = []

        logger.info(
            f"均线交叉策略初始化: 快线={fast_period}, 慢线={slow_period}, "
            f"类型={ma_type}, 交易数量={amount_per_trade}, 杠杆={leverage}x, 做空={enable_short}"
        )

    def reset(self):
        """重置回测状态"""
        super().reset()
        self.kline_buffer = KlineBuffer(
            max_size=max(self.fast_period, self.slow_period) + 10
        )
        self.fast_ma_history = []
        self.slow_ma_history = []

    @classmethod
    def from_params(
        cls, symbol: str, initial_capital: float, params: Dict
    ) -> "MACrossBacktestEngine":
        """
        从参数字典创建引擎实例

        Args:
            symbol: 交易对
            initial_capital: 初始资金
            params: 参数字典

        Returns:
            引擎实例
        """
        return cls(
            symbol=symbol,
            initial_capital=initial_capital,
            fast_period=int(params.get("fast_period", 5)),
            slow_period=int(params.get("slow_period", 20)),
            ma_type=params.get("ma_type", "EMA"),
            amount_per_trade=float(params.get("amount_per_trade", 0.01)),
            fee_rate=float(params.get("fee_rate", 0.001)),
            leverage=int(params.get("leverage", 1)),
            enable_short=bool(params.get("enable_short", False)),
            use_price_filter=bool(params.get("use_price_filter", False)),
        )

    def calculate_ma(self, data: List[float], period: int) -> Optional[float]:
        """
        计算均线值

        Args:
            data: 价格数据
            period: 周期

        Returns:
            均线值
        """
        if len(data) < period:
            return None

        if self.ma_type == "EMA":
            result = TechnicalIndicators.EMA(data, period)
        else:
            result = TechnicalIndicators.SMA(data, period)

        return result[-1] if result and result[-1] is not None else None

    def on_kline(self, kline: Dict):
        """
        处理K线数据，执行均线交叉策略

        策略逻辑:
        - 快线上穿慢线时买入（金叉）
        - 快线下穿慢线时卖出（死叉）
        - 如果启用做空：死叉时开空，金叉时平空

        Args:
            kline: K线数据
        """
        # 添加K线到缓冲区
        self.kline_buffer.add(kline)

        closes = self.kline_buffer.get_closes()
        close_price = float(kline["close"])
        timestamp = int(kline["timestamp"])

        # 计算均线
        fast_ma = self.calculate_ma(closes, self.fast_period)
        slow_ma = self.calculate_ma(closes, self.slow_period)

        if fast_ma is None or slow_ma is None:
            return

        # 保存均线历史
        self.fast_ma_history.append(fast_ma)
        self.slow_ma_history.append(slow_ma)

        # 需要至少两根K线来判断交叉
        if len(self.fast_ma_history) < 2:
            return

        # 获取前一根K线的均线
        prev_fast_ma = self.fast_ma_history[-2]
        prev_slow_ma = self.slow_ma_history[-2]

        # 检测金叉（快线上穿慢线）
        golden_cross = prev_fast_ma <= prev_slow_ma and fast_ma > slow_ma

        # 检测死叉（快线下穿慢线）
        death_cross = prev_fast_ma >= prev_slow_ma and fast_ma < slow_ma

        # 价格过滤（可选）
        if self.use_price_filter:
            # 只有价格在慢线之上才做多
            if close_price < slow_ma:
                golden_cross = False

        # 执行交易逻辑
        if golden_cross:
            # 金叉：做多
            if self.position.amount <= 0:
                # 如果有空仓，先平空
                if self.position.amount < 0 and self.enable_short:
                    self.cover(close_price, abs(self.position.amount), timestamp)
                    logger.debug(f"金叉平空: 价格={close_price:.2f}")

                # 开多仓
                self.buy(close_price, self.amount_per_trade, timestamp)
                self.position.direction = "long"
                logger.debug(
                    f"金叉开多: 价格={close_price:.2f}, 快线={fast_ma:.2f}, 慢线={slow_ma:.2f}"
                )

        elif death_cross:
            # 死叉：平多或开空
            if self.position.amount > 0:
                # 平多仓
                self.sell(close_price, self.position.amount, timestamp)
                logger.debug(f"死叉平多: 价格={close_price:.2f}")

            # 如果启用做空，开空仓
            if self.enable_short and self.position.amount == 0:
                self.short(close_price, self.amount_per_trade, timestamp)
                logger.debug(
                    f"死叉开空: 价格={close_price:.2f}, 快线={fast_ma:.2f}, 慢线={slow_ma:.2f}"
                )


class DualMACrossBacktestEngine(BacktestEngine):
    """
    双均线交叉策略（支持多空双向）
    更灵活的仓位管理
    """

    def __init__(
        self,
        symbol: str,
        initial_capital: float,
        fast_period: int = 5,
        slow_period: int = 20,
        ma_type: str = "EMA",
        position_ratio: float = 0.9,  # 仓位比例
        fee_rate: float = 0.001,
        leverage: int = 1,
        enable_short: bool = True,  # 默认启用做空
        stop_loss: float = 0.0,  # 止损比例，0表示不启用
        take_profit: float = 0.0,  # 止盈比例，0表示不启用
    ):
        """
        初始化双均线交叉策略

        Args:
            symbol: 交易对
            initial_capital: 初始资金
            fast_period: 快速均线周期
            slow_period: 慢速均线周期
            ma_type: 均线类型
            position_ratio: 仓位比例
            fee_rate: 手续费率
            leverage: 杠杆倍数
            enable_short: 是否启用做空
            stop_loss: 止损比例
            take_profit: 止盈比例
        """
        super().__init__(
            symbol=symbol,
            initial_capital=initial_capital,
            fee_rate=fee_rate,
            leverage=leverage,
            enable_short=enable_short,
        )

        self.fast_period = fast_period
        self.slow_period = slow_period
        self.ma_type = ma_type.upper()
        self.position_ratio = position_ratio
        self.stop_loss = stop_loss
        self.take_profit = take_profit

        self.kline_buffer = KlineBuffer(max_size=max(fast_period, slow_period) + 10)
        self.fast_ma_history: List[float] = []
        self.slow_ma_history: List[float] = []

        # 记录入场价格用于止损止盈
        self.entry_price: Optional[float] = None

        logger.info(
            f"双均线策略初始化: 快线={fast_period}, 慢线={slow_period}, "
            f"仓位比例={position_ratio}, 杠杆={leverage}x, 做空={enable_short}, "
            f"止损={stop_loss*100 if stop_loss else '无'}%, 止盈={take_profit*100 if take_profit else '无'}%"
        )

    def reset(self):
        """重置回测状态"""
        super().reset()
        self.kline_buffer = KlineBuffer(
            max_size=max(self.fast_period, self.slow_period) + 10
        )
        self.fast_ma_history = []
        self.slow_ma_history = []
        self.entry_price = None

    @classmethod
    def from_params(
        cls, symbol: str, initial_capital: float, params: Dict
    ) -> "DualMACrossBacktestEngine":
        """从参数字典创建引擎实例"""
        return cls(
            symbol=symbol,
            initial_capital=initial_capital,
            fast_period=int(params.get("fast_period", 5)),
            slow_period=int(params.get("slow_period", 20)),
            ma_type=params.get("ma_type", "EMA"),
            position_ratio=float(params.get("position_ratio", 0.9)),
            fee_rate=float(params.get("fee_rate", 0.001)),
            leverage=int(params.get("leverage", 1)),
            enable_short=bool(params.get("enable_short", True)),
            stop_loss=float(params.get("stop_loss", 0.0)),
            take_profit=float(params.get("take_profit", 0.0)),
        )

    def calculate_position_size(self, price: float) -> float:
        """
        计算仓位大小

        Args:
            price: 当前价格

        Returns:
            交易数量
        """
        # 可用资金 * 仓位比例 / 价格
        available = self.capital * self.position_ratio
        if self.leverage > 1:
            available *= self.leverage
        return available / price

    def check_stop_loss_take_profit(self, close_price: float, timestamp: int):
        """
        检查止损止盈

        Args:
            close_price: 当前价格
            timestamp: 时间戳
        """
        if self.entry_price is None or self.position.amount == 0:
            return

        if self.position.direction == "long":
            # 做多止损止盈
            pnl_ratio = (close_price - self.entry_price) / self.entry_price

            if self.stop_loss > 0 and pnl_ratio <= -self.stop_loss:
                # 触发止损
                self.sell(close_price, self.position.amount, timestamp)
                self.entry_price = None
                logger.debug(
                    f"做多止损触发: 价格={close_price:.2f}, 亏损={pnl_ratio*100:.2f}%"
                )

            elif self.take_profit > 0 and pnl_ratio >= self.take_profit:
                # 触发止盈
                self.sell(close_price, self.position.amount, timestamp)
                self.entry_price = None
                logger.debug(
                    f"做多止盈触发: 价格={close_price:.2f}, 盈利={pnl_ratio*100:.2f}%"
                )

        elif self.position.direction == "short":
            # 做空止损止盈
            pnl_ratio = (self.entry_price - close_price) / self.entry_price

            if self.stop_loss > 0 and pnl_ratio <= -self.stop_loss:
                # 触发止损
                self.cover(close_price, abs(self.position.amount), timestamp)
                self.entry_price = None
                logger.debug(
                    f"做空止损触发: 价格={close_price:.2f}, 亏损={pnl_ratio*100:.2f}%"
                )

            elif self.take_profit > 0 and pnl_ratio >= self.take_profit:
                # 触发止盈
                self.cover(close_price, abs(self.position.amount), timestamp)
                self.entry_price = None
                logger.debug(
                    f"做空止盈触发: 价格={close_price:.2f}, 盈利={pnl_ratio*100:.2f}%"
                )

    def on_kline(self, kline: Dict):
        """
        处理K线数据

        Args:
            kline: K线数据
        """
        self.kline_buffer.add(kline)

        closes = self.kline_buffer.get_closes()
        close_price = float(kline["close"])
        timestamp = int(kline["timestamp"])

        # 检查止损止盈
        self.check_stop_loss_take_profit(close_price, timestamp)

        # 计算均线
        if self.ma_type == "EMA":
            fast_result = TechnicalIndicators.EMA(closes, self.fast_period)
            slow_result = TechnicalIndicators.EMA(closes, self.slow_period)
        else:
            fast_result = TechnicalIndicators.SMA(closes, self.fast_period)
            slow_result = TechnicalIndicators.SMA(closes, self.slow_period)

        if not fast_result or not slow_result:
            return

        fast_ma = fast_result[-1]
        slow_ma = slow_result[-1]

        if fast_ma is None or slow_ma is None:
            return

        self.fast_ma_history.append(fast_ma)
        self.slow_ma_history.append(slow_ma)

        if len(self.fast_ma_history) < 2:
            return

        prev_fast_ma = self.fast_ma_history[-2]
        prev_slow_ma = self.slow_ma_history[-2]

        # 检测交叉
        golden_cross = prev_fast_ma <= prev_slow_ma and fast_ma > slow_ma
        death_cross = prev_fast_ma >= prev_slow_ma and fast_ma < slow_ma

        if golden_cross:
            # 金叉：平空开多
            if self.position.direction == "short" and self.position.amount < 0:
                self.cover(close_price, abs(self.position.amount), timestamp)

            if self.position.amount <= 0:
                # 平空后重新计算可用资金对应的仓位大小
                trade_amount = self.calculate_position_size(close_price)
                self.buy(close_price, trade_amount, timestamp)
                self.position.direction = "long"
                self.entry_price = close_price
                logger.debug(
                    f"金叉开多: 价格={close_price:.2f}, 数量={trade_amount:.6f}"
                )

        elif death_cross and self.enable_short:
            # 死叉：平多开空
            if self.position.direction == "long" and self.position.amount > 0:
                self.sell(close_price, self.position.amount, timestamp)

            if self.position.amount >= 0:
                # 平多后重新计算可用资金对应的仓位大小
                trade_amount = self.calculate_position_size(close_price)
                self.short(close_price, trade_amount, timestamp)
                self.position.direction = "short"
                self.entry_price = close_price
                logger.debug(
                    f"死叉开空: 价格={close_price:.2f}, 数量={trade_amount:.6f}"
                )
