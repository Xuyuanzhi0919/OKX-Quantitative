"""
回测执行服务
负责协调K线数据、回测引擎和结果存储
"""

from typing import Dict, Optional, Type, Callable
from sqlalchemy.orm import Session
from loguru import logger
from datetime import datetime

from app.models import Backtest, BacktestTrade, Kline
from .kline_service import KlineService
from .adaptive_grid_trend_backtest import AdaptiveGridTrendBacktestEngine
from .spot_perp_arbitrage_backtest import SpotPerpArbitrageBacktestEngine
from .fixed_tp_sl_backtest import FixedTpSlTrendBacktestEngine
from .backtest_engine import BacktestEngine
from .metrics import BacktestMetrics


# 策略类型注册表
BACKTEST_ENGINES: Dict[str, Type[BacktestEngine]] = {
    "adaptive_grid_trend": AdaptiveGridTrendBacktestEngine,
    "arbitrage": SpotPerpArbitrageBacktestEngine,
    "fixed_tp_sl": FixedTpSlTrendBacktestEngine,
}


def register_backtest_engine(strategy_type: str, engine_class: Type[BacktestEngine]):
    """
    注册新的回测引擎类型

    Args:
        strategy_type: 策略类型标识
        engine_class: 引擎类
    """
    BACKTEST_ENGINES[strategy_type] = engine_class
    logger.info(f"注册回测引擎: {strategy_type} -> {engine_class.__name__}")


def get_available_strategy_types() -> list:
    """获取可用的策略类型列表"""
    return list(BACKTEST_ENGINES.keys())


