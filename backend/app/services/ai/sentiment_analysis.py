"""
市场情绪分析模块
分析资金费率、多空比、持仓量等情绪指标
"""

from typing import Dict
from decimal import Decimal
from loguru import logger


class SentimentAnalysis:
    """市场情绪分析"""

    def __init__(self, exchange):
        self.exchange = exchange

    async def analyze(self, symbol: str) -> Dict:
        """
        市场情绪综合分析

        Returns:
            {
                "overall_score": 0.6,
                "long_score": 0.4,
                "short_score": 0.6,
                "details": {
                    "funding_rate": 0.01,  # 正值=多头支付空头
                    "long_short_ratio": 1.2,  # 多空比
                    "open_interest_change": 5.3,  # 持仓量变化%
                    "sentiment": "bullish" | "bearish" | "neutral"
                }
            }
        """
        try:
            # 并行获取各项数据
            import asyncio

            tasks = [
                self._get_funding_rate(symbol),
                self._get_long_short_ratio(symbol),
                self._get_open_interest_change(symbol),
            ]

            funding_rate, ls_ratio, oi_change = await asyncio.gather(
                *tasks, return_exceptions=True
            )

            # 处理异常
            if isinstance(funding_rate, Exception):
                logger.error(f"获取资金费率失败: {funding_rate}")
                funding_rate = 0

            if isinstance(ls_ratio, Exception):
                logger.error(f"获取多空比失败: {ls_ratio}")
                ls_ratio = 1.0

            if isinstance(oi_change, Exception):
                logger.error(f"获取持仓量变化失败: {oi_change}")
                oi_change = 0

            # 分析各项指标
            long_score = 0.5
            short_score = 0.5
            sentiment_details = {}

            # 1. 资金费率分析
            if funding_rate > 0.01:
                # 资金费率过高 → 多头过度拥挤 → 反向信号
                short_score += 0.3
                sentiment = "bearish"
            elif funding_rate < -0.01:
                # 负费率 → 空头过度拥挤 → 反向信号
                long_score += 0.3
                sentiment = "bullish"
            elif 0 <= funding_rate <= 0.01:
                # 正常范围
                sentiment = "neutral"
            else:
                sentiment = "neutral"

            sentiment_details["funding_rate"] = round(funding_rate, 4)
            sentiment_details["funding_sentiment"] = sentiment

            # 2. 多空比分析
            if ls_ratio > 1.5:
                # 多头过多 → 可能回调
                short_score += 0.2
            elif ls_ratio < 0.67:
                # 空头过多 → 可能反弹
                long_score += 0.2
            elif 1.0 <= ls_ratio <= 1.3:
                # 健康的多头优势
                long_score += 0.1

            sentiment_details["long_short_ratio"] = round(ls_ratio, 2)

            # 3. 持仓量变化分析
            if oi_change > 10:
                # 持仓量大增 → 资金流入
                long_score += 0.1
            elif oi_change < -10:
                # 持仓量大减 → 资金流出
                short_score += 0.1

            sentiment_details["open_interest_change"] = round(oi_change, 2)

            # 归一化
            total = long_score + short_score
            if total > 0:
                long_score /= total
                short_score /= total

            # 综合情绪
            if long_score > 0.6:
                overall_sentiment = "bullish"
            elif short_score > 0.6:
                overall_sentiment = "bearish"
            else:
                overall_sentiment = "neutral"

            sentiment_details["sentiment"] = overall_sentiment

            return {
                "overall_score": max(long_score, short_score),
                "long_score": long_score,
                "short_score": short_score,
                "details": sentiment_details,
            }

        except Exception as e:
            logger.error(f"情绪分析失败: {e}")
            return self._get_default_result()

    async def _get_funding_rate(self, symbol: str) -> float:
        """获取资金费率"""
        try:
            # 获取合约信息
            ticker = await self.exchange.get_ticker(symbol)

            # OKX返回的fundingRate字段
            funding_rate = float(ticker.get("fundingRate", 0))

            # 转换为百分比
            return funding_rate * 100

        except Exception as e:
            logger.error(f"获取资金费率失败: {e}")
            return 0.0

    async def _get_long_short_ratio(self, symbol: str) -> float:
        """
        获取多空比

        注意: OKX可能不直接提供此数据
        这里提供模拟实现，实际需要从第三方获取
        """
        try:
            # 实际项目中可以从以下来源获取:
            # - Coinglass
            # - 币安合约数据
            # - 通过持仓量估算

            # 这里返回默认值1.0
            logger.warning(f"多空比数据暂不可用，使用默认值")
            return 1.0

        except Exception as e:
            logger.error(f"获取多空比失败: {e}")
            return 1.0

    async def _get_open_interest_change(self, symbol: str) -> float:
        """
        获取持仓量变化(%)

        对比当前持仓量与24小时前的变化
        """
        try:
            # 获取当前持仓量
            from app.services.exchange.okx import OKXExchange

            if isinstance(self.exchange, OKXExchange):
                # OKX可能提供持仓量数据
                ticker = await self.exchange.get_ticker(symbol)
                oi = float(ticker.get("openInt", 0))

                # 这里简化处理，实际需要对比24小时前数据
                # 返回0表示无变化
                return 0.0

            return 0.0

        except Exception as e:
            logger.error(f"获取持仓量变化失败: {e}")
            return 0.0

    def _get_default_result(self) -> Dict:
        return {
            "overall_score": 0.5,
            "long_score": 0.5,
            "short_score": 0.5,
            "details": {
                "funding_rate": 0,
                "long_short_ratio": 1.0,
                "open_interest_change": 0,
                "sentiment": "neutral",
            },
        }
