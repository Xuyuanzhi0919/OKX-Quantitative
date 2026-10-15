"""
技术指标分析模块
分析趋势、动量、支撑阻力等技术面因素
"""

from typing import Dict, List
from decimal import Decimal
from loguru import logger
import asyncio


class TechnicalAnalysis:
    """技术指标分析"""

    def __init__(self, exchange):
        self.exchange = exchange

    async def analyze(self, symbol: str) -> Dict:
        """
        技术指标综合分析

        Returns:
            {
                "overall_score": 0.75,  # 0-1
                "long_score": 0.8,
                "short_score": 0.2,
                "details": {
                    "trend": {
                        "score": 0.8,
                        "analysis": "上涨趋势"
                    },
                    "momentum": {
                        "score": 0.6,
                        "rsi": 55
                    },
                    "support_resistance": {
                        "current_price": 50000,
                        "support": 49000,
                        "resistance": 51000
                    },
                    "volatility": 5.2  # %
                }
            }
        """
        try:
            # 获取K线数据
            klines = await self._get_klines(symbol, limit=100)
            if not klines or len(klines) < 50:
                logger.warning(f"K线数据不足: {len(klines) if klines else 0}")
                return self._get_default_result()

            current_price = Decimal(str(klines[-1]["c"]))

            # 并行分析各个指标
            tasks = [
                self._analyze_trend(klines),
                self._analyze_momentum(klines),
                self._analyze_support_resistance(klines, current_price),
                self._calculate_volatility(klines),
            ]

            trend, momentum, sr, volatility = await asyncio.gather(*tasks)

            # 综合评分
            trend_weight = 0.4
            momentum_weight = 0.3
            sr_weight = 0.3

            long_score = (
                trend["long_score"] * trend_weight
                + momentum["long_score"] * momentum_weight
                + sr["long_score"] * sr_weight
            )

            short_score = (
                trend["short_score"] * trend_weight
                + momentum["short_score"] * momentum_weight
                + sr["short_score"] * sr_weight
            )

            overall_score = max(long_score, short_score)

            return {
                "overall_score": round(overall_score, 3),
                "long_score": round(long_score, 3),
                "short_score": round(short_score, 3),
                "details": {
                    "trend": trend,
                    "momentum": momentum,
                    "support_resistance": sr,
                    "volatility": volatility,
                },
            }

        except Exception as e:
            logger.error(f"技术分析失败: {e}")
            return self._get_default_result()

    async def _get_klines(self, symbol: str, limit: int = 100) -> List[Dict]:
        """获取K线数据"""
        try:
            # 使用4小时K线
            klines = await self.exchange.get_kline(
                symbol=symbol, timeframe="4H", limit=limit
            )

            if not klines:
                return []

            logger.info(f"成功获取{len(klines)}条K线数据")
            return klines

        except Exception as e:
            logger.error(f"获取K线失败: {e}")
            return []

    async def _analyze_trend(self, klines: List[Dict]) -> Dict:
        """
        趋势分析
        - MA斜率
        - MACD
        - 价格与MA关系
        """
        try:
            closes = [float(k["c"]) for k in klines]

            # 计算MA
            ma20 = self._calculate_ma(closes, 20)
            ma50 = self._calculate_ma(closes, 50)

            current_price = closes[-1]

            # MA斜率
            if len(ma20) >= 5:
                ma_slope = (ma20[-1] - ma20[-5]) / ma20[-5] * 100
            else:
                ma_slope = 0

            # 价格与MA关系
            price_vs_ma20 = (current_price - ma20[-1]) / ma20[-1] * 100
            price_vs_ma50 = (current_price - ma50[-1]) / ma50[-1] * 100

            # MA多头排列
            ma_bullish = ma20[-1] > ma50[-1]

            # 综合评分
            long_signals = 0
            short_signals = 0

            # MA斜率
            if ma_slope > 1:
                long_signals += 2
            elif ma_slope < -1:
                short_signals += 2

            # 价格位置
            if price_vs_ma20 > 2:
                long_signals += 1
            elif price_vs_ma20 < -2:
                short_signals += 1

            if price_vs_ma50 > 5:
                long_signals += 1
            elif price_vs_ma50 < -5:
                short_signals += 1

            # MA排列
            if ma_bullish:
                long_signals += 1
            else:
                short_signals += 1

            total_signals = long_signals + short_signals
            if total_signals > 0:
                long_score = long_signals / total_signals
                short_score = short_signals / total_signals
            else:
                long_score = short_score = 0.5

            analysis = ""
            if ma_slope > 1:
                analysis = f"MA20向上倾斜({ma_slope:.2f}%)"
            elif ma_slope < -1:
                analysis = f"MA20向下倾斜({ma_slope:.2f}%)"
            else:
                analysis = "MA震荡"

            if ma_bullish:
                analysis += ", 多头排列"
            else:
                analysis += ", 空头排列"

            return {
                "score": max(long_score, short_score),
                "long_score": long_score,
                "short_score": short_score,
                "analysis": analysis,
                "ma20": round(ma20[-1], 2),
                "ma50": round(ma50[-1], 2),
                "ma_slope": round(ma_slope, 2),
            }

        except Exception as e:
            logger.error(f"趋势分析失败: {e}")
            return {
                "score": 0.5,
                "long_score": 0.5,
                "short_score": 0.5,
                "analysis": "分析失败",
            }

    async def _analyze_momentum(self, klines: List[Dict]) -> Dict:
        """
        动量分析
        - RSI
        - 动量
        """
        try:
            closes = [float(k["c"]) for k in klines]

            # RSI(14)
            rsi = self._calculate_rsi(closes, 14)

            # 动量 (当前价 vs N根K线前)
            momentum_period = 10
            if len(closes) > momentum_period:
                momentum = (
                    (closes[-1] - closes[-momentum_period])
                    / closes[-momentum_period]
                    * 100
                )
            else:
                momentum = 0

            # 评分
            long_score = 0.5
            short_score = 0.5

            # RSI分析
            if rsi < 30:
                # 超卖，偏多
                long_score += 0.3
            elif rsi > 70:
                # 超买，偏空
                short_score += 0.3
            elif 40 <= rsi <= 60:
                # 中性
                pass

            # 动量分析
            if momentum > 5:
                long_score += 0.2
            elif momentum < -5:
                short_score += 0.2

            # 归一化
            total = long_score + short_score
            if total > 0:
                long_score /= total
                short_score /= total

            return {
                "score": max(long_score, short_score),
                "long_score": long_score,
                "short_score": short_score,
                "rsi": round(rsi, 2),
                "momentum": round(momentum, 2),
            }

        except Exception as e:
            logger.error(f"动量分析失败: {e}")
            return {
                "score": 0.5,
                "long_score": 0.5,
                "short_score": 0.5,
                "rsi": 50,
                "momentum": 0,
            }

    async def _analyze_support_resistance(
        self, klines: List[Dict], current_price: Decimal
    ) -> Dict:
        """
        支撑/阻力位分析
        """
        try:
            highs = [float(k["h"]) for k in klines]
            lows = [float(k["l"]) for k in klines]

            # 简单支撑阻力: 近期高低点
            lookback = 20
            recent_highs = highs[-lookback:]
            recent_lows = lows[-lookback:]

            resistance = max(recent_highs)
            support = min(recent_lows)

            # 当前价格位置
            price_range = resistance - support
            if price_range > 0:
                position = (float(current_price) - support) / price_range
            else:
                position = 0.5

            # 评分
            # 接近支撑 → 偏多
            # 接近阻力 → 偏空
            if position < 0.3:
                long_score = 0.7
                short_score = 0.3
            elif position > 0.7:
                long_score = 0.3
                short_score = 0.7
            else:
                long_score = short_score = 0.5

            return {
                "score": max(long_score, short_score),
                "long_score": long_score,
                "short_score": short_score,
                "current_price": round(float(current_price), 2),
                "support": round(support, 2),
                "resistance": round(resistance, 2),
                "position": round(position, 3),  # 0-1, 0=支撑, 1=阻力
            }

        except Exception as e:
            logger.error(f"支撑阻力分析失败: {e}")
            return {
                "score": 0.5,
                "long_score": 0.5,
                "short_score": 0.5,
                "current_price": 0,
                "support": 0,
                "resistance": 0,
            }

    async def _calculate_volatility(self, klines: List[Dict]) -> float:
        """计算波动率"""
        try:
            closes = [float(k["close"]) for k in klines[-30:]]
            if len(closes) < 2:
                return 0.0

            # 计算标准差
            mean = sum(closes) / len(closes)
            variance = sum((c - mean) ** 2 for c in closes) / len(closes)
            std = variance**0.5

            # 波动率百分比
            volatility = (std / mean) * 100
            return round(volatility, 2)

        except Exception as e:
            logger.error(f"波动率计算失败: {e}")
            return 0.0

    def _calculate_ma(self, data: List[float], period: int) -> List[float]:
        """计算移动平均线"""
        if len(data) < period:
            # 数据不足，返回可用数据的平均
            return [sum(data) / len(data)] * len(data)

        ma = []
        for i in range(len(data)):
            if i < period - 1:
                ma.append(sum(data[: i + 1]) / (i + 1))
            else:
                ma.append(sum(data[i - period + 1 : i + 1]) / period)
        return ma

    def _calculate_rsi(self, closes: List[float], period: int = 14) -> float:
        """计算RSI"""
        if len(closes) < period + 1:
            return 50.0

        gains = []
        losses = []

        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def _get_default_result(self) -> Dict:
        return {
            "overall_score": 0.5,
            "long_score": 0.5,
            "short_score": 0.5,
            "details": {
                "trend": {"score": 0.5, "analysis": "数据不足"},
                "momentum": {"rsi": 50, "momentum": 0},
                "support_resistance": {},
                "volatility": 0,
            },
        }
