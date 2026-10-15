"""
回测系统API端点
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from datetime import datetime

from app.core.database import get_db, SessionLocal
from app.core.config import settings
from app.api.deps import require_current_user_id
from loguru import logger
from app.services.exchange.okx import OKXExchange
from app.services.backtest import KlineService
from app.services.backtest.backtest_service import BacktestService
from app.services.backtest.top_gainers_momentum import TopGainersMomentumAnalyzer
from app.models import Backtest

router = APIRouter()


async def _run_backtest_bg(backtest_id: int):
    """后台回测任务 - 使用独立DB会话，避免请求会话在任务完成前关闭"""
    db = SessionLocal()
    try:
        service = BacktestService(db=db)
        await service.run_backtest(backtest_id)
    except Exception as e:
        logger.error(f"后台回测任务异常: backtest_id={backtest_id}, error={e}")
    finally:
        db.close()


# ==================== Pydantic 模型 ====================


class FetchKlineRequest(BaseModel):
    """获取K线数据请求"""

    symbol: str = Field(..., description="交易对，如 BTC-USDT")
    interval: str = Field(..., description="K线周期：1m/5m/15m/30m/1H/4H/1D")
    start_time: int = Field(..., description="开始时间戳(毫秒)")
    end_time: int = Field(..., description="结束时间戳(毫秒)")


class FetchKlineResponse(BaseModel):
    """获取K线数据响应"""

    total: int = Field(..., description="总条数")
    new: int = Field(..., description="新增条数")
    updated: int = Field(..., description="更新条数")
    skipped: int = Field(..., description="跳过条数")


class KlineData(BaseModel):
    """K线数据"""

    timestamp: int = Field(..., description="时间戳(毫秒)")
    open: float = Field(..., description="开盘价")
    high: float = Field(..., description="最高价")
    low: float = Field(..., description="最低价")
    close: float = Field(..., description="收盘价")
    volume: float = Field(..., description="成交量(币)")
    volume_currency: float = Field(..., description="成交额(USDT)")


class DataRangeResponse(BaseModel):
    """数据范围响应"""

    start_time: int = Field(..., description="最早时间戳(毫秒)")
    end_time: int = Field(..., description="最晚时间戳(毫秒)")
    count: int = Field(..., description="数据条数")
    start_time_str: str = Field(..., description="最早时间(可读)")
    end_time_str: str = Field(..., description="最晚时间(可读)")


# ==================== 辅助函数 ====================


def get_exchange() -> OKXExchange:
    """获取交易所实例"""
    return OKXExchange(
        api_key=settings.OKX_API_KEY,
        secret_key=settings.OKX_SECRET_KEY,
        passphrase=settings.OKX_PASSPHRASE,
        simulated=settings.OKX_SIMULATED,
        proxy=settings.OKX_PROXY,
    )


def get_kline_service(db: Session = Depends(get_db)) -> KlineService:
    """获取K线服务实例"""
    exchange = get_exchange()
    return KlineService(db=db, exchange=exchange)


# ==================== API端点 ====================


@router.post(
    "/klines/fetch", response_model=FetchKlineResponse, summary="获取历史K线数据"
)
async def fetch_klines(
    request: FetchKlineRequest, kline_service: KlineService = Depends(get_kline_service)
):
    """
    从OKX获取历史K线数据并保存到数据库

    **参数说明:**
    - **symbol**: 交易对，如 BTC-USDT
    - **interval**: K线周期，支持 1m/5m/15m/30m/1H/4H/1D
    - **start_time**: 开始时间戳(毫秒)
    - **end_time**: 结束时间戳(毫秒)

    **返回:**
    - **total**: 总共处理的K线条数
    - **new**: 新增的K线条数
    - **updated**: 更新的K线条数
    - **skipped**: 跳过的K线条数
    """
    try:
        result = await kline_service.fetch_and_save_klines(
            symbol=request.symbol,
            interval=request.interval,
            start_time=request.start_time,
            end_time=request.end_time,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取K线数据失败: {str(e)}")


@router.get("/klines/query", response_model=List[KlineData], summary="查询K线数据")
async def query_klines(
    symbol: str = Query(..., description="交易对"),
    interval: str = Query(..., description="K线周期"),
    start_time: int = Query(..., description="开始时间戳(毫秒)"),
    end_time: int = Query(..., description="结束时间戳(毫秒)"),
    limit: Optional[int] = Query(None, description="限制返回数量"),
    kline_service: KlineService = Depends(get_kline_service),
):
    """
    从数据库查询K线数据

    **参数:**
    - **symbol**: 交易对
    - **interval**: K线周期
    - **start_time**: 开始时间戳(毫秒)
    - **end_time**: 结束时间戳(毫秒)
    - **limit**: 限制返回数量(可选)

    **返回:** K线数据列表（按时间升序）
    """
    try:
        klines = kline_service.query_klines(
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

        return [
            KlineData(
                timestamp=k.timestamp,
                open=float(k.open),
                high=float(k.high),
                low=float(k.low),
                close=float(k.close),
                volume=float(k.volume),
                volume_currency=float(k.volume_currency),
            )
            for k in klines
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询K线数据失败: {str(e)}")


@router.get("/strategy-types", summary="获取可用策略类型")
async def get_strategy_types():
    """
    获取所有可用的回测策略类型

    **返回:** 策略类型列表，包含类型标识和名称
    """
    from app.services.backtest.backtest_service import get_available_strategy_types

    types = get_available_strategy_types()
    strategy_names = {
        "grid": "网格策略",
        "grid_mm": "网格做市",
        "ma_cross": "均线交叉",
        "dual_ma_cross": "双均线(多空)",
        "adaptive_grid_trend": "自适应趋势网格",
        "arbitrage": "现货-永续套利",
        "fixed_tp_sl": "固定止盈止损",
    }

    return [{"value": t, "label": strategy_names.get(t, t)} for t in types]


@router.get("/top-gainers-momentum/analyze", summary="分析涨幅榜前三多周期动量策略")
async def analyze_top_gainers_momentum(
    timeframe: str = Query("15m", description="K线周期：1m/5m/15m/30m/1H/4H"),
    top_n: int = Query(3, ge=1, le=10, description="涨幅榜取前N个"),
    initial_capital: float = Query(1000.0, gt=0, description="初始资金"),
    lookback_hours: int = Query(24, ge=1, le=72, description="快速回测窗口小时数"),
):
    """
    实时拉取 OKX USDT 永续涨幅榜，排除 BTC/ETH 后取前 N 个，
    使用所选 K 线周期的 EMA 动量策略做近 24 小时快速回测并返回当前信号。
    """
    analyzer = TopGainersMomentumAnalyzer()
    try:
        return await analyzer.analyze(
            timeframe=timeframe,
            top_n=top_n,
            initial_capital=initial_capital,
            lookback_hours=lookback_hours,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"涨幅榜动量分析失败: {str(e)}")
    finally:
        await analyzer.close()


@router.get("/symbols", summary="获取有K线数据的交易对")
async def get_available_symbols(
    kline_service: KlineService = Depends(get_kline_service),
):
    """
    获取数据库中有K线数据的交易对列表

    **返回:** 交易对列表
    """
    symbols = kline_service.get_symbols()
    return symbols


@router.get("/symbols/detail", summary="获取交易对详细信息")
async def get_symbols_detail(kline_service: KlineService = Depends(get_kline_service)):
    """
    获取所有有K线数据的交易对详细信息

    **返回:** 交易对列表，包含每个交易对各周期的数据量
    """
    details = kline_service.get_available_symbols()
    return details


@router.get("/klines/range", summary="获取数据范围")
async def get_data_range(
    symbol: str = Query(..., description="交易对"),
    interval: str = Query(..., description="K线周期"),
    kline_service: KlineService = Depends(get_kline_service),
):
    """
    获取数据库中K线数据的时间范围

    **参数:**
    - **symbol**: 交易对
    - **interval**: K线周期

    **返回:** 数据范围信息，如果没有数据返回null
    """
    try:
        range_info = kline_service.get_data_range(symbol=symbol, interval=interval)

        if not range_info:
            return None

        # 添加可读的时间字符串
        range_info["start_time_str"] = datetime.fromtimestamp(
            range_info["start_time"] / 1000
        ).strftime("%Y-%m-%d %H:%M:%S")
        range_info["end_time_str"] = datetime.fromtimestamp(
            range_info["end_time"] / 1000
        ).strftime("%Y-%m-%d %H:%M:%S")

        return range_info
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取数据范围失败: {str(e)}")


@router.get("/klines/validate", summary="验证数据范围")
async def validate_data_range(
    symbol: str = Query(..., description="交易对"),
    interval: str = Query(..., description="K线周期"),
    start_time: int = Query(..., description="开始时间戳(毫秒)"),
    end_time: int = Query(..., description="结束时间戳(毫秒)"),
    kline_service: KlineService = Depends(get_kline_service),
):
    """
    验证指定时间范围是否有足够的K线数据用于回测

    **参数:**
    - **symbol**: 交易对
    - **interval**: K线周期
    - **start_time**: 回测开始时间戳(毫秒)
    - **end_time**: 回测结束时间戳(毫秒)

    **返回:**
    - **has_data**: 是否有数据
    - **data_start**: 数据库中最早的数据时间
    - **data_end**: 数据库中最晚的数据时间
    - **requested_start**: 请求的开始时间
    - **requested_end**: 请求的结束时间
    - **is_sufficient**: 数据是否充足(覆盖整个请求范围)
    - **message**: 提示信息
    """
    try:
        # 获取数据范围
        range_info = kline_service.get_data_range(symbol=symbol, interval=interval)

        if not range_info:
            return {
                "has_data": False,
                "is_sufficient": False,
                "message": f"数据库中没有 {symbol} {interval} 的K线数据，请先获取历史数据",
            }

        data_start = range_info["start_time"]
        data_end = range_info["end_time"]

        # 检查数据范围是否覆盖请求范围
        is_sufficient = data_start <= start_time and data_end >= end_time

        # 格式化时间字符串
        data_start_str = datetime.fromtimestamp(data_start / 1000).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        data_end_str = datetime.fromtimestamp(data_end / 1000).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        requested_start_str = datetime.fromtimestamp(start_time / 1000).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        requested_end_str = datetime.fromtimestamp(end_time / 1000).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        if is_sufficient:
            message = f"数据充足，可以进行回测"
        else:
            missing_parts = []
            if data_start > start_time:
                missing_parts.append(
                    f"缺少 {requested_start_str} 至 {data_start_str} 的数据"
                )
            if data_end < end_time:
                missing_parts.append(
                    f"缺少 {data_end_str} 至 {requested_end_str} 的数据"
                )
            message = "数据不足: " + "; ".join(missing_parts)

        return {
            "has_data": True,
            "data_start": data_start,
            "data_end": data_end,
            "data_start_str": data_start_str,
            "data_end_str": data_end_str,
            "requested_start": start_time,
            "requested_end": end_time,
            "requested_start_str": requested_start_str,
            "requested_end_str": requested_end_str,
            "is_sufficient": is_sufficient,
            "message": message,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"验证数据范围失败: {str(e)}")


@router.delete("/klines/delete", summary="删除K线数据")
async def delete_klines(
    symbol: str = Query(..., description="交易对"),
    interval: str = Query(..., description="K线周期"),
    start_time: Optional[int] = Query(None, description="开始时间戳(毫秒)"),
    end_time: Optional[int] = Query(None, description="结束时间戳(毫秒)"),
    kline_service: KlineService = Depends(get_kline_service),
):
    """
    删除K线数据

    **参数:**
    - **symbol**: 交易对
    - **interval**: K线周期
    - **start_time**: 开始时间戳(可选，不指定则删除所有)
    - **end_time**: 结束时间戳(可选，不指定则删除所有)

    **返回:** 删除的记录数
    """
    try:
        count = kline_service.delete_klines(
            symbol=symbol, interval=interval, start_time=start_time, end_time=end_time
        )
        return {"deleted": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除K线数据失败: {str(e)}")


# ==================== 回测执行API ====================


class CreateBacktestRequest(BaseModel):
    """创建回测请求"""

    name: str = Field(..., description="回测名称")
    strategy_type: str = Field(..., description="策略类型：grid/grid_mm")
    symbol: str = Field(..., description="交易对")
    interval: str = Field(..., description="K线周期")
    start_time: int = Field(..., description="开始时间戳(毫秒)")
    end_time: int = Field(..., description="结束时间戳(毫秒)")
    initial_capital: float = Field(10000.0, description="初始资金")
    parameters: Dict[str, Any] = Field(..., description="策略参数")
    description: Optional[str] = Field(None, description="回测描述")


class BacktestResponse(BaseModel):
    """回测响应"""

    id: int
    name: str
    description: Optional[str] = None
    strategy_type: str
    symbol: str
    interval: str
    status: str
    progress: int
    created_at: datetime
    # 添加性能指标字段(可选,因为运行中的回测可能没有这些值)
    total_return: Optional[float] = None
    max_drawdown: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    total_trades: Optional[int] = None

    class Config:
        from_attributes = True


class BacktestResultResponse(BaseModel):
    """回测结果响应"""

    id: int
    name: str
    description: Optional[str] = None
    strategy_type: str
    symbol: str
    interval: str
    status: str
    start_time: int
    end_time: int
    initial_capital: float
    final_capital: Optional[float]
    total_return: Optional[float]
    annualized_return: Optional[float]
    max_drawdown: Optional[float]
    sharpe_ratio: Optional[float]
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Optional[float]
    profit_factor: Optional[float]
    total_fee: Optional[float]
    equity_curve: Optional[List[Dict[str, Any]]]
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


def get_backtest_service(db: Session = Depends(get_db)) -> BacktestService:
    """获取回测服务实例"""
    return BacktestService(db=db)


@router.post("/run", response_model=BacktestResponse, summary="创建并运行回测")
async def create_and_run_backtest(
    request: CreateBacktestRequest,
    background_tasks: BackgroundTasks,
    backtest_service: BacktestService = Depends(get_backtest_service),
    user_id: int = Depends(require_current_user_id),
):
    """
    创建并运行回测

    **参数:**
    - **name**: 回测名称
    - **strategy_type**: 策略类型 (grid: 网格策略, grid_mm: 网格做市)
    - **symbol**: 交易对
    - **interval**: K线周期
    - **start_time**: 回测开始时间
    - **end_time**: 回测结束时间
    - **initial_capital**: 初始资金
    - **parameters**: 策略参数
      - grid策略: {grid_lower, grid_upper, grid_num, amount_per_grid, fee_rate}
      - grid_mm策略: {grid_spread, grid_levels, amount_per_grid, fee_rate}

    **返回:** 回测记录
    """
    try:
        # 创建回测记录
        backtest = backtest_service.create_backtest(
            user_id=user_id,
            name=request.name,
            strategy_type=request.strategy_type,
            symbol=request.symbol,
            interval=request.interval,
            start_time=request.start_time,
            end_time=request.end_time,
            initial_capital=request.initial_capital,
            parameters=request.parameters,
            description=request.description,
        )

        # 在后台执行回测（使用独立会话，避免请求会话提前关闭）
        background_tasks.add_task(_run_backtest_bg, backtest.id)

        return backtest

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建回测失败: {str(e)}")


@router.get("/list", response_model=List[BacktestResponse], summary="获取回测列表")
async def list_backtests(
    skip: int = Query(0, description="跳过记录数"),
    limit: int = Query(100, description="返回记录数"),
    db: Session = Depends(get_db),
    user_id: int = Depends(require_current_user_id),
):
    """
    获取回测列表

    **参数:**
    - **skip**: 跳过记录数
    - **limit**: 返回记录数

    **返回:** 回测列表
    """
    backtests = (
        db.query(Backtest)
        .filter(Backtest.user_id == user_id)
        .order_by(Backtest.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return backtests


@router.get(
    "/{backtest_id}", response_model=BacktestResultResponse, summary="获取回测详情"
)
async def get_backtest(backtest_id: int, db: Session = Depends(get_db)):
    """
    获取回测详情

    **参数:**
    - **backtest_id**: 回测ID

    **返回:** 回测详细信息
    """
    backtest = db.query(Backtest).filter(Backtest.id == backtest_id).first()

    if not backtest:
        raise HTTPException(status_code=404, detail="回测记录不存在")

    return backtest


@router.get("/{backtest_id}/trades", summary="获取回测交易记录")
async def get_backtest_trades(backtest_id: int, db: Session = Depends(get_db)):
    """
    获取回测的交易记录

    **参数:**
    - **backtest_id**: 回测ID

    **返回:** 交易记录列表
    """
    from app.models import BacktestTrade

    backtest = db.query(Backtest).filter(Backtest.id == backtest_id).first()
    if not backtest:
        raise HTTPException(status_code=404, detail="回测记录不存在")

    trades = (
        db.query(BacktestTrade)
        .filter(BacktestTrade.backtest_id == backtest_id)
        .order_by(BacktestTrade.timestamp.asc())
        .all()
    )

    return [
        {
            "timestamp": t.timestamp,
            "side": t.side,
            "price": float(t.price),
            "amount": float(t.amount),
            "fee": float(t.fee),
            "pnl": float(t.pnl) if t.pnl else 0.0,
            "pnl_percent": float(t.pnl_percent) if t.pnl_percent else 0.0,
        }
        for t in trades
    ]


@router.get("/{backtest_id}/equity-curve", summary="获取资金曲线")
async def get_equity_curve(backtest_id: int, db: Session = Depends(get_db)):
    """
    获取回测的资金曲线

    **参数:**
    - **backtest_id**: 回测ID

    **返回:** 资金曲线数据
    """
    backtest = db.query(Backtest).filter(Backtest.id == backtest_id).first()

    if not backtest:
        raise HTTPException(status_code=404, detail="回测记录不存在")

    return backtest.equity_curve or []


@router.patch("/{backtest_id}/description", summary="更新回测描述")
async def update_backtest_description(
    backtest_id: int,
    description: str = Query(..., description="回测描述"),
    db: Session = Depends(get_db),
):
    """
    更新回测描述信息

    **参数:**
    - **backtest_id**: 回测ID
    - **description**: 新的描述内容

    **返回:** 更新后的回测信息
    """
    backtest = db.query(Backtest).filter(Backtest.id == backtest_id).first()

    if not backtest:
        raise HTTPException(status_code=404, detail="回测记录不存在")

    backtest.description = description
    backtest.updated_at = datetime.now()
    db.commit()
    db.refresh(backtest)

    return {"success": True, "id": backtest_id, "description": description}


@router.delete("/{backtest_id}", summary="删除回测记录")
async def delete_backtest(backtest_id: int, db: Session = Depends(get_db)):
    """
    删除回测记录

    **参数:**
    - **backtest_id**: 回测ID

    **返回:** 删除结果
    """
    backtest = db.query(Backtest).filter(Backtest.id == backtest_id).first()

    if not backtest:
        raise HTTPException(status_code=404, detail="回测记录不存在")

    db.delete(backtest)
    db.commit()

    return {"success": True, "deleted_id": backtest_id}
