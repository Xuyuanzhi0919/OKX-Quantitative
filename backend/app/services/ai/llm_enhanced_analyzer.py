"""
LLM增强的AI分析器
结合规则引擎、技术分析和DeepSeek大语言模型
"""

from typing import Dict, Optional, List
from decimal import Decimal
from loguru import logger
from datetime import datetime, timedelta

from .llm_client import deepseek_llm
from .news_fetcher import news_fetcher
from .ai_analyzer import ai_analyzer  # 原有的规则AI分析器


class LLMEnhancedAnalyzer:
    """LLM增强的AI分析器"""

    def __init__(self):
        self.llm_client = deepseek_llm
        self.news_fetcher = news_fetcher
        self.rule_analyzer = ai_analyzer

        # LLM分析缓存 (避免频繁调用API)
        self.llm_cache = {}
        self.cache_duration = timedelta(minutes=5)

        logger.info("LLM增强分析器初始化完成")

    async def analyze_market_with_llm(
        self,
        symbol: str,
        current_price: Decimal,
        ticker_data: Dict,
        use_llm: bool = True,
        use_news: bool = True,
    ) -> Dict:
        """
        使用LLM增强的市场分析

        Args:
            symbol: 交易对符号
            current_price: 当前价格
            ticker_data: 行情数据
            use_llm: 是否使用LLM分析
            use_news: 是否获取新闻

        Returns:
            增强的分析结果
        """
        logger.info(f"开始LLM增强分析: {symbol}")

        # 1. 获取基础规则分析
        rule_result = await self.rule_analyzer.analyze_market(
            symbol=symbol, current_price=current_price, ticker_data=ticker_data
        )
        logger.info(
            f"规则分析完成: {rule_result['action']} (信心度: {rule_result['confidence']*100:.1f}%)"
        )

        # 如果不使用LLM,直接返回规则分析结果
        if not use_llm:
            return rule_result

        # 2. 获取新闻数据
        news_headlines = []
        if use_news:
            try:
                news_list = await self.news_fetcher.fetch_all_news(
                    symbol=symbol, limit=5, use_mock=False  # 使用真实新闻
                )
                news_headlines = [news["title"] for news in news_list[:5]]
                logger.info(f"获取到 {len(news_headlines)} 条新闻标题")
            except Exception as e:
                logger.warning(f"新闻获取失败: {e}, 继续分析")

        # 3. 检查LLM分析缓存
        cache_key = f"{symbol}_{current_price}"
        cached_result = self._get_cached_llm_result(cache_key)
        if cached_result:
            logger.info("使用缓存的LLM分析结果")
            return self._merge_analysis(rule_result, cached_result)

        # 4. 调用LLM进行市场情绪分析
        try:
            # 提取市场数据
            price_change_24h = float(ticker_data.get("sodUtc8", "0"))
            volume_24h = float(ticker_data.get("volCcy24h", "0"))
            high_24h = float(ticker_data.get("high24h", "0"))
            low_24h = float(ticker_data.get("low24h", "0"))

            # LLM情绪分析
            logger.info("调用DeepSeek进行情绪分析...")
            sentiment_result = await self.llm_client.analyze_market_sentiment(
                symbol=symbol,
                current_price=current_price,
                price_change_24h=price_change_24h,
                news_headlines=news_headlines if news_headlines else None,
            )
            logger.success(
                f"LLM情绪分析完成: {sentiment_result['sentiment']} (置信度: {sentiment_result['confidence']*100:.1f}%)"
            )

            # 5. LLM交易决策分析
            logger.info("调用DeepSeek进行交易决策分析...")
            decision_result = await self.llm_client.analyze_trading_decision(
                symbol=symbol,
                current_price=current_price,
                position_info=None,  # 可以传入当前持仓信息
                market_sentiment=sentiment_result,
            )
            logger.success(
                f"LLM决策分析完成: {decision_result['action']} (置信度: {decision_result['confidence']*100:.1f}%)"
            )

            # 6. 合并LLM结果
            llm_result = {
                "sentiment": sentiment_result,
                "decision": decision_result,
                "news_headlines": news_headlines,
                "timestamp": datetime.now().isoformat(),
            }

            # 缓存LLM结果
            self._cache_llm_result(cache_key, llm_result)

            # 7. 合并规则分析和LLM分析
            final_result = self._merge_analysis(rule_result, llm_result)

            logger.success(
                f"LLM增强分析完成: {final_result['action']} (综合信心度: {final_result['confidence']*100:.1f}%)"
            )
            return final_result

        except Exception as e:
            logger.error(f"LLM分析失败: {e}, 回退到规则分析")
            # LLM失败时回退到规则分析
            return rule_result

    def _merge_analysis(self, rule_result: Dict, llm_result: Dict) -> Dict:
        """
        合并规则分析和LLM分析结果

        策略:
        1. 如果两者建议一致,提高信心度
        2. 如果两者建议冲突,降低信心度,倾向保守(hold)
        3. 综合考虑新闻情绪和技术指标

        Args:
            rule_result: 规则分析结果
            llm_result: LLM分析结果

        Returns:
            合并后的分析结果
        """
        # 提取LLM决策
        llm_decision = llm_result.get("decision", {})
        llm_action = llm_decision.get("action", "hold")
        llm_confidence = llm_decision.get("confidence", 0.5)

        # 提取LLM情绪
        llm_sentiment = llm_result.get("sentiment", {})
        sentiment_type = llm_sentiment.get("sentiment", "neutral")
        sentiment_confidence = llm_sentiment.get("confidence", 0.5)

        # 规则分析结果
        rule_action = rule_result["action"]
        rule_confidence = rule_result["confidence"]

        logger.info(
            f"合并分析 - 规则: {rule_action}({rule_confidence*100:.1f}%), LLM: {llm_action}({llm_confidence*100:.1f}%), 情绪: {sentiment_type}"
        )

        # 决策合并逻辑
        final_action = rule_action
        final_confidence = rule_confidence

        # 1. 两者建议一致 -> 提高信心度
        if rule_action == llm_action:
            # 加权平均,规则占60%,LLM占40%
            final_confidence = rule_confidence * 0.6 + llm_confidence * 0.4
            final_confidence = min(final_confidence * 1.2, 0.95)  # 提升20%,最高95%

            reason = f"规则分析和LLM分析均建议{final_action}, 信心度提升"
            logger.success(
                f"✅ 分析一致: {final_action}, 信心度提升至 {final_confidence*100:.1f}%"
            )

        # 2. 两者建议冲突 -> 降低信心度,倾向保守
        else:
            # 如果信心度差异较大,采用高信心度的建议
            if abs(rule_confidence - llm_confidence) > 0.2:
                if rule_confidence > llm_confidence:
                    final_action = rule_action
                    final_confidence = rule_confidence * 0.8  # 降低20%
                    reason = f"规则分析信心度更高({rule_confidence*100:.1f}% vs {llm_confidence*100:.1f}%), 采用规则建议但降低信心度"
                else:
                    final_action = llm_action
                    final_confidence = llm_confidence * 0.8
                    reason = f"LLM分析信心度更高({llm_confidence*100:.1f}% vs {rule_confidence*100:.1f}%), 采用LLM建议但降低信心度"
            else:
                # 信心度相近,采用保守策略
                final_action = "hold"
                final_confidence = (rule_confidence + llm_confidence) / 2 * 0.7
                reason = f"规则建议{rule_action}, LLM建议{llm_action}, 采用保守策略hold"

            logger.warning(
                f"⚠️ 分析冲突: 规则={rule_action}, LLM={llm_action}, 最终={final_action} ({final_confidence*100:.1f}%)"
            )

        # 3. 结合情绪分析微调
        if sentiment_type == "bullish" and final_action in ["buy", "add"]:
            final_confidence = min(final_confidence * 1.1, 0.95)  # 提升10%
            reason += ", 市场情绪看涨进一步增强信心"
        elif sentiment_type == "bearish" and final_action in ["sell", "reduce"]:
            final_confidence = min(final_confidence * 1.1, 0.95)
            reason += ", 市场情绪看跌进一步增强信心"
        elif sentiment_type == "bullish" and final_action in ["sell", "reduce"]:
            final_confidence *= 0.9  # 降低10%
            reason += ", 但市场情绪看涨,降低卖出信心"
        elif sentiment_type == "bearish" and final_action in ["buy", "add"]:
            final_confidence *= 0.9
            reason += ", 但市场情绪看跌,降低买入信心"

        # 构建最终结果
        merged_result = {
            "action": final_action,
            "confidence": final_confidence,
            "reason": reason,
            "risk_level": self._calculate_risk_level(final_confidence, sentiment_type),
            # 详细分析信息
            "details": {
                "rule_analysis": {
                    "action": rule_action,
                    "confidence": rule_confidence,
                    "reason": rule_result.get("reason", ""),
                },
                "llm_analysis": {
                    "action": llm_action,
                    "confidence": llm_confidence,
                    "reason": llm_decision.get("reason", ""),
                    "key_points": llm_decision.get("key_points", []),
                },
                "sentiment_analysis": {
                    "sentiment": sentiment_type,
                    "confidence": sentiment_confidence,
                    "factors": llm_sentiment.get("factors", []),
                },
                "news_headlines": llm_result.get("news_headlines", []),
            },
            # 仓位建议 (如果有)
            "position_advice": rule_result.get("position_advice", {}),
        }

        return merged_result

    def _calculate_risk_level(self, confidence: float, sentiment: str) -> str:
        """
        计算风险等级

        Args:
            confidence: 信心度
            sentiment: 市场情绪

        Returns:
            风险等级: low, medium, high
        """
        if confidence >= 0.8:
            return "low"
        elif confidence >= 0.6:
            return "medium"
        else:
            return "high"

    def _get_cached_llm_result(self, cache_key: str) -> Optional[Dict]:
        """获取缓存的LLM结果"""
        if cache_key in self.llm_cache:
            cached_data = self.llm_cache[cache_key]
            cached_time = datetime.fromisoformat(cached_data["timestamp"])

            # 检查缓存是否过期
            if datetime.now() - cached_time < self.cache_duration:
                return cached_data
            else:
                # 清除过期缓存
                del self.llm_cache[cache_key]

        return None

    def _cache_llm_result(self, cache_key: str, llm_result: Dict):
        """缓存LLM结果"""
        self.llm_cache[cache_key] = llm_result

        # 限制缓存大小
        if len(self.llm_cache) > 100:
            # 删除最旧的缓存
            oldest_key = min(
                self.llm_cache.keys(), key=lambda k: self.llm_cache[k]["timestamp"]
            )
            del self.llm_cache[oldest_key]

    async def summarize_news(self, symbol: str, limit: int = 10) -> Dict:
        """
        获取并总结新闻

        Args:
            symbol: 交易对符号
            limit: 新闻数量

        Returns:
            新闻总结
        """
        try:
            # 获取新闻
            news_list = await self.news_fetcher.fetch_all_news(
                symbol=symbol, limit=limit, use_mock=False
            )

            if not news_list:
                return {"summary": "暂无相关新闻", "news_count": 0, "news": []}

            # 提取新闻标题
            headlines = [news["title"] for news in news_list]

            # 调用LLM总结新闻
            summary = await self.llm_client.summarize_news(headlines)

            return {"summary": summary, "news_count": len(news_list), "news": news_list}

        except Exception as e:
            logger.error(f"新闻总结失败: {e}")
            return {"summary": f"新闻总结失败: {str(e)}", "news_count": 0, "news": []}


# 全局LLM增强分析器实例
llm_enhanced_analyzer = LLMEnhancedAnalyzer()
