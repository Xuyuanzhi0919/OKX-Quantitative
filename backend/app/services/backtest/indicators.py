"""
技术指标计算模块
提供常用的技术分析指标计算功能
"""

from typing import List, Dict, Optional, Tuple
from decimal import Decimal
import math


class TechnicalIndicators:
    """技术指标计算类"""

    @staticmethod
    def SMA(data: List[float], period: int) -> List[Optional[float]]:
        """
        简单移动平均 (Simple Moving Average)

        Args:
            data: 价格数据列表
            period: 周期

        Returns:
            移动平均值列表，前period-1个值为None
        """
        if len(data) < period:
            return [None] * len(data)

        result = [None] * (period - 1)
        for i in range(period - 1, len(data)):
            avg = sum(data[i - period + 1 : i + 1]) / period
            result.append(avg)

        return result

    @staticmethod
    def EMA(data: List[float], period: int) -> List[Optional[float]]:
        """
        指数移动平均 (Exponential Moving Average)

        Args:
            data: 价格数据列表
            period: 周期

        Returns:
            EMA值列表，前period-1个值为None
        """
        if len(data) < period:
            return [None] * len(data)

        result = [None] * (period - 1)

        # 第一个EMA值使用SMA
        sma = sum(data[:period]) / period
        result.append(sma)

        # 平滑因子
        multiplier = 2 / (period + 1)

        for i in range(period, len(data)):
            ema = (data[i] - result[-1]) * multiplier + result[-1]
            result.append(ema)

        return result

    @staticmethod
    def RSI(close_prices: List[float], period: int = 14) -> List[Optional[float]]:
        """
        相对强弱指标 (Relative Strength Index)

        Args:
            close_prices: 收盘价列表
            period: 周期，默认14

        Returns:
            RSI值列表(0-100)，前period个值为None
        """
        if len(close_prices) < period + 1:
            return [None] * len(close_prices)

        # 计算价格变化
        changes = [
            close_prices[i] - close_prices[i - 1] for i in range(1, len(close_prices))
        ]

        result = [None]  # 第一个值无法计算变化

        # 分离上涨和下跌
        gains = [max(0, c) for c in changes]
        losses = [abs(min(0, c)) for c in changes]

        # 前period个值无法计算RSI
        result.extend([None] * (period - 1))

        # 第一个RSI使用简单平均
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100 - (100 / (1 + rs)))

        # 后续使用指数平滑
        for i in range(period, len(changes)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

            if avg_loss == 0:
                result.append(100.0)
            else:
                rs = avg_gain / avg_loss
                result.append(100 - (100 / (1 + rs)))

        return result

    @staticmethod
    def ATR(
        high: List[float], low: List[float], close: List[float], period: int = 14
    ) -> List[Optional[float]]:
        """
        平均真实波幅 (Average True Range)

        Args:
            high: 最高价列表
            low: 最低价列表
            close: 收盘价列表
            period: 周期，默认14

        Returns:
            ATR值列表
        """
        if len(high) < period + 1:
            return [None] * len(high)

        # 计算真实波幅
        tr_list = [None]  # 第一个值无法计算
        for i in range(1, len(high)):
            tr = max(
                high[i] - low[i],  # 当日最高-最低
                abs(high[i] - close[i - 1]),  # 当日最高-昨日收盘
                abs(low[i] - close[i - 1]),  # 当日最低-昨日收盘
            )
            tr_list.append(tr)

        # 计算ATR
        result = [None] * period

        # 第一个ATR使用简单平均
        first_atr = sum(tr_list[1 : period + 1]) / period
        result.append(first_atr)

        # 后续使用指数平滑
        atr = first_atr
        for i in range(period + 1, len(high)):
            atr = (atr * (period - 1) + tr_list[i]) / period
            result.append(atr)

        return result

    @staticmethod
    def BollingerBands(
        close: List[float], period: int = 20, std_dev: float = 2.0
    ) -> Dict[str, List[Optional[float]]]:
        """
        布林带 (Bollinger Bands)

        Args:
            close: 收盘价列表
            period: 周期，默认20
            std_dev: 标准差倍数，默认2.0

        Returns:
            包含upper、middle、lower三个列表的字典
        """
        n = len(close)
        middle = [None] * n
        upper = [None] * n
        lower = [None] * n

        for i in range(period - 1, n):
            # 计算SMA
            window = close[i - period + 1 : i + 1]
            sma = sum(window) / period
            middle[i] = sma

            # 计算标准差
            variance = sum((x - sma) ** 2 for x in window) / period
            std = math.sqrt(variance)

            upper[i] = sma + std_dev * std
            lower[i] = sma - std_dev * std

        return {"upper": upper, "middle": middle, "lower": lower}

    @staticmethod
    def MACD(
        close: List[float],
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> Dict[str, List[Optional[float]]]:
        """
        MACD指标 (Moving Average Convergence Divergence)

        Args:
            close: 收盘价列表
            fast_period: 快线周期，默认12
            slow_period: 慢线周期，默认26
            signal_period: 信号线周期，默认9

        Returns:
            包含macd、signal、histogram三个列表的字典
        """
        n = len(close)

        # 计算快慢EMA
        fast_ema = TechnicalIndicators.EMA(close, fast_period)
        slow_ema = TechnicalIndicators.EMA(close, slow_period)

        # 计算MACD线（快线-慢线）
        macd_line = [None] * n
        for i in range(n):
            if fast_ema[i] is not None and slow_ema[i] is not None:
                macd_line[i] = fast_ema[i] - slow_ema[i]

        # 计算信号线（MACD的EMA）
        # 过滤None值
        valid_macd = [(i, v) for i, v in enumerate(macd_line) if v is not None]
        if len(valid_macd) < signal_period:
            return {"macd": macd_line, "signal": [None] * n, "histogram": [None] * n}

        signal_line = [None] * n
        first_valid_idx = valid_macd[0][0]

        # 第一个信号值使用SMA
        first_signal = sum(v for _, v in valid_macd[:signal_period]) / signal_period
        signal_line[first_valid_idx + signal_period - 1] = first_signal

        # 后续使用EMA
        multiplier = 2 / (signal_period + 1)
        prev_signal = first_signal

        for i in range(signal_period, len(valid_macd)):
            idx, macd_val = valid_macd[i]
            current_signal = (macd_val - prev_signal) * multiplier + prev_signal
            signal_line[idx] = current_signal
            prev_signal = current_signal

        # 计算柱状图
        histogram = [None] * n
        for i in range(n):
            if macd_line[i] is not None and signal_line[i] is not None:
                histogram[i] = macd_line[i] - signal_line[i]

        return {"macd": macd_line, "signal": signal_line, "histogram": histogram}

    @staticmethod
    def Highest(data: List[float], period: int) -> List[Optional[float]]:
        """
        滚动最高值

        Args:
            data: 数据列表
            period: 周期

        Returns:
            滚动最高值列表
        """
        if len(data) < period:
            return [None] * len(data)

        result = [None] * (period - 1)
        for i in range(period - 1, len(data)):
            result.append(max(data[i - period + 1 : i + 1]))

        return result

    @staticmethod
    def Lowest(data: List[float], period: int) -> List[Optional[float]]:
        """
        滚动最低值

        Args:
            data: 数据列表
            period: 周期

        Returns:
            滚动最低值列表
        """
        if len(data) < period:
            return [None] * len(data)

        result = [None] * (period - 1)
        for i in range(period - 1, len(data)):
            result.append(min(data[i - period + 1 : i + 1]))

        return result

    @staticmethod
    def CrossAbove(
        fast: List[Optional[float]], slow: List[Optional[float]]
    ) -> List[bool]:
        """
        检测上穿信号

        Args:
            fast: 快线数据
            slow: 慢线数据

        Returns:
            布尔列表，True表示发生上穿
        """
        n = len(fast)
        result = [False] * n

        for i in range(1, n):
            if fast[i] is None or slow[i] is None:
                continue
            if fast[i - 1] is None or slow[i - 1] is None:
                continue

            # 当前快线>慢线 且 之前快线<=慢线
            if fast[i] > slow[i] and fast[i - 1] <= slow[i - 1]:
                result[i] = True

        return result

    @staticmethod
    def CrossBelow(
        fast: List[Optional[float]], slow: List[Optional[float]]
    ) -> List[bool]:
        """
        检测下穿信号

        Args:
            fast: 快线数据
            slow: 慢线数据

        Returns:
            布尔列表，True表示发生下穿
        """
        n = len(fast)
        result = [False] * n

        for i in range(1, n):
            if fast[i] is None or slow[i] is None:
                continue
            if fast[i - 1] is None or slow[i - 1] is None:
                continue

            # 当前快线<慢线 且 之前快线>=慢线
            if fast[i] < slow[i] and fast[i - 1] >= slow[i - 1]:
                result[i] = True

        return result


class KlineBuffer:
    """
    K线数据缓冲区
    用于策略运行时维护历史数据
    """

    def __init__(self, max_size: int = 500):
        """
        初始化缓冲区

        Args:
            max_size: 最大缓存数量
        """
        self.max_size = max_size
        self.timestamps: List[int] = []
        self.opens: List[float] = []
        self.highs: List[float] = []
        self.lows: List[float] = []
        self.closes: List[float] = []
        self.volumes: List[float] = []

    def add(self, kline: Dict):
        """
        添加K线数据

        Args:
            kline: K线字典，包含 timestamp, open, high, low, close, volume
        """
        self.timestamps.append(kline.get("timestamp", 0))
        self.opens.append(float(kline.get("open", 0)))
        self.highs.append(float(kline.get("high", 0)))
        self.lows.append(float(kline.get("low", 0)))
        self.closes.append(float(kline.get("close", 0)))
        self.volumes.append(float(kline.get("volume", 0)))

        # 超出最大容量时移除最旧数据
        if len(self.closes) > self.max_size:
            self.timestamps.pop(0)
            self.opens.pop(0)
            self.highs.pop(0)
            self.lows.pop(0)
            self.closes.pop(0)
            self.volumes.pop(0)

    def __len__(self) -> int:
        return len(self.closes)

    def get_closes(self) -> List[float]:
        """获取收盘价列表"""
        return self.closes.copy()

    def get_highs(self) -> List[float]:
        """获取最高价列表"""
        return self.highs.copy()

    def get_lows(self) -> List[float]:
        """获取最低价列表"""
        return self.lows.copy()

    def get_last(self) -> Optional[Dict]:
        """获取最后一条K线"""
        if len(self.closes) == 0:
            return None
        return {
            "timestamp": self.timestamps[-1],
            "open": self.opens[-1],
            "high": self.highs[-1],
            "low": self.lows[-1],
            "close": self.closes[-1],
            "volume": self.volumes[-1],
        }
