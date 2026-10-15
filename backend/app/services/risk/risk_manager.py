"""
风控管理器 - 核心风控逻辑
"""

from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from datetime import datetime, timedelta
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models import RiskControl, RiskAction, Alert, Strategy, Order, Position
from app.services.exchange.okx import OKXExchange


class RiskManager:
    """风控管理器"""

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self.exchange = None  # 延迟初始化

    def set_exchange(self, exchange: OKXExchange):
        """设置交易所实例"""
        self.exchange = exchange

    async def check_all_risks(self, strategy_id: Optional[int] = None) -> List[Dict]:
        """
        检查所有风控规则

        Args:
            strategy_id: 策略ID，如果为None则检查所有策略

        Returns:
            触发的风控规则列表
        """
        triggered_rules = []

        # 加载启用的风控规则
        query = self.db.query(RiskControl).filter(
            RiskControl.user_id == self.user_id, RiskControl.is_enabled == True
        )

        if strategy_id:
            query = query.filter(
                and_(
                    RiskControl.strategy_id == strategy_id,
                    RiskControl.level == "strategy",
                )
            )

        rules = query.all()

        for rule in rules:
            # 检查资金风控
            if rule.risk_type == "capital":
                result = await self._check_capital_risk(rule, strategy_id)
                if result:
                    triggered_rules.append(result)

            # 检查持仓风控
            elif rule.risk_type == "position":
                result = await self._check_position_risk(rule, strategy_id)
                if result:
                    triggered_rules.append(result)

            # 检查亏损风控
            elif rule.risk_type == "loss":
                result = await self._check_loss_risk(rule, strategy_id)
                if result:
                    triggered_rules.append(result)

            # 检查回撤风控
            elif rule.risk_type == "drawdown":
                result = await self._check_drawdown_risk(rule, strategy_id)
                if result:
                    triggered_rules.append(result)

            # 检查频率风控
            elif rule.risk_type == "frequency":
                result = await self._check_frequency_risk(rule, strategy_id)
                if result:
                    triggered_rules.append(result)

        return triggered_rules

    async def _check_capital_risk(
        self, rule: RiskControl, strategy_id: Optional[int]
    ) -> Optional[Dict]:
        """检查资金风控"""
        try:
            # 获取账户余额
            if not self.exchange:
                logger.warning("交易所实例未设置，跳过资金风控检查")
                return None

            balance = await self.exchange.get_balance()
            available_balance = float(balance.get("availBal", 0))

            # 检查最小可用资金
            if (
                rule.min_available_balance
                and available_balance < rule.min_available_balance
            ):
                risk_percent = available_balance / rule.min_available_balance
                is_warning = risk_percent >= (rule.warning_threshold or 0.8)

                return {
                    "rule": rule,
                    "risk_type": "capital",
                    "severity": "warning" if is_warning else "error",
                    "message": f"可用资金不足: 当前 {available_balance:.2f} USDT, 最低要求 {rule.min_available_balance:.2f} USDT",
                    "metrics": {
                        "available_balance": available_balance,
                        "min_required": rule.min_available_balance,
                        "risk_percent": risk_percent,
                    },
                }

            # 获取持仓总价值
            positions = await self.exchange.get_positions()
            total_position_value = sum(
                [abs(float(pos.get("notionalUsd", 0))) for pos in positions]
            )

            # 检查最大持仓价值
            if (
                rule.max_position_value
                and total_position_value > rule.max_position_value
            ):
                risk_percent = total_position_value / rule.max_position_value

                return {
                    "rule": rule,
                    "risk_type": "capital",
                    "severity": "error",
                    "message": f"持仓价值超限: 当前 {total_position_value:.2f} USDT, 上限 {rule.max_position_value:.2f} USDT",
                    "metrics": {
                        "total_position_value": total_position_value,
                        "max_allowed": rule.max_position_value,
                        "risk_percent": risk_percent,
                    },
                }

            return None

        except Exception as e:
            logger.error(f"检查资金风控失败: {e}")
            return None

    async def _check_position_risk(
        self, rule: RiskControl, strategy_id: Optional[int]
    ) -> Optional[Dict]:
        """检查持仓风控"""
        try:
            if not self.exchange:
                return None

            positions = await self.exchange.get_positions()

            # 检查单币种持仓上限
            if rule.max_position_per_symbol:
                for pos in positions:
                    pos_amt = abs(float(pos.get("pos", 0)))
                    symbol = pos.get("instId", "")

                    if pos_amt > rule.max_position_per_symbol:
                        return {
                            "rule": rule,
                            "risk_type": "position",
                            "severity": "error",
                            "message": f"{symbol} 持仓超限: {pos_amt:.4f} > {rule.max_position_per_symbol:.4f}",
                            "metrics": {
                                "symbol": symbol,
                                "position": pos_amt,
                                "max_allowed": rule.max_position_per_symbol,
                            },
                        }

            # 检查持仓集中度
            if rule.max_concentration_ratio and len(positions) > 0:
                total_value = sum(
                    [abs(float(p.get("notionalUsd", 0))) for p in positions]
                )
                max_single = max(
                    [abs(float(p.get("notionalUsd", 0))) for p in positions]
                )

                if total_value > 0:
                    concentration = max_single / total_value

                    if concentration > rule.max_concentration_ratio:
                        return {
                            "rule": rule,
                            "risk_type": "position",
                            "severity": "warning",
                            "message": f"持仓集中度过高: {concentration*100:.1f}% > {rule.max_concentration_ratio*100:.1f}%",
                            "metrics": {
                                "concentration": concentration,
                                "max_allowed": rule.max_concentration_ratio,
                                "total_value": total_value,
                                "max_single": max_single,
                            },
                        }

            return None

        except Exception as e:
            logger.error(f"检查持仓风控失败: {e}")
            return None

    async def _check_loss_risk(
        self, rule: RiskControl, strategy_id: Optional[int]
    ) -> Optional[Dict]:
        """检查亏损风控"""
        try:
            if strategy_id:
                # 策略级风控
                strategy = (
                    self.db.query(Strategy).filter(Strategy.id == strategy_id).first()
                )
                if not strategy:
                    return None

                total_profit = float(strategy.total_profit or 0)

                # 检查日亏损限额
                if rule.daily_loss_limit:
                    # 计算今日亏损
                    today_start = datetime.now().replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    today_orders = (
                        self.db.query(Order)
                        .filter(
                            Order.strategy_id == strategy_id,
                            Order.status == "filled",
                            Order.created_at >= today_start,
                        )
                        .all()
                    )

                    today_loss = sum(
                        [
                            float(o.realized_pnl or 0)
                            for o in today_orders
                            if float(o.realized_pnl or 0) < 0
                        ]
                    )

                    if abs(today_loss) > rule.daily_loss_limit:
                        return {
                            "rule": rule,
                            "risk_type": "loss",
                            "severity": "error",
                            "message": f"日亏损超限: {today_loss:.2f} USDT < -{rule.daily_loss_limit:.2f} USDT",
                            "metrics": {
                                "today_loss": today_loss,
                                "daily_limit": rule.daily_loss_limit,
                            },
                        }

                # 检查总亏损限额
                if rule.total_loss_limit and total_profit < -rule.total_loss_limit:
                    return {
                        "rule": rule,
                        "risk_type": "loss",
                        "severity": "error",
                        "message": f"总亏损超限: {total_profit:.2f} USDT < -{rule.total_loss_limit:.2f} USDT",
                        "metrics": {
                            "total_profit": total_profit,
                            "total_limit": rule.total_loss_limit,
                        },
                    }

                # 检查连续亏损次数
                if rule.max_consecutive_losses:
                    recent_orders = (
                        self.db.query(Order)
                        .filter(
                            Order.strategy_id == strategy_id, Order.status == "filled"
                        )
                        .order_by(Order.created_at.desc())
                        .limit(rule.max_consecutive_losses + 5)
                        .all()
                    )

                    consecutive_losses = 0
                    for order in recent_orders:
                        pnl = float(order.realized_pnl or 0)
                        if pnl < 0:
                            consecutive_losses += 1
                        else:
                            break

                    if consecutive_losses >= rule.max_consecutive_losses:
                        return {
                            "rule": rule,
                            "risk_type": "loss",
                            "severity": "warning",
                            "message": f"连续亏损次数过多: {consecutive_losses} >= {rule.max_consecutive_losses}",
                            "metrics": {
                                "consecutive_losses": consecutive_losses,
                                "max_allowed": rule.max_consecutive_losses,
                            },
                        }

            return None

        except Exception as e:
            logger.error(f"检查亏损风控失败: {e}")
            return None

    async def _check_drawdown_risk(
        self, rule: RiskControl, strategy_id: Optional[int]
    ) -> Optional[Dict]:
        """检查回撤风控"""
        try:
            if not strategy_id:
                return None

            strategy = (
                self.db.query(Strategy).filter(Strategy.id == strategy_id).first()
            )
            if not strategy:
                return None

            # 获取历史最高盈利
            orders = (
                self.db.query(Order)
                .filter(Order.strategy_id == strategy_id, Order.status == "filled")
                .order_by(Order.created_at)
                .all()
            )

            if not orders:
                return None

            # 计算累计盈亏曲线
            cumulative_pnl = []
            cum_sum = 0
            for order in orders:
                cum_sum += float(order.realized_pnl or 0)
                cumulative_pnl.append(cum_sum)

            # 计算最大回撤
            peak = cumulative_pnl[0]
            max_drawdown = 0

            for pnl in cumulative_pnl:
                if pnl > peak:
                    peak = pnl
                drawdown = (peak - pnl) / abs(peak) if peak != 0 else 0
                max_drawdown = max(max_drawdown, drawdown)

            # 检查最大回撤限制
            if rule.max_drawdown_percent and max_drawdown > rule.max_drawdown_percent:
                return {
                    "rule": rule,
                    "risk_type": "drawdown",
                    "severity": "error",
                    "message": f"最大回撤超限: {max_drawdown*100:.2f}% > {rule.max_drawdown_percent*100:.2f}%",
                    "metrics": {
                        "max_drawdown": max_drawdown,
                        "max_allowed": rule.max_drawdown_percent,
                        "peak_pnl": peak,
                        "current_pnl": cumulative_pnl[-1],
                    },
                }

            return None

        except Exception as e:
            logger.error(f"检查回撤风控失败: {e}")
            return None

    async def _check_frequency_risk(
        self, rule: RiskControl, strategy_id: Optional[int]
    ) -> Optional[Dict]:
        """检查交易频率风控"""
        try:
            if (
                not strategy_id
                or not rule.max_trades_per_period
                or not rule.period_seconds
            ):
                return None

            # 计算时间窗口
            period_start = datetime.now() - timedelta(seconds=rule.period_seconds)

            # 统计时间窗口内的交易次数
            trade_count = (
                self.db.query(Order)
                .filter(
                    Order.strategy_id == strategy_id,
                    Order.status == "filled",
                    Order.created_at >= period_start,
                )
                .count()
            )

            if trade_count > rule.max_trades_per_period:
                return {
                    "rule": rule,
                    "risk_type": "frequency",
                    "severity": "warning",
                    "message": f"交易频率过高: {trade_count} 次 > {rule.max_trades_per_period} 次 / {rule.period_seconds}秒",
                    "metrics": {
                        "trade_count": trade_count,
                        "max_allowed": rule.max_trades_per_period,
                        "period_seconds": rule.period_seconds,
                    },
                }

            return None

        except Exception as e:
            logger.error(f"检查交易频率风控失败: {e}")
            return None

    async def execute_risk_action(self, triggered_risk: Dict) -> bool:
        """
        执行风控动作

        Args:
            triggered_risk: 触发的风控规则信息

        Returns:
            是否执行成功
        """
        try:
            rule: RiskControl = triggered_risk["rule"]
            action_type = rule.action_on_trigger
            strategy_id = rule.strategy_id

            logger.warning(
                f"执行风控动作: {action_type}, 规则: {rule.name}, 策略: {strategy_id}"
            )

            # 记录风控动作
            risk_action = RiskAction(
                user_id=self.user_id,
                strategy_id=strategy_id,
                risk_control_id=rule.id,
                action_type=action_type,
                trigger_reason=triggered_risk["message"],
                risk_metrics=str(triggered_risk["metrics"]),
                execution_status="pending",
            )
            self.db.add(risk_action)
            self.db.commit()

            # 执行对应动作
            if action_type == "warn":
                # 仅发送警告
                await self._send_alert(triggered_risk)
                risk_action.execution_status = "success"

            elif action_type == "limit":
                # 限制新订单
                await self._send_alert(triggered_risk)
                # 实际限制逻辑在策略下单时检查
                risk_action.execution_status = "success"

            elif action_type == "pause":
                # 暂停策略
                success = await self._pause_strategy(strategy_id)
                risk_action.execution_status = "success" if success else "failed"

            elif action_type == "close":
                # 平仓
                success = await self._close_positions(strategy_id)
                risk_action.execution_status = "success" if success else "failed"

            # 更新规则触发状态
            rule.is_triggered = True
            rule.trigger_count += 1
            rule.last_trigger_at = datetime.now()

            self.db.commit()

            return risk_action.execution_status == "success"

        except Exception as e:
            logger.error(f"执行风控动作失败: {e}")
            return False

    async def _send_alert(self, triggered_risk: Dict):
        """发送风控预警"""
        try:
            rule: RiskControl = triggered_risk["rule"]

            alert = Alert(
                user_id=self.user_id,
                strategy_id=rule.strategy_id,
                alert_type="risk_warning",
                severity=triggered_risk["severity"],
                title=f"风控预警: {rule.name}",
                message=triggered_risk["message"],
                data=str(triggered_risk["metrics"]),
            )
            self.db.add(alert)
            self.db.commit()

            logger.warning(f"风控预警: {triggered_risk['message']}")

        except Exception as e:
            logger.error(f"发送风控预警失败: {e}")

    async def _pause_strategy(self, strategy_id: int) -> bool:
        """暂停策略"""
        try:
            if not strategy_id:
                return False

            strategy = (
                self.db.query(Strategy).filter(Strategy.id == strategy_id).first()
            )
            if not strategy:
                return False

            strategy.status = "stopped"
            self.db.commit()

            logger.info(f"策略 {strategy_id} 已被风控暂停")
            return True

        except Exception as e:
            logger.error(f"暂停策略失败: {e}")
            return False

    async def _close_positions(self, strategy_id: int) -> bool:
        """平仓（市价卖出）"""
        try:
            if not self.exchange or not strategy_id:
                return False

            strategy = (
                self.db.query(Strategy).filter(Strategy.id == strategy_id).first()
            )
            if not strategy:
                return False

            # 获取策略持仓
            positions = await self.exchange.get_positions()
            symbol = strategy.symbol

            for pos in positions:
                if pos.get("instId") == symbol:
                    pos_amt = float(pos.get("pos", 0))

                    if pos_amt > 0:
                        # 市价卖出
                        await self.exchange.create_order(
                            symbol=symbol,
                            side="sell",
                            order_type="market",
                            amount=abs(pos_amt),
                        )
                        logger.info(f"风控平仓: {symbol}, 数量: {pos_amt}")

            # 暂停策略
            strategy.status = "stopped"
            self.db.commit()

            return True

        except Exception as e:
            logger.error(f"风控平仓失败: {e}")
            return False

    async def check_before_order(
        self, strategy_id: int, order_amount: float
    ) -> Tuple[bool, Optional[str]]:
        """
        下单前风控检查

        Args:
            strategy_id: 策略ID
            order_amount: 订单金额

        Returns:
            (是否通过, 拒绝原因)
        """
        # 检查单笔订单金额限制
        rules = (
            self.db.query(RiskControl)
            .filter(
                RiskControl.user_id == self.user_id,
                RiskControl.strategy_id == strategy_id,
                RiskControl.is_enabled == True,
                RiskControl.max_order_amount.isnot(None),
            )
            .all()
        )

        for rule in rules:
            if order_amount > rule.max_order_amount:
                return (
                    False,
                    f"订单金额超限: {order_amount:.2f} > {rule.max_order_amount:.2f} USDT",
                )

        # 检查是否有触发的风控规则限制交易
        triggered_rules = await self.check_all_risks(strategy_id)
        for risk in triggered_rules:
            rule = risk["rule"]
            if rule.action_on_trigger in ["limit", "pause", "close"]:
                return False, f"风控限制: {risk['message']}"

        return True, None
