"""
网格策略参数推荐器

根据历史价格波动率智能推荐网格策略参数
"""

from loguru import logger
from typing import Dict, Any, Optional
import math


class GridRecommender:
    """网格策略参数推荐器"""

    def __init__(self, exchange):
        """
        初始化推荐器

        Args:
            exchange: 交易所实例
        """
        self.exchange = exchange

    async def recommend_params(
        self, symbol: str, total_amount: float
    ) -> Dict[str, Any]:
        """
        推荐网格策略参数

        Args:
            symbol: 交易对，如 BTC-USDT
            total_amount: 总投资金额(USDT)

        Returns:
            推荐的网格策略参数
        """
        # 获取当前价格
        ticker = await self.exchange.get_ticker(symbol)
        current_price = float(ticker.get("last", 0))

        if current_price <= 0:
            raise ValueError(f"无法获取 {symbol} 的当前价格")

        # 获取历史K线数据计算波动率
        volatility = await self._calculate_volatility(symbol)

        # 根据波动率确定网格范围
        grid_range = self._calculate_grid_range(current_price, volatility)

        # 根据总投资金额确定网格数量
        grid_count = self._calculate_grid_count(total_amount, current_price)

        # 计算每格投资额
        investment_per_grid = total_amount / grid_count

        return {
            "symbol": symbol,
            "current_price": current_price,
            "volatility": round(volatility * 100, 2),  # 转为百分比
            "price_upper": round(grid_range["upper"], 4),
            "price_lower": round(grid_range["lower"], 4),
            "grid_count": grid_count,
            "investment_per_grid": round(investment_per_grid, 2),
            "total_amount": total_amount,
            "grid_spacing": round(
                (grid_range["upper"] - grid_range["lower"]) / grid_count, 4
            ),
            "recommendation": self._get_recommendation_level(volatility),
        }

    async def _calculate_volatility(self, symbol: str) -> float:
        """
        计算历史波动率

        Args:
            symbol: 交易对

        Returns:
            波动率(小数形式，如 0.15 表示 15%)
        """
        try:
            # 获取最近24小时的数据
            # 这里简化处理，使用24小时高低价计算波动范围
            ticker = await self.exchange.get_ticker(symbol)

            high_24h = float(ticker.get("high24h", 0))
            low_24h = float(ticker.get("low24h", 0))
            last_price = float(ticker.get("last", 0))

            if high_24h > 0 and low_24h > 0 and last_price > 0:
                # 使用24小时高低价范围作为波动率估计
                volatility = (high_24h - low_24h) / last_price
                return volatility

            # 默认波动率 5%
            return 0.05

        except Exception as e:
            logger.warning(f"计算波动率失败，使用默认值: {e}")
            return 0.05

    def _calculate_grid_range(
        self, current_price: float, volatility: float
    ) -> Dict[str, float]:
        """
        计算网格价格范围

        Args:
            current_price: 当前价格
            volatility: 波动率

        Returns:
            包含 upper 和 lower 的字典
        """
        # 网格范围设为波动率的 1.5 倍，确保覆盖大部分价格波动
        range_multiplier = 1.5
        price_range = current_price * volatility * range_multiplier

        upper = current_price + price_range / 2
        lower = current_price - price_range / 2

        # 确保下限为正数
        lower = max(lower, current_price * 0.1)

        return {"upper": upper, "lower": lower}

    def _calculate_grid_count(self, total_amount: float, current_price: float) -> int:
        """
        计算推荐的网格数量

        Args:
            total_amount: 总投资金额
            current_price: 当前价格

        Returns:
            网格数量
        """
        # 根据总投资金额确定网格数量
        # 每格最小投资约 10 USDT
        min_investment_per_grid = 10

        # 最大网格数 100，最小 5
        max_grids = 100
        min_grids = 5

        # 计算理论网格数
        theoretical_grids = int(total_amount / min_investment_per_grid)

        # 限制在合理范围内
        grid_count = max(min_grids, min(max_grids, theoretical_grids))

        return grid_count

    def _get_recommendation_level(self, volatility: float) -> str:
        """
        根据波动率给出推荐等级

        Args:
            volatility: 波动率

        Returns:
            推荐等级描述
        """
        if volatility < 0.03:
            return "低波动 - 适合网格策略"
        elif volatility < 0.08:
            return "中等波动 - 较适合网格策略"
        elif volatility < 0.15:
            return "较高波动 - 请注意风险"
        else:
            return "高波动 - 建议谨慎操作"
