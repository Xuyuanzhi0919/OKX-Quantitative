"""
AI市场分析器 - 智能分析市场并提供交易建议

功能:
1. 技术指标分析 (RSI, MACD, 布林带等)
2. 市场情绪分析 (成交量, 波动率等)
3. 风险评估
4. 加仓/减仓建议
"""

from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from loguru import logger
from datetime import datetime, timedelta


class AIMarketAnalyzer:
    """AI市场分析器"""

    def __init__(self):
        self.analysis_cache = {}  # 缓存分析结果
        self.cache_duration = 60  # 缓存时长(秒)

    async def analyze_market(
        self,
        symbol: str,
        current_price: Decimal,
        entry_price: Optional[Decimal] = None,
        position_size: Optional[Decimal] = None,
        kline_data: Optional[List[Dict]] = None,
        ticker_data: Optional[Dict] = None,
    ) -> Dict:
        """
        综合分析市场状况

        Args:
            symbol: 交易对
            current_price: 当前价格
            entry_price: 入场价格(如有持仓)
            position_size: 持仓大小(如有持仓)
            kline_data: K线数据(可选)
            ticker_data: 行情数据(可选)

        Returns:
            {
                "action": "hold|buy|sell|add|reduce",  # 建议操作
                "confidence": 0.85,  # 信心度 0-1
                "reason": "原因说明",
                "risk_level": "low|medium|high",  # 风险等级
                "indicators": {
                    "rsi": 65,
                    "trend": "up",
                    "volatility": "medium"
                },
                "position_advice": {
                    "action": "add|reduce|hold",
                    "ratio": 0.5  # 建议调整比例
                }
            }
        """
        try:
            logger.info(f"🤖 AI开始分析 {symbol} 市场...")

            # 1. 基础市场分析
            market_sentiment = await self._analyze_market_sentiment(ticker_data or {})

            # 2. 技术指标分析(如果有K线数据)
            technical_signals = await self._analyze_technical_indicators(
                kline_data or []
            )

            # 3. 持仓分析(如果有持仓)
            position_analysis = await self._analyze_position(
                current_price, entry_price, position_size
            )

            # 4. 风险评估
            risk_assessment = await self._assess_risk(
                market_sentiment, technical_signals, position_analysis
            )

            # 5. 综合决策
            decision = await self._make_decision(
                market_sentiment, technical_signals, position_analysis, risk_assessment
            )

            result = {
                "action": decision["action"],
                "confidence": decision["confidence"],
                "reason": decision["reason"],
                "risk_level": risk_assessment["level"],
                "indicators": {
                    "sentiment": market_sentiment["score"],
                    "technical": technical_signals.get("score", 0.5),
                    "volatility": market_sentiment["volatility"],
                },
                "position_advice": decision.get(
                    "position_advice", {"action": "hold", "ratio": 0}
                ),
                "timestamp": datetime.now().isoformat(),
            }

            logger.success(
                f"✅ AI分析完成: {result['action']} (信心度: {result['confidence']:.0%})"
            )
            return result

        except Exception as e:
            logger.error(f"❌ AI分析失败: {e}")
            return {
                "action": "hold",
                "confidence": 0,
                "reason": f"分析失败: {str(e)}",
                "risk_level": "unknown",
                "indicators": {},
                "position_advice": {"action": "hold", "ratio": 0},
            }

    async def _analyze_market_sentiment(self, ticker_data: Dict) -> Dict:
        """
        分析市场情绪

        基于:
        - 24h涨跌幅
        - 24h成交量变化
        - 24h波动率
        """
        try:
            # 提取数据
            last_price = Decimal(str(ticker_data.get("last", 0)))
            open24h = Decimal(str(ticker_data.get("open24h", 0)))
            high24h = Decimal(str(ticker_data.get("high24h", 0)))
            low24h = Decimal(str(ticker_data.get("low24h", 0)))
            vol24h = Decimal(str(ticker_data.get("vol24h", 0)))
            volCcy24h = Decimal(str(ticker_data.get("volCcy24h", 0)))

            sentiment_score = 0.5  # 中性
            signals = []

            # 1. 价格变化分析
            if open24h > 0:
                price_change_pct = (last_price - open24h) / open24h * 100

                if price_change_pct > 5:
                    sentiment_score += 0.2
                    signals.append(f"24h大涨 {price_change_pct:.2f}%")
                elif price_change_pct > 2:
                    sentiment_score += 0.1
                    signals.append(f"24h上涨 {price_change_pct:.2f}%")
                elif price_change_pct < -5:
                    sentiment_score -= 0.2
                    signals.append(f"24h大跌 {price_change_pct:.2f}%")
                elif price_change_pct < -2:
                    sentiment_score -= 0.1
                    signals.append(f"24h下跌 {price_change_pct:.2f}%")

            # 2. 波动率分析
            if open24h > 0:
                volatility = (high24h - low24h) / open24h * 100

                if volatility > 10:
                    volatility_level = "extreme"
                    signals.append(f"极高波动 {volatility:.2f}%")
                elif volatility > 5:
                    volatility_level = "high"
                    signals.append(f"高波动 {volatility:.2f}%")
                elif volatility > 2:
                    volatility_level = "medium"
                else:
                    volatility_level = "low"
                    sentiment_score -= 0.05  # 低波动降低信心
                    signals.append(f"低波动 {volatility:.2f}%")
            else:
                volatility_level = "unknown"

            # 3. 成交量分析(简化版,实际需要历史数据对比)
            if volCcy24h > 1000000:  # 100万USDT以上
                sentiment_score += 0.05
                signals.append("成交活跃")

            # 限制在0-1之间
            sentiment_score = max(0, min(1, sentiment_score))

            return {
                "score": sentiment_score,
                "volatility": volatility_level,
                "signals": signals,
                "trend": (
                    "bullish"
                    if sentiment_score > 0.6
                    else "bearish" if sentiment_score < 0.4 else "neutral"
                ),
            }

        except Exception as e:
            logger.error(f"市场情绪分析失败: {e}")
            return {
                "score": 0.5,
                "volatility": "unknown",
                "signals": [],
                "trend": "neutral",
            }

    async def _analyze_technical_indicators(self, kline_data: List[Dict]) -> Dict:
        """
        技术指标分析

        如果有K线数据,计算:
        - RSI (相对强弱指标)
        - 均线趋势
        - 支撑阻力位

        TODO: 后续可以接入专业的技术分析库(如 TA-Lib)
        """
        if not kline_data or len(kline_data) < 14:
            return {"score": 0.5, "signals": ["K线数据不足,跳过技术分析"]}

        try:
            # 简化版RSI计算(实际应该用专业库)
            # 这里先返回中性评分
            return {"score": 0.5, "rsi": None, "signals": ["技术分析功能待完善"]}

        except Exception as e:
            logger.error(f"技术指标分析失败: {e}")
            return {"score": 0.5, "signals": []}

    async def _analyze_position(
        self,
        current_price: Decimal,
        entry_price: Optional[Decimal],
        position_size: Optional[Decimal],
    ) -> Dict:
        """
        持仓分析

        分析当前持仓状况,给出加仓/减仓建议
        """
        if not entry_price or not position_size:
            return {"has_position": False, "profit_pct": 0, "risk_level": "none"}

        try:
            # 计算盈亏
            profit_pct = (current_price - entry_price) / entry_price * 100

            # 风险评估
            if profit_pct > 10:
                risk_level = "low"  # 大幅盈利,风险低
                suggestion = "考虑部分止盈"
            elif profit_pct > 5:
                risk_level = "low"
                suggestion = "持有观望"
            elif profit_pct > -3:
                risk_level = "medium"
                suggestion = "持有观望"
            elif profit_pct > -5:
                risk_level = "medium"
                suggestion = "接近止损线,准备止损"
            else:
                risk_level = "high"
                suggestion = "建议止损"

            return {
                "has_position": True,
                "profit_pct": float(profit_pct),
                "risk_level": risk_level,
                "suggestion": suggestion,
            }

        except Exception as e:
            logger.error(f"持仓分析失败: {e}")
            return {"has_position": True, "profit_pct": 0, "risk_level": "unknown"}

    async def _assess_risk(
        self, market_sentiment: Dict, technical_signals: Dict, position_analysis: Dict
    ) -> Dict:
        """
        综合风险评估
        """
        risk_score = 0  # 0=低风险, 10=高风险

        # 1. 市场风险
        volatility = market_sentiment.get("volatility", "medium")
        if volatility == "extreme":
            risk_score += 4
        elif volatility == "high":
            risk_score += 3
        elif volatility == "low":
            risk_score += 1  # 低波动也有风险(流动性差)

        # 2. 持仓风险
        if position_analysis.get("has_position"):
            profit_pct = position_analysis.get("profit_pct", 0)
            if profit_pct < -5:
                risk_score += 3  # 深度亏损
            elif profit_pct < -2:
                risk_score += 2

        # 3. 市场情绪风险
        sentiment_score = market_sentiment.get("score", 0.5)
        if sentiment_score < 0.3:  # 极度悲观
            risk_score += 2
        elif sentiment_score > 0.8:  # 极度乐观(可能过热)
            risk_score += 1

        # 确定风险等级
        if risk_score >= 7:
            level = "high"
        elif risk_score >= 4:
            level = "medium"
        else:
            level = "low"

        return {
            "level": level,
            "score": risk_score,
            "factors": [
                f"市场波动: {volatility}",
                f"市场情绪: {market_sentiment.get('trend', 'neutral')}",
                f"持仓状态: {position_analysis.get('suggestion', 'N/A')}",
            ],
        }

    async def _make_decision(
        self,
        market_sentiment: Dict,
        technical_signals: Dict,
        position_analysis: Dict,
        risk_assessment: Dict,
    ) -> Dict:
        """
        综合决策引擎

        基于所有分析结果,给出最终建议
        """
        # 提取关键指标
        sentiment_score = market_sentiment.get("score", 0.5)
        volatility = market_sentiment.get("volatility", "medium")
        trend = market_sentiment.get("trend", "neutral")
        has_position = position_analysis.get("has_position", False)
        profit_pct = position_analysis.get("profit_pct", 0)
        risk_level = risk_assessment.get("level", "medium")

        # 决策逻辑
        action = "hold"
        confidence = 0.5
        reason = ""
        position_advice = {"action": "hold", "ratio": 0}

        # 场景1: 无持仓 - 考虑开仓
        if not has_position:
            if sentiment_score > 0.65 and risk_level != "high":
                action = "buy"
                confidence = sentiment_score
                reason = f"市场情绪积极({sentiment_score:.0%}), 趋势{trend}, 建议开仓"
            elif sentiment_score < 0.35:
                action = "hold"
                confidence = 0.7
                reason = f"市场情绪低迷({sentiment_score:.0%}), 暂不开仓"
            else:
                action = "hold"
                confidence = 0.6
                reason = "市场中性,观望为主"

        # 场景2: 有持仓 - 考虑加仓/减仓
        else:
            # 盈利情况下
            if profit_pct > 10:
                # 大幅盈利
                if sentiment_score > 0.7:
                    action = "hold"
                    position_advice = {"action": "add", "ratio": 0.3}
                    confidence = 0.75
                    reason = f"已盈利{profit_pct:.2f}%, 市场强势, 可考虑加仓30%"
                else:
                    action = "sell"
                    position_advice = {"action": "reduce", "ratio": 0.5}
                    confidence = 0.8
                    reason = f"已盈利{profit_pct:.2f}%, 市场转弱, 建议减仓50%止盈"

            elif profit_pct > 5:
                # 中等盈利
                action = "hold"
                confidence = 0.7
                reason = f"盈利{profit_pct:.2f}%, 持有观望"

            elif profit_pct > -3:
                # 小幅盈亏
                if sentiment_score > 0.7:
                    position_advice = {"action": "add", "ratio": 0.2}
                    confidence = 0.65
                    reason = f"当前{profit_pct:+.2f}%, 市场转强, 可小幅加仓20%"
                else:
                    action = "hold"
                    confidence = 0.6
                    reason = f"当前{profit_pct:+.2f}%, 持有观望"

            elif profit_pct > -5:
                # 接近止损
                if sentiment_score > 0.65:
                    action = "hold"
                    confidence = 0.6
                    reason = f"亏损{profit_pct:.2f}%, 但市场回暖, 可继续持有"
                else:
                    action = "sell"
                    position_advice = {"action": "reduce", "ratio": 0.5}
                    confidence = 0.75
                    reason = f"亏损{profit_pct:.2f}%, 市场弱势, 建议减仓50%"

            else:
                # 深度亏损
                action = "sell"
                confidence = 0.9
                reason = f"亏损{profit_pct:.2f}%, 建议止损"

        return {
            "action": action,
            "confidence": confidence,
            "reason": reason,
            "position_advice": position_advice,
        }


# 全局实例
ai_analyzer = AIMarketAnalyzer()
