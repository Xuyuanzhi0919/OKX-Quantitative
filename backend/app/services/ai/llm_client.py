"""
DeepSeek LLM客户端
用于新闻分析、市场情绪分析等
"""

import os
import json
from typing import Dict, List, Optional
from loguru import logger
import aiohttp
from decimal import Decimal


class DeepSeekLLM:
    """DeepSeek LLM客户端"""

    def __init__(
        self, api_key: Optional[str] = None, base_url: str = "https://api.deepseek.com"
    ):
        """
        初始化DeepSeek客户端

        Args:
            api_key: DeepSeek API密钥，默认从环境变量DEEPSEEK_API_KEY或settings读取
            base_url: API基础URL
        """
        # 优先使用传入的api_key，其次环境变量，最后从settings读取
        if api_key:
            self.api_key = api_key
        else:
            self.api_key = os.getenv("DEEPSEEK_API_KEY")
            if not self.api_key:
                try:
                    from app.core.config import settings

                    self.api_key = settings.DEEPSEEK_API_KEY
                except:
                    pass

        if not self.api_key:
            logger.warning("DeepSeek API Key未设置，LLM功能将无法使用")

        self.base_url = base_url
        self.model = "deepseek-chat"  # 使用DeepSeek Chat模型
        self.timeout = aiohttp.ClientTimeout(total=30)

        logger.info(f"DeepSeek LLM客户端初始化完成 - 模型: {self.model}")

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        """
        调用DeepSeek Chat API

        Args:
            messages: 对话消息列表，格式: [{"role": "user", "content": "..."}]
            temperature: 温度参数，控制随机性 (0-2)
            max_tokens: 最大生成token数

        Returns:
            LLM生成的回复文本
        """
        if not self.api_key:
            raise ValueError("DeepSeek API Key未设置")

        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(
                            f"DeepSeek API错误 ({response.status}): {error_text}"
                        )

                    result = await response.json()
                    content = result["choices"][0]["message"]["content"]

                    logger.debug(f"DeepSeek响应: {content[:100]}...")
                    return content

        except aiohttp.ClientError as e:
            logger.error(f"DeepSeek API请求失败: {e}")
            raise
        except Exception as e:
            logger.error(f"DeepSeek调用异常: {e}")
            raise

    async def analyze_market_sentiment(
        self,
        symbol: str,
        current_price: Decimal,
        price_change_24h: float,
        news_headlines: Optional[List[str]] = None,
    ) -> Dict:
        """
        使用LLM分析市场情绪

        Args:
            symbol: 交易对
            current_price: 当前价格
            price_change_24h: 24h价格变化百分比
            news_headlines: 相关新闻标题列表

        Returns:
            {
                "sentiment": "bullish|bearish|neutral",
                "confidence": 0.8,
                "reasoning": "分析原因",
                "key_factors": ["因素1", "因素2"]
            }
        """
        # 构建提示词
        news_context = ""
        if news_headlines:
            news_context = "\n\n最近相关新闻:\n" + "\n".join(
                [f"- {h}" for h in news_headlines[:5]]
            )

        prompt = f"""你是一位专业的加密货币市场分析师。请分析以下市场数据并给出情绪判断。

交易对: {symbol}
当前价格: ${current_price}
24小时涨跌: {price_change_24h:+.2f}%{news_context}

请以JSON格式回复，包含以下字段:
{{
    "sentiment": "bullish/bearish/neutral",
    "confidence": 0.0-1.0之间的数值,
    "reasoning": "简短的分析原因(1-2句话)",
    "key_factors": ["关键因素1", "关键因素2", "关键因素3"]
}}

只返回JSON，不要其他文字。"""

        messages = [
            {
                "role": "system",
                "content": "你是一位专业的加密货币市场分析师，擅长技术分析和情绪分析。",
            },
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self.chat_completion(
                messages, temperature=0.3, max_tokens=500
            )

            # 解析JSON响应
            # 清理可能的markdown代码块标记
            response_clean = response.strip()
            if response_clean.startswith("```json"):
                response_clean = response_clean[7:]
            if response_clean.startswith("```"):
                response_clean = response_clean[3:]
            if response_clean.endswith("```"):
                response_clean = response_clean[:-3]

            result = json.loads(response_clean.strip())

            logger.success(
                f"LLM市场情绪分析完成: {result['sentiment']} (信心度: {result['confidence']})"
            )
            return result

        except json.JSONDecodeError as e:
            logger.error(f"LLM响应JSON解析失败: {e}, 原始响应: {response}")
            # 返回默认中性结果
            return {
                "sentiment": "neutral",
                "confidence": 0.5,
                "reasoning": "LLM响应解析失败，使用默认中性判断",
                "key_factors": ["数据不足"],
            }
        except Exception as e:
            logger.error(f"LLM市场情绪分析失败: {e}")
            return {
                "sentiment": "neutral",
                "confidence": 0.5,
                "reasoning": f"分析失败: {str(e)}",
                "key_factors": ["分析错误"],
            }

    async def analyze_trading_decision(
        self,
        symbol: str,
        current_price: Decimal,
        position_info: Optional[Dict] = None,
        market_sentiment: Optional[Dict] = None,
        technical_indicators: Optional[Dict] = None,
    ) -> Dict:
        """
        使用LLM分析交易决策

        Args:
            symbol: 交易对
            current_price: 当前价格
            position_info: 持仓信息 {"amount": 100, "entry_price": 90000, "pnl_pct": 5.5}
            market_sentiment: 市场情绪分析结果
            technical_indicators: 技术指标 {"rsi": 65, "macd": "bullish", ...}

        Returns:
            {
                "action": "buy|sell|hold|add|reduce",
                "confidence": 0.85,
                "reasoning": "决策原因",
                "risk_assessment": "low|medium|high",
                "suggested_ratio": 0.3  # 加仓/减仓比例
            }
        """
        # 构建上下文信息
        context_parts = [f"交易对: {symbol}", f"当前价格: ${current_price}"]

        if position_info:
            context_parts.append(
                f"持仓信息: 数量={position_info.get('amount', 0)}, "
                f"成本=${position_info.get('entry_price', 0)}, "
                f"盈亏={position_info.get('pnl_pct', 0):+.2f}%"
            )

        if market_sentiment:
            context_parts.append(
                f"市场情绪: {market_sentiment.get('sentiment', 'unknown')} "
                f"(信心度: {market_sentiment.get('confidence', 0):.0%})"
            )

        if technical_indicators:
            indicators_str = ", ".join(
                [f"{k}={v}" for k, v in technical_indicators.items()]
            )
            context_parts.append(f"技术指标: {indicators_str}")

        context = "\n".join(context_parts)

        prompt = f"""你是一位专业的量化交易分析师。请基于以下信息给出交易建议。

{context}

请以JSON格式回复，包含以下字段:
{{
    "action": "buy|sell|hold|add|reduce",
    "confidence": 0.0-1.0之间的数值,
    "reasoning": "决策原因(1-2句话)",
    "risk_assessment": "low|medium|high",
    "suggested_ratio": 0.0-1.0之间的数值 (仅当action为add/reduce时)
}}

注意:
- buy: 开仓买入 (无持仓时)
- sell: 全部平仓 (有持仓时)
- hold: 继续持有
- add: 加仓 (有盈利持仓时)
- reduce: 减仓止盈 (有盈利持仓时)

只返回JSON，不要其他文字。"""

        messages = [
            {
                "role": "system",
                "content": "你是一位专业的量化交易分析师，擅长风险控制和决策分析。你的建议应该保守、理性。",
            },
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self.chat_completion(
                messages, temperature=0.2, max_tokens=500
            )

            # 解析JSON响应
            response_clean = response.strip()
            if response_clean.startswith("```json"):
                response_clean = response_clean[7:]
            if response_clean.startswith("```"):
                response_clean = response_clean[3:]
            if response_clean.endswith("```"):
                response_clean = response_clean[:-3]

            result = json.loads(response_clean.strip())

            logger.success(
                f"LLM交易决策分析完成: {result['action']} "
                f"(信心度: {result['confidence']}, 风险: {result['risk_assessment']})"
            )
            return result

        except json.JSONDecodeError as e:
            logger.error(f"LLM响应JSON解析失败: {e}, 原始响应: {response}")
            return {
                "action": "hold",
                "confidence": 0.5,
                "reasoning": "LLM响应解析失败，建议观望",
                "risk_assessment": "medium",
                "suggested_ratio": 0.0,
            }
        except Exception as e:
            logger.error(f"LLM交易决策分析失败: {e}")
            return {
                "action": "hold",
                "confidence": 0.5,
                "reasoning": f"分析失败: {str(e)}",
                "risk_assessment": "high",
                "suggested_ratio": 0.0,
            }

    async def summarize_news(self, news_articles: List[Dict]) -> str:
        """
        总结多条新闻

        Args:
            news_articles: 新闻列表 [{"title": "...", "summary": "...", "published_at": "..."}]

        Returns:
            新闻摘要文本
        """
        if not news_articles:
            return "暂无相关新闻"

        # 构建新闻列表
        news_list = []
        for i, article in enumerate(news_articles[:10], 1):
            title = article.get("title", "")
            summary = article.get("summary", "")
            news_list.append(f"{i}. {title}\n   {summary}")

        news_text = "\n\n".join(news_list)

        prompt = f"""请总结以下加密货币相关新闻，提取关键信息和整体趋势。

{news_text}

请用3-5句话总结，重点关注:
1. 主要事件和趋势
2. 对市场可能的影响
3. 整体情绪倾向

用中文回复，简洁明了。"""

        messages = [
            {"role": "system", "content": "你是一位专业的加密货币新闻分析师。"},
            {"role": "user", "content": prompt},
        ]

        try:
            summary = await self.chat_completion(
                messages, temperature=0.5, max_tokens=300
            )
            logger.success(f"新闻摘要生成完成: {len(summary)}字")
            return summary
        except Exception as e:
            logger.error(f"新闻摘要生成失败: {e}")
            return "新闻摘要生成失败"


# 全局LLM客户端实例
deepseek_llm = DeepSeekLLM()
