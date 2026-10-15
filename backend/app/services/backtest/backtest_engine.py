"""
回测引擎基类
提供回测执行的核心功能：订单撮合、资金管理、持仓管理等
"""

from typing import Dict, List, Optional, Callable
from decimal import Decimal
from dataclasses import dataclass
from datetime import datetime
from loguru import logger


@dataclass
class Trade:
    """交易记录"""

    timestamp: int  # 交易时间戳(毫秒)
    side: str  # 方向：buy/sell
    price: float  # 成交价格
    amount: float  # 成交数量
    fee: float  # 手续费
    position_before: float  # 交易前持仓
    position_after: float  # 交易后持仓
    capital_before: float  # 交易前资金
    capital_after: float  # 交易后资金
    pnl: float = 0.0  # 本次交易盈亏
    pnl_percent: float = 0.0  # 本次交易盈亏百分比
    direction: str = "long"  # 交易方向：long/short
    leverage: int = 1  # 杠杆倍数
    margin_used: float = 0.0  # 占用保证金


@dataclass
class Position:
    """持仓信息"""

    amount: float = 0.0  # 持仓数量（正数做多，负数做空）
    avg_price: float = 0.0  # 平均成本价
    unrealized_pnl: float = 0.0  # 未实现盈亏
    direction: str = "flat"  # 持仓方向：long/short/flat
    margin_used: float = 0.0  # 占用保证金


@dataclass
class MarginAccount:
    """保证金账户"""

    balance: float  # 保证金余额
    leverage: int = 1  # 杠杆倍数
    margin_used: float = 0.0  # 已用保证金
    liquidation_price: float = 0.0  # 强平价格
    margin_call_ratio: float = 0.8  # 追保比例阈值


