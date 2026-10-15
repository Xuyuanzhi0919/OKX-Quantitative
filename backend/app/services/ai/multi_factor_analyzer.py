"""
多因子市场分析器
结合技术指标、市场情绪、AI分析进行综合决策
"""

from typing import Dict, Optional, Tuple
from decimal import Decimal
from loguru import logger
from datetime import datetime, timedelta
import asyncio


class MultiFactorAnalyzer:
    """
    多因子分析器

    权重分配:
    - 技术指标: 40%
    - 市场情绪: 30%
    - AI分析: 30%
    """

    def __init__(self, exchange, api_key: Optional[str] = None):
        self.exchange = exchange
        self.api_key = api_key

    async def analyze(self, symbol: str) -> Dict:
        """
        综合分析交易对

        Returns:
            {
                "symbol": "BTC-USDT-SWAP",
                "timestamp": "2026-02-04T12:00:00Z",
                "decision": "long" | "short" | "wait",
                "confidence": 0.75,  # 0-1
                "scores": {
                    "long_score": 0.72,
                    "short_score": 0.23,
                    "wait_score": 0.05
                },
                "factors": {
                    "technical": {
                        "score": 0.8,
                        "weight": 0.4,
                        "details": {...}
                    },
                    "sentiment": {
                        "score": 0.6,
                        "weight": 0.3,
                        "details": {...}
                    },
                    "ai": {
                        "score": 0.75,
                        "weight": 0.3,
                        "analysis": "..."
                    }
                },
                "risk_level": "low" | "medium" | "high",
                "suggested_strategy": "swing_long" | "swing_short",
                "reasoning": "详细说明"
            }
        """
        try:
            # 并行执行三个因子的分析
            technical_task = self._analyze_technical(symbol)
            sentiment_task = self._analyze_sentiment(symbol)
            ai_task = self._analyze_ai(symbol)

            technical, sentiment, ai = await asyncio.gather(
                technical_task, sentiment_task, ai_task, return_exceptions=True
            )

            # 处理异常
            if isinstance(technical, Exception):
                logger.error(f"技术指标分析失败: {technical}")
                technical = self._get_default_technical()
            if isinstance(sentiment, Exception):
                logger.error(f"市场情绪分析失败: {sentiment}")
                sentiment = self._get_default_sentiment()
            if isinstance(ai, Exception):
                logger.error(f"AI分析失败: {ai}")
                ai = self._get_default_ai()

            # 计算综合得分
            long_score = (
                technical["long_score"] * technical["weight"]
                + sentiment["long_score"] * sentiment["weight"]
                + ai["long_score"] * ai["weight"]
            )

            short_score = (
                technical["short_score"] * technical["weight"]
                + sentiment["short_score"] * sentiment["weight"]
                + ai["short_score"] * ai["weight"]
            )

            wait_score = max(0, 1 - long_score - short_score)

            # 归一化
            total = long_score + short_score + wait_score
            if total > 0:
                long_score /= total
                short_score /= total
                wait_score /= total

            # 决策逻辑
            min_confidence = 0.6  # 最低信心度
            decision = "wait"
            confidence = 0
            suggested_strategy = None

            if long_score >= min_confidence and long_score > short_score * 1.5:
                decision = "long"
                confidence = long_score
                suggested_strategy = "swing_long"
            elif short_score >= min_confidence and short_score > long_score * 1.5:
                decision = "short"
                confidence = short_score
                suggested_strategy = "swing_short"
            else:
                decision = "wait"
                confidence = wait_score

            # 风险等级
            volatility = technical.get("details", {}).get("volatility", 0)
            if volatility < 3:
                risk_level = "low"
            elif volatility < 7:
                risk_level = "medium"
            else:
                risk_level = "high"

            # 生成说明
            reasoning = self._generate_reasoning(
                decision, confidence, technical, sentiment, ai
            )

            return {
                "symbol": symbol,
                "timestamp": datetime.now().isoformat(),
                "decision": decision,
                "confidence": round(confidence, 3),
                "scores": {
                    "long_score": round(long_score, 3),
                    "short_score": round(short_score, 3),
                    "wait_score": round(wait_score, 3),
                },
                "factors": {"technical": technical, "sentiment": sentiment, "ai": ai},
                "risk_level": risk_level,
                "suggested_strategy": suggested_strategy,
                "reasoning": reasoning,
            }

        except Exception as e:
            logger.error(f"综合分析失败: {e}")
            return self._get_default_analysis(symbol)

    async def _analyze_technical(self, symbol: str) -> Dict:
        """
        技术指标分析 (40%权重)

        分析内容:
        - 趋势指标: MA, MACD, EMA
        - 动量指标: RSI, CCI
        - 支撑/阻力位
        """
        try:
            from app.services.ai.technical_analysis import TechnicalAnalysis

            ta = TechnicalAnalysis(self.exchange)
            result = await ta.analyze(symbol)

            return {
                "score": result.get("overall_score", 0.5),
                "weight": 0.4,
                "long_score": result.get("long_score", 0.5),
                "short_score": result.get("short_score", 0.5),
                "details": result.get("details", {}),
            }
        except Exception as e:
            logger.error(f"技术分析失败: {e}")
            return self._get_default_technical()

    async def _analyze_sentiment(self, symbol: str) -> Dict:
        """
        市场情绪分析 (30%权重)

        分析内容:
        - 资金费率 (Funding Rate)
        - 多空比 (Long/Short Ratio)
        - 持仓量变化 (Open Interest Change)
        """
        try:
            from app.services.ai.sentiment_analysis import SentimentAnalysis

            sa = SentimentAnalysis(self.exchange)
            result = await sa.analyze(symbol)

            return {
                "score": result.get("overall_score", 0.5),
                "weight": 0.3,
                "long_score": result.get("long_score", 0.5),
                "short_score": result.get("short_score", 0.5),
                "details": result.get("details", {}),
            }
        except Exception as e:
            logger.error(f"情绪分析失败: {e}")
            return self._get_default_sentiment()

    async def _analyze_ai(self, symbol: str) -> Dict:
        """
        AI深度分析 (30%权重)

        分析内容:
        - 市场情绪分析
        - 量价关系分析
        - 趋势判断
        """
        try:
            # 检查API key
            if not self.api_key:
                logger.warning("未配置AI API key，跳过AI分析")
                return {
                    "score": 0.5,
                    "weight": 0.3,
                    "long_score": 0.5,
                    "short_score": 0.5,
                    "analysis": "未配置AI服务",
                    "details": {},
                }

            logger.info(
                f"开始AI分析: {symbol}, API key length: {len(self.api_key) if self.api_key else 0}"
            )

            from app.services.ai.llm_client import DeepSeekLLM

            # 创建LLM客户端
            llm_client = DeepSeekLLM(api_key=self.api_key)

            # 构建分析提示词
            prompt = f"""请分析{symbol}的市场趋势并给出做多/做空建议。

请考虑以下因素:
1. 当前市场趋势(上涨/下跌/震荡)
2. 支撑位和阻力位
3. 市场情绪(贪婪/恐惧/中性)
4. 风险等级

请以JSON格式返回分析结果:
{{
    "trend": "bullish" | "bearish" | "neutral",
    "long_probability": 0.7,
    "short_probability": 0.3,
    "confidence": 0.75,
    "analysis": "详细分析说明...",
    "risk_level": "low"
}}

请只返回JSON，不要有其他内容。"""

            try:
                # 调用LLM
                logger.info("调用DeepSeek API...")
                messages = [
                    {
                        "role": "system",
                        "content": "你是一位专业的加密货币市场分析师。请以JSON格式返回分析结果。",
                    },
                    {"role": "user", "content": prompt},
                ]
                response = await llm_client.chat_completion(
                    messages, temperature=0.7, max_tokens=500
                )
                logger.info(f"DeepSeek API响应长度: {len(response) if response else 0}")

                # 解析响应
                import json

                # 尝试提取JSON（如果响应包含其他文字）
                import re

                json_match = re.search(r"\{[^}]*\}", response)
                if json_match:
                    json_str = json_match.group(0)
                    result = json.loads(json_str)
                else:
                    result = json.loads(response)

                logger.info(
                    f"AI分析结果: trend={result.get('trend')}, confidence={result.get('confidence')}"
                )

                return {
                    "score": result.get("confidence", 0.5),
                    "weight": 0.3,
                    "long_score": result.get("long_probability", 0.5),
                    "short_score": result.get("short_probability", 0.5),
                    "analysis": result.get("analysis", ""),
                    "details": result,
                }
            except Exception as e:
                logger.error(f"AI分析调用失败: {e}", exc_info=True)
                return {
                    "score": 0.5,
                    "weight": 0.3,
                    "long_score": 0.5,
                    "short_score": 0.5,
                    "analysis": f"AI分析失败: {str(e)}",
                    "details": {},
                }

        except Exception as e:
            logger.error(f"AI分析失败: {e}", exc_info=True)
            return self._get_default_ai()

    def _generate_reasoning(
        self,
        decision: str,
        confidence: float,
        technical: Dict,
        sentiment: Dict,
        ai: Dict,
    ) -> str:
        """生成决策说明"""
        reasons = []

        # 技术面
        tech_score = technical.get("score", 0.5)
        if tech_score > 0.6:
            reasons.append(
                f"技术指标{'看涨' if technical.get('long_score', 0) > technical.get('short_score', 0) else '看跌'} (得分: {tech_score:.2f})"
            )

        # 情绪面
        sent_score = sentiment.get("score", 0.5)
        sent_details = sentiment.get("details", {})
        if "funding_rate" in sent_details:
            fr = sent_details["funding_rate"]
            if fr > 0.01:
                reasons.append(f"资金费率偏高({fr:.3%}), 多头过度拥挤")
            elif fr < -0.01:
                reasons.append(f"资金费率为负({fr:.3%}), 空头过度拥挤")

        # AI分析
        ai_analysis = ai.get("analysis", "")
        if ai_analysis:
            reasons.append(f"AI: {ai_analysis[:100]}...")

        # 决策
        if decision == "long":
            reasoning = f"建议做多 (信心度: {confidence:.1%})。"
        elif decision == "short":
            reasoning = f"建议做空 (信心度: {confidence:.1%})。"
        else:
            reasoning = f"建议观望 (信号不明确，做多得分: {technical.get('long_score', 0):.2f}, 做空得分: {technical.get('short_score', 0):.2f})。"

        if reasons:
            reasoning += " " + " ".join(reasons)

        return reasoning

    def _get_default_technical(self) -> Dict:
        return {
            "score": 0.5,
            "weight": 0.4,
            "long_score": 0.5,
            "short_score": 0.5,
            "details": {},
        }

    def _get_default_sentiment(self) -> Dict:
        return {
            "score": 0.5,
            "weight": 0.3,
            "long_score": 0.5,
            "short_score": 0.5,
            "details": {},
        }

    def _get_default_ai(self) -> Dict:
        return {
            "score": 0.5,
            "weight": 0.3,
            "long_score": 0.5,
            "short_score": 0.5,
            "analysis": "AI分析暂不可用",
            "details": {},
        }

    def _get_default_analysis(self, symbol: str) -> Dict:
        return {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "decision": "wait",
            "confidence": 0.0,
            "scores": {"long_score": 0.33, "short_score": 0.33, "wait_score": 0.34},
            "factors": {
                "technical": self._get_default_technical(),
                "sentiment": self._get_default_sentiment(),
                "ai": self._get_default_ai(),
            },
            "risk_level": "high",
            "suggested_strategy": None,
            "reasoning": "分析失败，建议人工判断",
        }
