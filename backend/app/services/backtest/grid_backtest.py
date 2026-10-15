"""
网格策略回测实现
"""

from typing import Dict, List
from loguru import logger
from .backtest_engine import BacktestEngine


class GridBacktestEngine(BacktestEngine):
    """网格策略回测引擎"""

    def __init__(
        self,
        symbol: str,
        initial_capital: float,
        grid_lower: float,  # 网格下限
        grid_upper: float,  # 网格上限
        grid_num: int,  # 网格数量
        amount_per_grid: float,  # 每格交易数量
        fee_rate: float = 0.001,
    ):
        """
        初始化网格策略回测引擎

        Args:
            symbol: 交易对
            initial_capital: 初始资金
            grid_lower: 网格下限价格
            grid_upper: 网格上限价格
            grid_num: 网格数量
            amount_per_grid: 每格交易数量
            fee_rate: 手续费率
        """
        super().__init__(symbol, initial_capital, fee_rate)

        self.grid_lower = grid_lower
        self.grid_upper = grid_upper
        self.grid_num = grid_num
        self.amount_per_grid = amount_per_grid

        # 计算网格价格
        self.grid_prices = self._calculate_grid_prices()

        # 网格状态（记录每个网格是否已买入）
        self.grid_states = [False] * grid_num

        logger.info(
            f"网格策略初始化: 价格区间 [{grid_lower}, {grid_upper}], "
            f"网格数: {grid_num}, 每格数量: {amount_per_grid}"
        )
        logger.info(f"网格价格: {[f'{p:.2f}' for p in self.grid_prices]}")

    def _calculate_grid_prices(self) -> List[float]:
        """
        计算网格价格

        Returns:
            网格价格列表（从低到高）
        """
        if self.grid_num <= 1:
            return [self.grid_lower]

        # 等差网格
        step = (self.grid_upper - self.grid_lower) / (self.grid_num - 1)
        prices = [self.grid_lower + i * step for i in range(self.grid_num)]

        return prices

    def reset(self):
        """重置回测状态"""
        super().reset()
        self.grid_states = [False] * self.grid_num

    def on_kline(self, kline: Dict):
        """
        处理K线数据，执行网格策略

        网格策略逻辑 (改进版 - 使用穿越触发):
        - 价格从上方跌破网格线时买入(低买)
        - 价格从下方突破网格线时卖出(高卖)
        - 使用K线的open/high/low/close判断穿越

        这种方式避免了在价格已经在网格下方时立即买入的问题

        Args:
            kline: K线数据
        """
        timestamp = int(kline["timestamp"])
        open_price = float(kline["open"])
        high_price = float(kline["high"])
        low_price = float(kline["low"])
        close_price = float(kline["close"])

        # 遍历网格价格，检查是否触发交易
        for i, grid_price in enumerate(self.grid_prices):
            # 网格买入逻辑：价格从上方穿越网格线向下
            # 条件: 1) 开盘价高于网格价格(之前在上方)  2) 最低价低于网格价格(穿越发生)  3) 该网格未持仓
            if (
                open_price > grid_price
                and low_price <= grid_price
                and not self.grid_states[i]
            ):
                # 以网格价格买入
                trade = self.buy(grid_price, self.amount_per_grid, timestamp)
                if trade:
                    self.grid_states[i] = True
                    logger.debug(
                        f"网格{i}买入: 价格穿越 {grid_price:.2f} 向下 (K线: {open_price:.2f} -> {low_price:.2f}-{high_price:.2f} -> {close_price:.2f})"
                    )

            # 网格卖出逻辑：价格从下方穿越网格线向上
            # 条件: 1) 开盘价低于网格价格(之前在下方)  2) 最高价高于网格价格(穿越发生)  3) 该网格有持仓
            elif (
                open_price < grid_price
                and high_price >= grid_price
                and self.grid_states[i]
            ):
                # 以网格价格卖出
                trade = self.sell(grid_price, self.amount_per_grid, timestamp)
                if trade:
                    self.grid_states[i] = False
                    logger.debug(
                        f"网格{i}卖出: 价格穿越 {grid_price:.2f} 向上, 盈亏: {trade.pnl:.2f}"
                    )