class BacktestEngine:
    """回测引擎基类"""

    def __init__(
        self,
        symbol: str,
        initial_capital: float = 10000.0,
        fee_rate: float = 0.001,  # 默认手续费率 0.1%
        leverage: int = 1,  # 杠杆倍数
        enable_short: bool = False,  # 是否启用做空
        margin_call_ratio: float = 0.8,  # 追保比例阈值
    ):
        """
        初始化回测引擎

        Args:
            symbol: 交易对
            initial_capital: 初始资金(USDT)
            fee_rate: 手续费率
            leverage: 杠杆倍数 (1-125)
            enable_short: 是否启用做空
            margin_call_ratio: 追保比例阈值
        """
        self.symbol = symbol
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.leverage = min(max(1, leverage), 125)  # 限制杠杆范围1-125
        self.enable_short = enable_short
        self.margin_call_ratio = margin_call_ratio

        # 账户状态
        self.capital = initial_capital  # 当前可用资金
        self.position = Position()  # 当前持仓
        self.margin_account = MarginAccount(
            balance=initial_capital,
            leverage=self.leverage,
            margin_call_ratio=margin_call_ratio,
        )

        # 交易记录
        self.trades: List[Trade] = []

        # 资金曲线
        self.equity_curve: List[Dict] = []

        # 当前K线索引
        self.current_index = 0
        self.current_kline: Optional[Dict] = None

        # 强平统计
        self.liquidation_count = 0
        self.liquidated = False

    def reset(self):
        """重置回测状态"""
        self.capital = self.initial_capital
        self.position = Position()
        self.margin_account = MarginAccount(
            balance=self.initial_capital,
            leverage=self.leverage,
            margin_call_ratio=self.margin_call_ratio,
        )
        self.trades = []
        self.equity_curve = []
        self.current_index = 0
        self.current_kline = None
        self.liquidation_count = 0
        self.liquidated = False

    def buy(self, price: float, amount: float, timestamp: int) -> Optional[Trade]:
        """
        买入（合约模式下使用保证金）

        Args:
            price: 买入价格
            amount: 买入数量
            timestamp: 时间戳

        Returns:
            交易记录，如果资金不足返回None
        """
        # 计算所需保证金（杠杆模式下）
        position_value = price * amount
        margin_required = position_value / self.leverage
        fee = position_value * self.fee_rate
        total_cost = margin_required + fee

        # 检查资金是否足够
        if total_cost > self.capital:
            logger.warning(f"资金不足: 需要 {total_cost:.2f}, 可用 {self.capital:.2f}")
            return None

        # 记录交易前状态
        position_before = self.position.amount
        capital_before = self.capital

        # 更新持仓（加权平均成本）
        if self.position.amount > 0:
            total_amount = self.position.amount + amount
            total_cost_basis = (
                self.position.avg_price * self.position.amount
            ) + position_value
            self.position.avg_price = total_cost_basis / total_amount
        else:
            self.position.avg_price = price

        self.position.amount += amount
        self.position.direction = "long"
        self.position.margin_used = self.position.amount * price / self.leverage

        # 更新资金
        self.capital -= total_cost
        self.margin_account.margin_used = self.position.margin_used

        # 记录交易后状态
        position_after = self.position.amount
        capital_after = self.capital

        # 创建交易记录
        trade = Trade(
            timestamp=timestamp,
            side="buy",
            price=price,
            amount=amount,
            fee=fee,
            position_before=position_before,
            position_after=position_after,
            capital_before=capital_before,
            capital_after=capital_after,
            pnl=0.0,  # 买入时pnl为0
            pnl_percent=0.0,
            direction="long",
            leverage=self.leverage,
            margin_used=margin_required,
        )

        self.trades.append(trade)
        logger.debug(
            f"买入: {amount:.8f} @ {price:.2f}, 保证金: {margin_required:.2f}, 杠杆: {self.leverage}x, 剩余资金: {self.capital:.2f}"
        )

        return trade

    def sell(self, price: float, amount: float, timestamp: int) -> Optional[Trade]:
        """
        卖出平多（合约模式下）

        Args:
            price: 卖出价格
            amount: 卖出数量
            timestamp: 时间戳

        Returns:
            交易记录，如果持仓不足返回None
        """
        # 检查持仓是否足够
        if amount > self.position.amount:
            logger.warning(
                f"持仓不足: 需要 {amount:.8f}, 可用 {self.position.amount:.8f}"
            )
            return None

        # 计算收益（杠杆模式下）
        position_value = price * amount
        fee = position_value * self.fee_rate

        # 计算盈亏（基于价格变化，杠杆效应已体现在价格变化上）
        price_pnl = price - self.position.avg_price
        gross_pnl = price_pnl * amount
        net_pnl = gross_pnl - fee

        # 计算收益率（相对于保证金）
        margin_used = position_value / self.leverage
        pnl_percent = (net_pnl / margin_used) * 100 if margin_used > 0 else 0.0

        # 记录交易前状态
        position_before = self.position.amount
        capital_before = self.capital

        # 返还保证金 + 盈亏
        self.capital += margin_used + net_pnl

        # 更新持仓
        self.position.amount -= amount
        if self.position.amount <= 0:
            self.position.amount = 0
            self.position.avg_price = 0
            self.position.direction = "flat"
            self.position.margin_used = 0

        self.margin_account.margin_used = self.position.margin_used

        # 记录交易后状态
        position_after = self.position.amount
        capital_after = self.capital

        # 创建交易记录
        trade = Trade(
            timestamp=timestamp,
            side="sell",
            price=price,
            amount=amount,
            fee=fee,
            position_before=position_before,
            position_after=position_after,
            capital_before=capital_before,
            capital_after=capital_after,
            pnl=net_pnl,
            pnl_percent=pnl_percent,
            direction="long",
            leverage=self.leverage,
        )

        self.trades.append(trade)
        logger.debug(
            f"卖出: {amount:.8f} @ {price:.2f}, 盈亏: {net_pnl:.2f} ({pnl_percent:.2f}%), 剩余资金: {self.capital:.2f}"
        )

        return trade

    def short(self, price: float, amount: float, timestamp: int) -> Optional[Trade]:
        """
        做空开仓

        Args:
            price: 卖出价格
            amount: 卖出数量
            timestamp: 时间戳

        Returns:
            交易记录，如果不支持做空或资金不足返回None
        """
        if not self.enable_short:
            logger.warning("做空功能未启用")
            return None

        # 计算所需保证金（杠杆模式下）
        position_value = price * amount
        margin_required = position_value / self.leverage
        fee = position_value * self.fee_rate
        total_required = margin_required + fee

        # 检查资金是否足够
        if total_required > self.capital:
            logger.warning(
                f"保证金不足: 需要 {total_required:.2f}, 可用 {self.capital:.2f}"
            )
            return None

        # 记录交易前状态
        position_before = self.position.amount
        capital_before = self.capital

        # 更新持仓（负数表示做空）
        if self.position.amount < 0:
            # 加仓做空
            total_amount = abs(self.position.amount) + amount
            total_cost_basis = (
                abs(self.position.amount) * self.position.avg_price
            ) + position_value
            self.position.avg_price = total_cost_basis / total_amount
            self.position.amount = -total_amount
        else:
            # 新开空仓
            self.position.avg_price = price
            self.position.amount = -amount

        self.position.direction = "short"
        self.position.margin_used = abs(self.position.amount) * price / self.leverage

        # 更新资金
        self.capital -= total_required
        self.margin_account.margin_used = self.position.margin_used

        # 记录交易后状态
        position_after = self.position.amount
        capital_after = self.capital

        # 创建交易记录
        trade = Trade(
            timestamp=timestamp,
            side="sell",  # 做空是卖出
            price=price,
            amount=amount,
            fee=fee,
            position_before=position_before,
            position_after=position_after,
            capital_before=capital_before,
            capital_after=capital_after,
            pnl=0.0,
            pnl_percent=0.0,
            direction="short",
            leverage=self.leverage,
            margin_used=margin_required,
        )

        self.trades.append(trade)
        logger.debug(
            f"做空开仓: {amount:.8f} @ {price:.2f}, 保证金: {margin_required:.2f}, 杠杆: {self.leverage}x"
        )

        return trade

    def cover(self, price: float, amount: float, timestamp: int) -> Optional[Trade]:
        """
        平空仓

        Args:
            price: 买入价格
            amount: 买入数量
            timestamp: 时间戳

        Returns:
            交易记录，如果空仓不足返回None
        """
        # 检查空仓是否足够
        if self.position.amount >= 0:
            logger.warning("没有空仓可平")
            return None

        if amount > abs(self.position.amount):
            logger.warning(
                f"空仓不足: 需要 {amount:.8f}, 可用 {abs(self.position.amount):.8f}"
            )
            return None

        # 计算平仓成本和盈亏
        buy_cost = price * amount
        fee = buy_cost * self.fee_rate

        # 计算盈亏（做空：高价卖低价买=盈利）
        price_pnl = self.position.avg_price - price  # 做空：价格下跌盈利
        gross_pnl = price_pnl * amount
        net_pnl = gross_pnl - fee

        # 计算收益率（相对于开仓时的保证金）
        open_margin = (self.position.avg_price * amount) / self.leverage
        pnl_percent = (net_pnl / open_margin) * 100 if open_margin > 0 else 0.0

        # 释放的保证金（基于开仓价格）
        margin_released = open_margin

        # 记录交易前状态
        position_before = self.position.amount
        capital_before = self.capital

        # 更新持仓
        self.position.amount += amount  # 负数加正数
        if self.position.amount >= 0:
            self.position.amount = 0
            self.position.avg_price = 0
            self.position.direction = "flat"
            self.position.margin_used = 0
        else:
            self.position.margin_used = (
                abs(self.position.amount) * self.position.avg_price / self.leverage
            )

        # 更新资金（返还保证金 + 盈亏）
        self.capital += margin_released + net_pnl
        self.margin_account.margin_used = self.position.margin_used

        # 记录交易后状态
        position_after = self.position.amount
        capital_after = self.capital

        # 创建交易记录
        trade = Trade(
            timestamp=timestamp,
            side="buy",  # 平空是买入
            price=price,
            amount=amount,
            fee=fee,
            position_before=position_before,
            position_after=position_after,
            capital_before=capital_before,
            capital_after=capital_after,
            pnl=net_pnl,
            pnl_percent=pnl_percent,
            direction="short",
            leverage=self.leverage,
            margin_used=margin_released,
        )

        self.trades.append(trade)
        logger.debug(
            f"平空仓: {amount:.8f} @ {price:.2f}, 盈亏: {net_pnl:.2f} ({pnl_percent:.2f}%)"
        )

        return trade

    def check_liquidation(self, current_price: float) -> bool:
        """
        检查是否触发强平

        Args:
            current_price: 当前价格

        Returns:
            是否触发强平
        """
        if self.position.amount == 0:
            return False

        position_value = abs(self.position.amount) * current_price

        # 计算未实现盈亏
        if self.position.direction == "long":
            unrealized_pnl = (
                current_price - self.position.avg_price
            ) * self.position.amount
        elif self.position.direction == "short":
            unrealized_pnl = (self.position.avg_price - current_price) * abs(
                self.position.amount
            )
        else:
            return False

        # 计算保证金率
        margin_ratio = (
            (self.position.margin_used + unrealized_pnl) / position_value
            if position_value > 0
            else 0
        )

        # 强平阈值
        liquidation_threshold = 1 / self.leverage * (1 - self.margin_call_ratio)

        return margin_ratio < liquidation_threshold

    def execute_liquidation(
        self, current_price: float, timestamp: int
    ) -> Optional[Trade]:
        """
        执行强平

        Args:
            current_price: 当前价格
            timestamp: 时间戳

        Returns:
            强平交易记录
        """
        if self.position.amount == 0:
            return None

        logger.warning(
            f"触发强平! 当前价格: {current_price}, 持仓: {self.position.amount}"
        )

        # 强平所有持仓
        if self.position.direction == "long":
            trade = self.sell(current_price, self.position.amount, timestamp)
        elif self.position.direction == "short":
            trade = self.cover(current_price, abs(self.position.amount), timestamp)
        else:
            return None

        if trade:
            self.liquidation_count += 1
            self.liquidated = True
            logger.warning(f"强平执行完成，累计强平次数: {self.liquidation_count}")

        return trade

    def update_equity(self, current_price: float, timestamp: int):
        """
        更新资金曲线

        Args:
            current_price: 当前价格
            timestamp: 时间戳
        """
        # 计算未实现盈亏（支持做多和做空）
        if self.position.amount > 0:
            # 做多未实现盈亏
            market_value = current_price * self.position.amount
            cost_basis = self.position.avg_price * self.position.amount
            self.position.unrealized_pnl = market_value - cost_basis
            position_value = market_value
        elif self.position.amount < 0:
            # 做空未实现盈亏
            short_amount = abs(self.position.amount)
            sell_revenue = self.position.avg_price * short_amount
            buy_cost = current_price * short_amount
            self.position.unrealized_pnl = sell_revenue - buy_cost
            position_value = self.position.margin_used  # 做空时仓位价值为保证金
        else:
            self.position.unrealized_pnl = 0.0
            position_value = 0

        # 计算总权益
        total_equity = self.capital + self.position.unrealized_pnl

        # 记录到资金曲线
        self.equity_curve.append(
            {
                "timestamp": timestamp,
                "equity": total_equity,
                "capital": self.capital,
                "position_value": position_value,
                "unrealized_pnl": self.position.unrealized_pnl,
                "position_direction": self.position.direction,
                "leverage": self.leverage,
            }
        )

    def get_total_equity(self, current_price: float) -> float:
        """
        获取当前总权益

        Args:
            current_price: 当前价格

        Returns:
            总权益
        """
        if self.position.amount > 0:
            # 做多：资金 + 持仓价值
            return self.capital + (current_price * self.position.amount)
        elif self.position.amount < 0:
            # 做空：资金 + 未实现盈亏
            short_amount = abs(self.position.amount)
            unrealized_pnl = (self.position.avg_price - current_price) * short_amount
            return self.capital + unrealized_pnl
        else:
            return self.capital

    def on_kline(self, kline: Dict):
        """
        处理K线数据（由子类实现策略逻辑）

        Args:
            kline: K线数据
        """
        raise NotImplementedError("子类必须实现 on_kline 方法")

    def run(
        self, klines: List[Dict], progress_callback: Optional[Callable] = None
    ) -> Dict:
        """
        运行回测

        Args:
            klines: K线数据列表（按时间升序）
            progress_callback: 进度回调函数 callback(current, total)

        Returns:
            回测结果
        """
        logger.info(
            f"开始回测: {self.symbol}, 初始资金: {self.initial_capital}, K线数量: {len(klines)}, 杠杆: {self.leverage}x, 做空: {self.enable_short}"
        )

        self.reset()

        total_klines = len(klines)

        for i, kline in enumerate(klines):
            self.current_index = i
            self.current_kline = kline

            close_price = float(kline["close"])
            timestamp = int(kline["timestamp"])

            # 检查强平（杠杆模式下）
            if self.leverage > 1 and self.check_liquidation(close_price):
                self.execute_liquidation(close_price, timestamp)

            # 调用策略逻辑（如果未强平）
            if not self.liquidated:
                self.on_kline(kline)

            # 更新资金曲线
            self.update_equity(close_price, timestamp)

            # 进度回调
            if progress_callback and i % 100 == 0:
                progress_callback(i + 1, total_klines)

        # 最终进度
        if progress_callback:
            progress_callback(total_klines, total_klines)

        # 强制平掉期末持仓，确保所有盈亏都体现在交易记录中
        if klines and self.position.amount != 0:
            final_price = float(klines[-1]["close"])
            final_ts = int(klines[-1]["timestamp"])
            if self.position.amount > 0:
                logger.info(
                    f"回测结束，强制平多仓: {self.position.amount:.8f} @ {final_price:.2f}"
                )
                self.sell(final_price, self.position.amount, final_ts)
            elif self.position.amount < 0:
                logger.info(
                    f"回测结束，强制平空仓: {abs(self.position.amount):.8f} @ {final_price:.2f}"
                )
                self.cover(final_price, abs(self.position.amount), final_ts)

        # 计算最终权益
        if klines:
            final_price = float(klines[-1]["close"])
            final_equity = self.get_total_equity(final_price)
        else:
            final_equity = self.initial_capital

        logger.info(
            f"回测完成: 最终权益: {final_equity:.2f}, 交易次数: {len(self.trades)}, 强平次数: {self.liquidation_count}"
        )

        return {
            "final_equity": final_equity,
            "total_trades": len(self.trades),
            "initial_capital": self.initial_capital,
            "liquidation_count": self.liquidation_count,
            "leverage": self.leverage,
        }
