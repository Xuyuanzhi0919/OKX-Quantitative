"""
回测性能指标计算
"""

from typing import List, Dict
import numpy as np
from datetime import datetime


class BacktestMetrics:
    """回测性能指标计算器"""

    @staticmethod
    def calculate_total_return(initial_capital: float, final_capital: float) -> float:
        """
        计算总收益率

        Args:
            initial_capital: 初始资金
            final_capital: 最终资金

        Returns:
            总收益率（小数形式，如0.15表示15%）
        """
        if initial_capital <= 0:
            return 0.0
        return (final_capital - initial_capital) / initial_capital

    @staticmethod
    def calculate_annualized_return(
        total_return: float, start_timestamp: int, end_timestamp: int
    ) -> float:
        """
        计算年化收益率

        Args:
            total_return: 总收益率
            start_timestamp: 开始时间戳(毫秒)
            end_timestamp: 结束时间戳(毫秒)

        Returns:
            年化收益率
        """
        # 计算天数
        days = (end_timestamp - start_timestamp) / (1000 * 60 * 60 * 24)

        if days <= 0:
            return 0.0

        # 年化收益率公式: (1 + total_return) ^ (365 / days) - 1
        years = days / 365.0
        annualized = (1 + total_return) ** (1 / years) - 1

        return annualized

    @staticmethod
    def calculate_max_drawdown(equity_curve: List[Dict]) -> float:
        """
        计算最大回撤

        Args:
            equity_curve: 资金曲线 [{timestamp, equity}, ...]

        Returns:
            最大回撤（小数形式，如0.15表示15%）
        """
        if not equity_curve:
            return 0.0

        equities = [point["equity"] for point in equity_curve]

        max_drawdown = 0.0
        peak = equities[0]

        for equity in equities:
            # 更新峰值
            if equity > peak:
                peak = equity

            # 计算当前回撤
            if peak > 0:
                drawdown = (peak - equity) / peak
                max_drawdown = max(max_drawdown, drawdown)

        return max_drawdown

    @staticmethod
    def calculate_sharpe_ratio(
        equity_curve: List[Dict], risk_free_rate: float = 0.02
    ) -> float:
        """
        计算夏普比率

        Args:
            equity_curve: 资金曲线
            risk_free_rate: 无风险利率（年化，默认2%）

        Returns:
            夏普比率
        """
        if len(equity_curve) < 2:
            return 0.0

        # 计算日收益率
        equities = [point["equity"] for point in equity_curve]
        returns = []

        for i in range(1, len(equities)):
            if equities[i - 1] > 0:
                daily_return = (equities[i] - equities[i - 1]) / equities[i - 1]
                returns.append(daily_return)

        if not returns:
            return 0.0

        # 计算日均收益和标准差
        avg_return = np.mean(returns)
        std_return = np.std(returns)

        if std_return == 0:
            return 0.0

        # 日无风险收益率
        daily_risk_free = risk_free_rate / 252  # 假设一年252个交易日

        # 夏普比率 = (平均收益 - 无风险收益) / 收益标准差
        sharpe = (avg_return - daily_risk_free) / std_return

        # 年化夏普比率
        annualized_sharpe = sharpe * np.sqrt(252)

        return annualized_sharpe

    @staticmethod
    def calculate_win_rate(trades: List[Dict]) -> float:
        """
        计算胜率

        Args:
            trades: 交易记录列表

        Returns:
            胜率（小数形式）
        """
        if not trades:
            return 0.0

        # 只统计已平仓交易；多单平仓通常是 sell，空单平仓通常是 buy。
        sell_trades = [t for t in trades if t.get("pnl", 0) != 0]

        if not sell_trades:
            return 0.0

        winning_trades = sum(1 for t in sell_trades if t.get("pnl", 0) > 0)

        return winning_trades / len(sell_trades)

    @staticmethod
    def calculate_profit_factor(trades: List[Dict]) -> float:
        """
        计算盈亏比（Profit Factor）

        Args:
            trades: 交易记录列表

        Returns:
            盈亏比
        """
        if not trades:
            return 0.0

        # 只统计已平仓交易；多空策略里空单平仓是 buy，不能只看 sell。
        sell_trades = [t for t in trades if t.get("pnl", 0) != 0]

        if not sell_trades:
            return 0.0

        total_profit = sum(t.get("pnl", 0) for t in sell_trades if t.get("pnl", 0) > 0)
        total_loss = abs(
            sum(t.get("pnl", 0) for t in sell_trades if t.get("pnl", 0) < 0)
        )

        if total_loss == 0:
            return float("inf") if total_profit > 0 else 0.0

        return total_profit / total_loss

    @staticmethod
    def calculate_all_metrics(
        initial_capital: float,
        final_capital: float,
        equity_curve: List[Dict],
        trades: List[Dict],
        start_timestamp: int,
        end_timestamp: int,
    ) -> Dict:
        """
        计算所有性能指标

        Args:
            initial_capital: 初始资金
            final_capital: 最终资金
            equity_curve: 资金曲线
            trades: 交易记录
            start_timestamp: 开始时间戳
            end_timestamp: 结束时间戳

        Returns:
            所有指标的字典
        """
        # 总收益率
        total_return = BacktestMetrics.calculate_total_return(
            initial_capital, final_capital
        )

        # 年化收益率
        annualized_return = BacktestMetrics.calculate_annualized_return(
            total_return, start_timestamp, end_timestamp
        )

        # 最大回撤
        max_drawdown = BacktestMetrics.calculate_max_drawdown(equity_curve)

        # 夏普比率
        sharpe_ratio = BacktestMetrics.calculate_sharpe_ratio(equity_curve)

        # 交易统计
        sell_trades = [t for t in trades if t.get("side") == "sell"]
        winning_trades = sum(1 for t in sell_trades if t.get("pnl", 0) > 0)
        losing_trades = sum(1 for t in sell_trades if t.get("pnl", 0) <= 0)

        # 胜率
        win_rate = BacktestMetrics.calculate_win_rate(trades)

        # 盈亏比
        profit_factor = BacktestMetrics.calculate_profit_factor(trades)

        # 总手续费
        total_fee = sum(t.get("fee", 0) for t in trades)

        return {
            "total_return": total_return,
            "annualized_return": annualized_return,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe_ratio,
            "total_trades": len(trades),
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_fee": total_fee,
        }