class GridMarketMakingBacktest(BacktestEngine):
    """
    网格做市策略回测
    在当前价格上下挂买卖单，不断做市
    """

    def __init__(
        self,
        symbol: str,
        initial_capital: float,
        grid_spread: float,  # 网格间距（百分比，如0.01表示1%）
        grid_levels: int,  # 每侧网格层数
        amount_per_grid: float,  # 每格交易数量
        fee_rate: float = 0.001,
    ):
        """
        初始化网格做市策略

        Args:
            symbol: 交易对
            initial_capital: 初始资金
            grid_spread: 网格间距（百分比）
            grid_levels: 每侧网格层数
            amount_per_grid: 每格交易数量
            fee_rate: 手续费率
        """
        super().__init__(symbol, initial_capital, fee_rate)

        self.grid_spread = grid_spread
        self.grid_levels = grid_levels
        self.amount_per_grid = amount_per_grid

        # 买卖挂单
        self.buy_orders: List[Dict] = []  # [{price, amount, grid_index}]
        self.sell_orders: List[Dict] = []

        logger.info(
            f"网格做市策略初始化: 间距 {grid_spread*100:.2f}%, "
            f"层数: {grid_levels}, 每格数量: {amount_per_grid}"
        )

    def reset(self):
        """重置回测状态"""
        super().reset()
        self.buy_orders = []
        self.sell_orders = []

    def _initialize_grids(self, current_price: float):
        """
        初始化网格挂单

        Args:
            current_price: 当前价格
        """
        self.buy_orders = []
        self.sell_orders = []

        # 生成买单（低于当前价）
        for i in range(1, self.grid_levels + 1):
            buy_price = current_price * (1 - self.grid_spread * i)
            self.buy_orders.append(
                {"price": buy_price, "amount": self.amount_per_grid, "grid_index": i}
            )

        # 生成卖单（高于当前价）
        for i in range(1, self.grid_levels + 1):
            sell_price = current_price * (1 + self.grid_spread * i)
            self.sell_orders.append(
                {"price": sell_price, "amount": self.amount_per_grid, "grid_index": i}
            )

        logger.debug(f"初始化网格: 当前价 {current_price:.2f}")
        buy_prices = [f"{o['price']:.2f}" for o in self.buy_orders]
        sell_prices = [f"{o['price']:.2f}" for o in self.sell_orders]
        logger.debug(f"买单: {buy_prices}")
        logger.debug(f"卖单: {sell_prices}")

    def on_kline(self, kline: Dict):
        """
        处理K线数据，执行网格做市

        Args:
            kline: K线数据
        """
        timestamp = int(kline["timestamp"])
        low_price = float(kline["low"])
        high_price = float(kline["high"])
        close_price = float(kline["close"])

        # 首次运行时初始化网格
        if not self.buy_orders and not self.sell_orders:
            self._initialize_grids(close_price)
            return

        # 检查买单成交
        executed_buys = []
        for order in self.buy_orders:
            if low_price <= order["price"]:
                # 买单成交
                trade = self.buy(order["price"], order["amount"], timestamp)
                if trade:
                    executed_buys.append(order)
                    logger.debug(f"做市买入: {order['price']:.2f}")

        # 移除已成交的买单
        for order in executed_buys:
            self.buy_orders.remove(order)
            # 在上方添加新的卖单
            new_sell_price = order["price"] * (1 + self.grid_spread)
            self.sell_orders.append(
                {
                    "price": new_sell_price,
                    "amount": order["amount"],
                    "grid_index": order["grid_index"],
                }
            )

        # 检查卖单成交
        executed_sells = []
        for order in self.sell_orders:
            if high_price >= order["price"]:
                # 卖单成交
                trade = self.sell(order["price"], order["amount"], timestamp)
                if trade:
                    executed_sells.append(order)
                    logger.debug(
                        f"做市卖出: {order['price']:.2f}, 盈亏: {trade.pnl:.2f}"
                    )

        # 移除已成交的卖单
        for order in executed_sells:
            self.sell_orders.remove(order)
            # 在下方添加新的买单
            new_buy_price = order["price"] * (1 - self.grid_spread)
            self.buy_orders.append(
                {
                    "price": new_buy_price,
                    "amount": order["amount"],
                    "grid_index": order["grid_index"],
                }
            )
