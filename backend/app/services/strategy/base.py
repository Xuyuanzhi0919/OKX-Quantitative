"""
策略基类
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from decimal import Decimal
from app.services.exchange.base import ExchangeBase
import asyncio
from loguru import logger
from datetime import date, datetime


class InsufficientBalanceError(Exception):
    """余额不足异常"""

    pass


class StrategyBase(ABC):
    """策略抽象基类"""

    def __init__(
        self,
        strategy_id: int,
        exchange: ExchangeBase,
        symbol: str,
        parameters: Dict,
        user_id: int = 1,  # 默认用户ID,后续从策略记录中获取
    ):
        """
        初始化策略

        Args:
            strategy_id: 策略ID
            exchange: 交易所实例
            symbol: 交易对
            parameters: 策略参数
            user_id: 用户ID
        """
        self.strategy_id = strategy_id
        self.exchange = exchange
        self.symbol = symbol
        self.parameters = parameters
        self.user_id = user_id
        self.is_running = False

        # 运行期交易质量追踪
        self.consecutive_losses: int = 0  # 当前连续亏损次数
        self.max_consecutive_losses: int = 0  # 历史最大连续亏损次数
        self.trade_pnl_history: list = []  # 最近平仓交易盈亏（最新在末尾）
        self.runtime_realized_pnl: float = 0.0  # 本次运行累计已实现盈亏
        self.runtime_equity_peak: float = 0.0  # 本次运行已实现盈亏曲线峰值
        self.max_runtime_drawdown: float = 0.0  # 本次运行最大回撤（绝对金额）
        self.daily_realized_pnl: float = 0.0  # 当日已实现盈亏
        self._daily_pnl_date: date = datetime.now().date()
        self.last_ticker_at: Optional[float] = None
        self.last_tick_ok_at: Optional[float] = None
        self.last_error_at: Optional[float] = None
        self.last_error_message: Optional[str] = None

    def record_trade_result(self, pnl: float) -> None:
        """
        记录一笔平仓交易的盈亏，更新连续亏损计数器。
        子类在确认一笔完整买卖循环结束时调用（如 sell 成交后）。

        Args:
            pnl: 本次平仓的已实现盈亏（正盈负亏）
        """
        today = datetime.now().date()
        if today != self._daily_pnl_date:
            self._daily_pnl_date = today
            self.daily_realized_pnl = 0.0

        self.runtime_realized_pnl += pnl
        self.daily_realized_pnl += pnl
        self.runtime_equity_peak = max(
            self.runtime_equity_peak, self.runtime_realized_pnl
        )
        self.max_runtime_drawdown = max(
            self.max_runtime_drawdown,
            self.runtime_equity_peak - self.runtime_realized_pnl,
        )

        self.trade_pnl_history.append(round(pnl, 4))
        if len(self.trade_pnl_history) > 50:
            self.trade_pnl_history.pop(0)

        if pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses > self.max_consecutive_losses:
                self.max_consecutive_losses = self.consecutive_losses
        else:
            self.consecutive_losses = 0

        logger.debug(
            f"策略 {self.strategy_id} 交易结果记录: pnl={pnl:.4f}, "
            f"runtime_pnl={self.runtime_realized_pnl:.4f}, daily_pnl={self.daily_realized_pnl:.4f}, "
            f"drawdown={self.max_runtime_drawdown:.4f}, consecutive_losses={self.consecutive_losses}, "
            f"max={self.max_consecutive_losses}"
        )

    def runtime_profit_factor(self, window: int = 10) -> Optional[float]:
        """计算最近若干笔平仓交易的盈亏比。"""
        recent_trades = (
            self.trade_pnl_history[-window:] if window > 0 else self.trade_pnl_history
        )
        if not recent_trades:
            return None

        gross_profit = sum(pnl for pnl in recent_trades if pnl > 0)
        gross_loss = abs(sum(pnl for pnl in recent_trades if pnl < 0))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else None
        return gross_profit / gross_loss

    @abstractmethod
    async def on_tick(self, ticker: Dict):
        """
        处理实时行情

        Args:
            ticker: 实时价格数据
        """
        pass

    @abstractmethod
    async def on_kline(self, kline: Dict):
        """
        处理K线数据

        Args:
            kline: K线数据
        """
        pass

    @abstractmethod
    async def on_order_update(self, order: Dict):
        """
        处理订单更新

        Args:
            order: 订单信息
        """
        pass

    @abstractmethod
    async def start(self):
        """启动策略"""
        self.is_running = True

    @abstractmethod
    async def stop(self):
        """停止策略"""
        self.is_running = False

    async def _save_order_to_db(
        self,
        order_data: Dict,
        side: str,
        order_type: str,
        price: Optional[Decimal],
        amount: Decimal,
    ):
        """
        保存订单到数据库

        Args:
            order_data: 交易所返回的订单数据
            side: 买卖方向
            order_type: 订单类型
            price: 委托价格
            amount: 委托数量
        """
        from app.core.database import SessionLocal
        from app.models.order import Order, OrderSide, OrderType, OrderStatus

        db = SessionLocal()
        try:
            logger.debug(
                f"开始保存订单: order_id={order_data.get('ordId')}, symbol={self.symbol}"
            )

            # 映射订单状态
            status_map = {
                "live": OrderStatus.SUBMITTED,
                "partially_filled": OrderStatus.PARTIAL_FILLED,
                "filled": OrderStatus.FILLED,
                "canceled": OrderStatus.CANCELED,
            }

            # 提取字段 - 兼容OKX API格式和其他格式
            # OKX API格式: ordId, state, accFillSz, avgPx, feeCcy
            # 标准格式: order_id, status, filled_amount, avg_price, fee_currency
            order_id = order_data.get("ordId") or order_data.get("order_id")
            okx_state = order_data.get("state") or order_data.get("status")
            filled_amount = order_data.get("accFillSz") or order_data.get(
                "filled_amount", 0
            )
            avg_price = order_data.get("avgPx") or order_data.get("avg_price")
            fee_currency = order_data.get("feeCcy") or order_data.get("fee_currency")

            db_order = Order(
                user_id=self.user_id,
                strategy_id=self.strategy_id,
                order_id=order_id,
                symbol=self.symbol,
                side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                order_type=(
                    OrderType.LIMIT
                    if order_type == "limit"
                    else (
                        OrderType.MARKET
                        if order_type == "market"
                        else (
                            OrderType.IOC
                            if order_type == "ioc"
                            else (
                                OrderType.POST_ONLY
                                if order_type == "post_only"
                                else (
                                    OrderType.STOP_LIMIT
                                    if order_type == "stop_limit"
                                    else (
                                        OrderType.STOP_MARKET
                                        if order_type == "stop_market"
                                        else OrderType.MARKET
                                    )
                                )
                            )
                        )
                    )  # Default to market if unknown
                ),
                status=status_map.get(okx_state, OrderStatus.SUBMITTED),
                price=float(price) if price else None,
                amount=float(amount),
                filled_amount=float(filled_amount) if filled_amount else 0,
                avg_price=float(avg_price) if avg_price else None,
                fee=float(order_data.get("fee", 0)),
                fee_currency=fee_currency,
                submitted_at=datetime.now(),
            )

            logger.debug("准备添加订单到session")
            db.add(db_order)
            logger.debug("准备commit")
            db.commit()
            logger.debug("Commit成功，准备refresh")
            db.refresh(db_order)
            logger.debug("Refresh成功")

            logger.info(
                f"✅ 订单已成功保存到数据库: ID={db_order.id}, OrderID={db_order.order_id}, Symbol={db_order.symbol}"
            )
            return db_order

        except Exception as e:
            logger.error(f"❌ 保存订单到数据库失败: {e}")
            logger.error(f"Exception type: {type(e).__name__}")
            logger.error(f"订单数据: {order_data}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            db.rollback()
            return None
        finally:
            db.close()
            logger.debug("数据库session已关闭")

    async def buy(
        self,
        amount: Decimal,
        price: Optional[Decimal] = None,
        order_type: str = "limit",
    ) -> Dict:
        """
        买入

        Args:
            amount: 数量
            price: 价格（市价单不需要）
            order_type: 订单类型

        Returns:
            订单信息
        """
        return await self.exchange.create_order(
            symbol=self.symbol,
            side="buy",
            order_type=order_type,
            amount=amount,
            price=price,
        )

    async def sell(
        self,
        amount: Decimal,
        price: Optional[Decimal] = None,
        order_type: str = "limit",
    ) -> Dict:
        """
        卖出

        Args:
            amount: 数量
            price: 价格（市价单不需要）
            order_type: 订单类型

        Returns:
            订单信息
        """
        return await self.exchange.create_order(
            symbol=self.symbol,
            side="sell",
            order_type=order_type,
            amount=amount,
            price=price,
        )

    async def place_order_with_retry(
        self,
        side: str,
        amount: Decimal,
        price: Optional[Decimal] = None,
        order_type: str = "limit",
        max_retries: int = 3,
        retry_delay: float = 1.0,
        pos_side: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        带重试机制的下单方法

        Args:
            side: 买卖方向 (buy/sell)
            amount: 数量
            price: 价格（市价单不需要）
            order_type: 订单类型
            max_retries: 最大重试次数
            retry_delay: 重试间隔（秒）
            pos_side: 持仓方向 "long"/"short"(开平仓双向模式) 或 None(自动判断)
                开多: side="buy",  pos_side="long"
                平多: side="sell", pos_side="long"
                开空: side="sell", pos_side="short"
                平空: side="buy",  pos_side="short"

        Returns:
            订单信息，如果所有重试都失败则返回None
        """
        last_error = None

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"下单尝试 {attempt + 1}/{max_retries}: "
                    f"{side} {amount} @ {price} ({order_type}) pos_side={pos_side}"
                )

                # 根据交易对类型设置交易模式
                # SWAP/FUTURES需要保证金模式, SPOT使用非保证金模式
                if self.symbol.endswith("-SWAP") or self.symbol.endswith("-FUTURES"):
                    # 从策略参数获取保证金模式，默认逐仓
                    margin_mode = self.parameters.get("margin_mode", "isolated")
                    td_mode = margin_mode  # isolated(逐仓) 或 cross(全仓)
                    # 若调用方明确传入 pos_side("long"/"short")，使用双向持仓模式
                    # 否则默认 "net"（买卖模式）保持向后兼容
                    effective_pos_side = (
                        pos_side if pos_side in ("long", "short") else "net"
                    )
                else:
                    td_mode = "cash"  # 非保证金(现货)
                    effective_pos_side = None  # 现货无 posSide

                order = await self.exchange.create_order(
                    symbol=self.symbol,
                    side=side,
                    order_type=order_type,
                    amount=amount,
                    price=price,
                    td_mode=td_mode,
                    pos_side=effective_pos_side,
                )

                order_id = order.get("ordId")
                logger.info(f"订单创建成功: ordId={order_id}")

                # 市价单会立即成交，延迟查询完整订单信息（含 state/avgPx/accFillSz）
                order_detail = order
                if order_type == "market" and order_id:
                    try:
                        await asyncio.sleep(0.8)
                        order_detail = await self.exchange.get_order(
                            symbol=self.symbol, order_id=order_id
                        )
                        logger.info(
                            f"订单详情: state={order_detail.get('state')} "
                            f"avgPx={order_detail.get('avgPx')} "
                            f"accFillSz={order_detail.get('accFillSz')}"
                        )
                    except Exception as e:
                        logger.warning(f"查询订单详情失败，使用原始数据: {e}")

                # 保存订单到数据库
                await self._save_order_to_db(
                    order_detail, side, order_type, price, amount
                )

                return order_detail

            except Exception as e:
                last_error = e
                error_msg = str(e)

                # 解析错误类型
                if "51000" in error_msg or "Parameter sz error" in error_msg:
                    logger.error(f"订单参数错误（数量过小或格式错误）: {error_msg}")
                    # 参数错误不需要重试
                    return None
                elif (
                    "51008" in error_msg
                    or "Insufficient balance" in error_msg
                    or "insufficient" in error_msg.lower()
                ):
                    logger.error(f"余额不足，停止策略: {error_msg}")
                    # 抛出余额不足异常，让上层处理
                    raise InsufficientBalanceError(
                        f"账户余额不足，无法继续下单: {error_msg}"
                    )
                elif (
                    "51001" in error_msg
                    or "Order would trigger immediately" in error_msg
                ):
                    logger.warning(f"订单会立即成交（价格不合适）: {error_msg}")
                    # 价格问题不需要重试
                    return None
                else:
                    # 其他错误可以重试
                    logger.warning(
                        f"下单失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}"
                    )

                    if attempt < max_retries - 1:
                        logger.info(f"等待 {retry_delay} 秒后重试...")
                        await asyncio.sleep(retry_delay)
                    else:
                        logger.error(f"所有重试都失败: {error_msg}")

        return None
