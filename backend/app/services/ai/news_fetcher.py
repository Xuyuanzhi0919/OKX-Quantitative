"""
加密货币新闻获取模块
支持多个新闻源
"""

import aiohttp
from typing import List, Dict, Optional
from loguru import logger
from datetime import datetime, timedelta
import asyncio


class NewsFetcher:
    """加密货币新闻获取器"""

    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(total=10)
        logger.info("新闻获取器初始化完成")

    async def fetch_coingecko_news(
        self, symbol: Optional[str] = None, limit: int = 10
    ) -> List[Dict]:
        """
        从CoinGecko获取新闻 (免费API)

        Args:
            symbol: 交易对符号，如"BTC"
            limit: 返回新闻数量

        Returns:
            新闻列表
        """
        # CoinGecko的状态更新API (免费)
        url = "https://api.coingecko.com/api/v3/status_updates"

        params = {"per_page": limit}

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        logger.warning(f"CoinGecko新闻获取失败: HTTP {response.status}")
                        return []

                    data = await response.json()

                    # 解析新闻
                    news_list = []
                    for item in data.get("status_updates", [])[:limit]:
                        news_list.append(
                            {
                                "source": "CoinGecko",
                                "title": item.get("description", "")[
                                    :200
                                ],  # 取前200字符作为标题
                                "summary": item.get("description", ""),
                                "url": item.get("project", {})
                                .get("image", {})
                                .get("large", ""),
                                "published_at": item.get("created_at", ""),
                                "category": item.get("category", "general"),
                            }
                        )

                    logger.success(f"从CoinGecko获取到 {len(news_list)} 条新闻")
                    return news_list

        except aiohttp.ClientError as e:
            logger.error(f"CoinGecko新闻请求失败: {e}")
            return []
        except Exception as e:
            logger.error(f"CoinGecko新闻解析失败: {e}")
            return []

    async def fetch_cryptopanic_news(
        self, symbol: Optional[str] = None, limit: int = 10
    ) -> List[Dict]:
        """
        从CryptoPanic获取新闻 (免费API，需要注册获取token)

        Args:
            symbol: 币种符号，如"BTC"
            limit: 返回新闻数量

        Returns:
            新闻列表
        """
        # CryptoPanic免费API
        # 需要在 https://cryptopanic.com/developers/api/ 注册获取免费token
        # 这里使用公共API端点 (功能有限)

        base_url = "https://cryptopanic.com/api/v1/posts/"

        params = {
            "auth_token": "free",  # 免费公共访问
            "public": "true",
            "kind": "news",  # 只要新闻，不要社交媒体
            "filter": "hot",  # 热门新闻
        }

        if symbol:
            # 转换为CryptoPanic的币种代码
            currency_map = {
                "BTC": "BTC",
                "ETH": "ETH",
                "USDT": "USDT",
                "BNB": "BNB",
                "SOL": "SOL",
                "XRP": "XRP",
                "ADA": "ADA",
                "DOGE": "DOGE",
            }
            coin_code = symbol.replace("-USDT-SWAP", "").replace("-USDT", "")
            if coin_code in currency_map:
                params["currencies"] = currency_map[coin_code]

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(base_url, params=params) as response:
                    if response.status != 200:
                        logger.warning(
                            f"CryptoPanic新闻获取失败: HTTP {response.status}"
                        )
                        return []

                    data = await response.json()

                    # 解析新闻
                    news_list = []
                    for item in data.get("results", [])[:limit]:
                        news_list.append(
                            {
                                "source": "CryptoPanic",
                                "title": item.get("title", ""),
                                "summary": item.get(
                                    "title", ""
                                ),  # CryptoPanic没有摘要，用标题代替
                                "url": item.get("url", ""),
                                "published_at": item.get("published_at", ""),
                                "category": "news",
                                "votes": item.get("votes", {}),
                            }
                        )

                    logger.success(f"从CryptoPanic获取到 {len(news_list)} 条新闻")
                    return news_list

        except aiohttp.ClientError as e:
            logger.error(f"CryptoPanic新闻请求失败: {e}")
            return []
        except Exception as e:
            logger.error(f"CryptoPanic新闻解析失败: {e}")
            return []

    async def fetch_mock_news(self, symbol: str) -> List[Dict]:
        """
        生成模拟新闻 (用于测试和演示)

        Args:
            symbol: 交易对符号

        Returns:
            模拟新闻列表
        """
        coin = symbol.split("-")[0]

        mock_news = [
            {
                "source": "Mock",
                "title": f"{coin}价格突破关键阻力位，市场情绪转暖",
                "summary": f"{coin}在过去24小时内成功突破关键技术阻力位，交易量显著增加，市场分析师普遍看好后市。",
                "url": "https://example.com/news/1",
                "published_at": datetime.now().isoformat(),
                "category": "market",
            },
            {
                "source": "Mock",
                "title": f"机构投资者加仓{coin}，链上数据显示大额转入交易所",
                "summary": f"据链上数据监测，多个巨鲸地址在过去一周内向交易所转入大量{coin}，市场猜测机构正在建仓。",
                "url": "https://example.com/news/2",
                "published_at": (datetime.now() - timedelta(hours=2)).isoformat(),
                "category": "onchain",
            },
            {
                "source": "Mock",
                "title": f"{coin}技术升级即将上线，社区反响积极",
                "summary": f"{coin}开发团队宣布将在下月推出重要技术升级，预计将提升网络性能和用户体验，社区反响热烈。",
                "url": "https://example.com/news/3",
                "published_at": (datetime.now() - timedelta(hours=5)).isoformat(),
                "category": "development",
            },
            {
                "source": "Mock",
                "title": f"分析师: {coin}短期可能面临回调压力",
                "summary": f"多位技术分析师指出，{coin}在快速上涨后可能面临短期回调压力，建议投资者注意风险管理。",
                "url": "https://example.com/news/4",
                "published_at": (datetime.now() - timedelta(hours=8)).isoformat(),
                "category": "analysis",
            },
            {
                "source": "Mock",
                "title": f"全球监管趋严，{coin}及其他加密货币受到关注",
                "summary": f"多国监管机构表示将加强对加密货币市场的监管，{coin}等主流币种可能受到影响。",
                "url": "https://example.com/news/5",
                "published_at": (datetime.now() - timedelta(hours=12)).isoformat(),
                "category": "regulation",
            },
        ]

        logger.info(f"生成 {len(mock_news)} 条{coin}模拟新闻")
        return mock_news

    async def fetch_all_news(
        self, symbol: str, limit: int = 10, use_mock: bool = False
    ) -> List[Dict]:
        """
        从所有可用源获取新闻

        Args:
            symbol: 交易对符号
            limit: 每个源的新闻数量
            use_mock: 是否使用模拟新闻 (测试模式)

        Returns:
            合并后的新闻列表
        """
        if use_mock:
            return await self.fetch_mock_news(symbol)

        # 并发获取多个新闻源
        tasks = [
            self.fetch_coingecko_news(symbol, limit),
            self.fetch_cryptopanic_news(symbol, limit),
        ]

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            all_news = []
            for result in results:
                if isinstance(result, list):
                    all_news.extend(result)
                elif isinstance(result, Exception):
                    logger.warning(f"新闻获取出错: {result}")

            # 按发布时间排序 (最新的在前)
            all_news.sort(key=lambda x: x.get("published_at", ""), reverse=True)

            # 去重 (基于标题)
            seen_titles = set()
            unique_news = []
            for news in all_news:
                title = news.get("title", "")
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    unique_news.append(news)

            logger.success(f"共获取 {len(unique_news)} 条去重后的新闻")
            return unique_news[: limit * 2]  # 返回最多limit*2条

        except Exception as e:
            logger.error(f"新闻获取失败: {e}")
            # 失败时返回模拟新闻
            return await self.fetch_mock_news(symbol)


# 全局新闻获取器实例
news_fetcher = NewsFetcher()