class BacktestService:
    """回测执行服务"""

    def __init__(self, db: Session):
        """
        初始化回测服务

        Args:
            db: 数据库会话
        """
        self.db = db

    def create_backtest(
        self,
        user_id: int,
        name: str,
        strategy_type: str,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
        initial_capital: float,
        parameters: Dict,
        description: Optional[str] = None,
    ) -> Backtest:
        """
        创建回测记录

        Args:
            user_id: 用户ID
            name: 回测名称
            strategy_type: 策略类型，目前仅支持 adaptive_grid_trend
            symbol: 交易对
            interval: K线周期
            start_time: 开始时间戳(毫秒)
            end_time: 结束时间戳(毫秒)
            initial_capital: 初始资金
            parameters: 策略参数
            description: 回测描述

        Returns:
            回测记录
        """
        if strategy_type not in BACKTEST_ENGINES:
            raise ValueError(
                f"不支持的策略类型: {strategy_type}，可用类型: {list(BACKTEST_ENGINES.keys())}"
            )

        backtest = Backtest(
            user_id=user_id,
            name=name,
            description=description,
            strategy_type=strategy_type,
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            initial_capital=initial_capital,
            parameters=parameters,
            status="pending",
            progress=0,
        )

        self.db.add(backtest)
        self.db.commit()
        self.db.refresh(backtest)

        logger.info(
            f"创建回测记录: ID={backtest.id}, 策略={strategy_type}, 交易对={symbol}"
        )

        return backtest

    async def run_backtest(self, backtest_id: int) -> Dict:
        """
        执行回测

        Args:
            backtest_id: 回测ID

        Returns:
            回测结果
        """
        # 获取回测记录
        backtest = self.db.query(Backtest).filter(Backtest.id == backtest_id).first()
        if not backtest:
            raise ValueError(f"回测记录不存在: {backtest_id}")

        try:
            # 更新状态为运行中
            backtest.status = "running"
            backtest.progress = 0
            self.db.commit()

            logger.info(
                f"开始执行回测: ID={backtest_id}, 策略={backtest.strategy_type}"
            )

            # 获取K线数据
            kline_service = KlineService(self.db, None)  # 不需要exchange
            klines = kline_service.query_klines(
                symbol=backtest.symbol,
                interval=backtest.interval,
                start_time=backtest.start_time,
                end_time=backtest.end_time,
            )

            if not klines:
                raise ValueError("没有K线数据，请先获取历史数据")

            logger.info(f"加载K线数据: {len(klines)} 条")

            # 转换为字典格式
            kline_dicts = [
                {
                    "timestamp": k.timestamp,
                    "open": float(k.open),
                    "high": float(k.high),
                    "low": float(k.low),
                    "close": float(k.close),
                    "volume": float(k.volume),
                    "volume_currency": float(k.volume_currency),
                }
                for k in klines
            ]

            # 创建回测引擎
            engine = self._create_engine(backtest)
            if hasattr(engine, "set_pair_klines") and hasattr(
                engine, "required_symbols"
            ):
                pair_klines = {backtest.symbol.upper(): kline_dicts}
                for pair_symbol in engine.required_symbols():
                    pair_symbol = pair_symbol.upper()
                    if pair_symbol in pair_klines:
                        continue
                    pair_rows = kline_service.query_klines(
                        symbol=pair_symbol,
                        interval=backtest.interval,
                        start_time=backtest.start_time,
                        end_time=backtest.end_time,
                    )
                    if not pair_rows:
                        raise ValueError(
                            f"没有 {pair_symbol} 的K线数据，请先获取历史数据"
                        )
                    pair_klines[pair_symbol] = [
                        {
                            "timestamp": k.timestamp,
                            "open": float(k.open),
                            "high": float(k.high),
                            "low": float(k.low),
                            "close": float(k.close),
                            "volume": float(k.volume),
                            "volume_currency": float(k.volume_currency),
                        }
                        for k in pair_rows
                    ]
                engine.set_pair_klines(pair_klines)

            # 进度回调
            def progress_callback(current, total):
                progress = int((current / total) * 100)
                backtest.progress = progress
                self.db.commit()
                logger.debug(f"回测进度: {progress}%")

            # 运行回测
            result = engine.run(kline_dicts, progress_callback)

            # 计算性能指标
            metrics = BacktestMetrics.calculate_all_metrics(
                initial_capital=float(backtest.initial_capital),
                final_capital=result["final_equity"],
                equity_curve=engine.equity_curve,
                trades=[self._trade_to_dict(t) for t in engine.trades],
                start_timestamp=backtest.start_time,
                end_timestamp=backtest.end_time,
            )

            # 保存回测结果
            backtest.status = "completed"
            backtest.progress = 100
            backtest.final_capital = result["final_equity"]
            backtest.total_return = metrics["total_return"]
            backtest.annualized_return = metrics["annualized_return"]
            backtest.max_drawdown = metrics["max_drawdown"]
            backtest.sharpe_ratio = metrics["sharpe_ratio"]
            backtest.total_trades = metrics["total_trades"]
            backtest.winning_trades = metrics["winning_trades"]
            backtest.losing_trades = metrics["losing_trades"]
            backtest.win_rate = metrics["win_rate"]
            backtest.profit_factor = metrics["profit_factor"]
            backtest.total_fee = metrics["total_fee"]
            backtest.equity_curve = engine.equity_curve
            backtest.completed_at = datetime.now()

            # 保存交易记录
            for trade in engine.trades:
                backtest_trade = BacktestTrade(
                    backtest_id=backtest.id,
                    timestamp=trade.timestamp,
                    side=trade.side,
                    price=trade.price,
                    amount=trade.amount,
                    fee=trade.fee,
                    position_before=trade.position_before,
                    position_after=trade.position_after,
                    capital_before=trade.capital_before,
                    capital_after=trade.capital_after,
                    pnl=trade.pnl,
                    pnl_percent=trade.pnl_percent,
                )
                self.db.add(backtest_trade)

            self.db.commit()

            logger.info(
                f"回测完成: ID={backtest_id}, "
                f"最终资金={result['final_equity']:.2f}, "
                f"收益率={metrics['total_return']*100:.2f}%"
            )

            return {
                "backtest_id": backtest.id,
                "status": "completed",
                "metrics": metrics,
                "final_equity": result["final_equity"],
            }

        except Exception as e:
            logger.error(f"回测执行失败: {e}")
            backtest.status = "failed"
            backtest.error_message = str(e)
            self.db.commit()
            raise

    def _create_engine(self, backtest: Backtest) -> BacktestEngine:
        """
        根据策略类型创建回测引擎

        Args:
            backtest: 回测记录

        Returns:
            回测引擎实例
        """
        params = backtest.parameters or {}
        strategy_type = backtest.strategy_type

        # 从注册表获取引擎类
        engine_class = BACKTEST_ENGINES.get(strategy_type)

        if engine_class is None:
            raise ValueError(
                f"不支持的策略类型: {strategy_type}，可用类型: {list(BACKTEST_ENGINES.keys())}"
            )

        # 检查引擎是否支持 from_params 方法
        if hasattr(engine_class, "from_params"):
            return engine_class.from_params(
                symbol=backtest.symbol,
                initial_capital=float(backtest.initial_capital),
                params=params,
            )

        raise ValueError(f"无法创建策略引擎: {strategy_type}")

    @staticmethod
    def _trade_to_dict(trade) -> Dict:
        """
        将Trade对象转换为字典

        Args:
            trade: Trade对象

        Returns:
            字典
        """
        return {
            "timestamp": trade.timestamp,
            "side": trade.side,
            "price": trade.price,
            "amount": trade.amount,
            "fee": trade.fee,
            "pnl": trade.pnl,
            "pnl_percent": trade.pnl_percent,
        }
