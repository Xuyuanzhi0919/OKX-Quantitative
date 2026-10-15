"""
策略管理API
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.core.database import get_db
from app.api.deps import require_current_user_id, require_mobile_read_user_id
from app.models.strategy import Strategy, StrategyEvent, StrategyStatus
from app.models.order import Order, OrderStatus, OrderSide
from app.schemas.strategy import (
    StrategyCreate,
    StrategyUpdate,
    StrategyResponse,
    StrategyListResponse,
    StrategyStatsResponse,
)
from app.services.strategy.manager import strategy_manager
from app.services.strategy.adaptive_grid_trend_config import (
    normalize_adaptive_grid_trend_params,
    select_stable_1000u_symbols,
)
from app.services.exchange.okx import OKXExchange
from app.services.api_config_service import api_config_service
from app.core.config import settings
from typing import List
from datetime import datetime
from decimal import Decimal
from loguru import logger


router = APIRouter()


get_current_user_id = require_current_user_id


SUPPORTED_STRATEGY_TYPES = {
    "adaptive_grid_trend",
    "arbitrage",
    "top_gainers_momentum",
    "explosive_momentum_chaser",
}
ANALYSIS_ONLY_STRATEGY_TYPES = set()
SUPPORTED_STRATEGY_TYPE_LABEL = (
    "自适应趋势网格策略、现货-永续套利策略、涨幅榜前三15m动量策略和爆量急拉追涨策略"
)


def _summarize_close_events(events) -> dict:
    """Build restart-safe realized PnL statistics from persisted close events."""
    pnls = []
    completed_trade_pnls = []
    for event in events:
        data = (
            event[0]
            if isinstance(event, (tuple, list))
            else getattr(event, "data", event)
        )
        if not isinstance(data, dict) or data.get("pnl") is None:
            continue
        try:
            pnl = float(data["pnl"])
        except (TypeError, ValueError):
            continue
        pnls.append(pnl)
        event_type = getattr(event, "event_type", "close_position")
        if event_type == "close_position":
            completed_trade_pnls.append(pnl)

    total_trades = len(completed_trade_pnls)
    winning_trades = sum(1 for pnl in completed_trade_pnls if pnl > 0)
    return {
        "realized_pnl": sum(pnls),
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "win_rate": winning_trades / total_trades * 100 if total_trades else 0.0,
    }


def _get_persistent_strategy_pnl(db: Session, strategy_id: int) -> dict:
    events = (
        db.query(StrategyEvent)
        .filter(
            StrategyEvent.strategy_id == strategy_id,
            StrategyEvent.event_type.in_(["close_position", "partial_close"]),
        )
        .all()
    )
    return _summarize_close_events(events)


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


async def _get_exchange_position_status(strategy_id: int) -> dict | None:
    """Return exact OKX merged positions for symbols managed by this strategy."""
    strategy_instance = strategy_manager.get_strategy(strategy_id)
    if not strategy_instance or not hasattr(
        strategy_instance.exchange, "get_positions"
    ):
        return None

    tracked = getattr(strategy_instance, "positions", None)
    if not isinstance(tracked, dict):
        return None
    tracked_symbols = set(tracked.keys())
    if not tracked_symbols:
        return {
            "in_position": False,
            "dynamic": True,
            "positions": [],
            "open_positions": 0,
            "current_notional_usd": 0.0,
        }

    try:
        exchange_positions = await strategy_instance.exchange.get_positions(
            inst_type="SWAP"
        )
    except Exception as exc:
        logger.warning(
            f"策略 {strategy_id} 获取交易所真实持仓失败，回退内存状态: {exc}"
        )
        return None

    items = []
    for raw in exchange_positions:
        symbol = str(raw.get("instId") or "")
        raw_qty = _safe_float(raw.get("pos"))
        if symbol not in tracked_symbols or raw_qty == 0:
            continue
        pos_side = str(raw.get("posSide") or "net").lower()
        side = (
            pos_side
            if pos_side in {"long", "short"}
            else ("long" if raw_qty > 0 else "short")
        )
        qty = abs(raw_qty)
        entry = _safe_float(raw.get("avgPx"))
        current = _safe_float(raw.get("markPx") or raw.get("last"), entry)
        notional = abs(_safe_float(raw.get("notionalUsd")))
        unrealized = _safe_float(raw.get("upl"))
        unrealized_pct = _safe_float(raw.get("uplRatio")) * 100
        local = tracked.get(symbol)
        stop_px = _safe_float(getattr(local, "stop_px", 0))
        take_profit_px = _safe_float(getattr(local, "take_profit_px", 0))
        opened_ms = _safe_float(raw.get("cTime"))
        item = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry_price": entry,
            "current_price": current,
            "stop_px": stop_px,
            "take_profit_px": take_profit_px or None,
            "open_time": (
                opened_ms / 1000
                if opened_ms > 0
                else _safe_float(getattr(local, "open_time", 0))
            ),
            "leverage": _safe_float(
                raw.get("lever"),
                _safe_float(getattr(strategy_instance, "max_leverage", 0)),
            ),
            "notional_usd": notional,
            "unrealized_pnl": unrealized,
            "unrealized_pnl_pct": unrealized_pct,
        }
        if current > 0 and stop_px > 0:
            item["distance_to_stop_pct"] = (
                (current - stop_px) / current * 100
                if side == "long"
                else (stop_px - current) / current * 100
            )
        if current > 0 and take_profit_px > 0:
            item["distance_to_take_profit_pct"] = (
                (take_profit_px - current) / current * 100
                if side == "long"
                else (current - take_profit_px) / current * 100
            )
        items.append(item)

    return {
        "in_position": bool(items),
        "dynamic": True,
        "positions": items,
        "open_positions": len(items),
        "current_notional_usd": sum(item["notional_usd"] for item in items),
    }


async def _get_account_position_status(strategy: Strategy) -> dict | None:
    """Return every live OKX position, including positions opened manually."""
    strategy_instance = strategy_manager.get_strategy(strategy.id)
    exchange = getattr(strategy_instance, "exchange", None)
    tracked = getattr(strategy_instance, "positions", {}) if strategy_instance else {}
    tracked = tracked if isinstance(tracked, dict) else {}
    owns_exchange = False
    if not exchange or not hasattr(exchange, "get_positions"):
        try:
            exchange = api_config_service.get_exchange(
                user_id=strategy.user_id,
                config_id=strategy.api_config_id,
            )
            owns_exchange = True
        except Exception as exc:
            logger.warning(f"策略 {strategy.id} 创建持仓查询客户端失败: {exc}")
            return None

    try:
        exchange_positions = await exchange.get_positions(inst_type="SWAP")
    except Exception as exc:
        logger.warning(f"策略 {strategy.id} 获取账户全部持仓失败: {exc}")
        return None
    finally:
        if owns_exchange and hasattr(exchange, "close"):
            await exchange.close()

    items = []
    for raw in exchange_positions:
        raw_qty = _safe_float(raw.get("pos"))
        if raw_qty == 0:
            continue
        symbol = str(raw.get("instId") or "")
        pos_side = str(raw.get("posSide") or "net").lower()
        side = (
            pos_side
            if pos_side in {"long", "short"}
            else ("long" if raw_qty > 0 else "short")
        )
        entry = _safe_float(raw.get("avgPx"))
        current = _safe_float(raw.get("markPx") or raw.get("last"), entry)
        local = tracked.get(symbol)
        stop_px = _safe_float(getattr(local, "stop_px", 0))
        take_profit_px = _safe_float(getattr(local, "take_profit_px", 0))
        opened_ms = _safe_float(raw.get("cTime"))
        item = {
            "symbol": symbol,
            "side": side,
            "qty": abs(raw_qty),
            "entry_price": entry,
            "current_price": current,
            "stop_px": stop_px,
            "take_profit_px": take_profit_px or None,
            "open_time": opened_ms / 1000 if opened_ms > 0 else 0.0,
            "leverage": _safe_float(raw.get("lever")),
            "notional_usd": abs(_safe_float(raw.get("notionalUsd"))),
            "margin": _safe_float(raw.get("margin")),
            "initial_margin": _safe_float(raw.get("imr")),
            "maintenance_margin": _safe_float(raw.get("mmr")),
            "margin_ratio": _safe_float(raw.get("mgnRatio")),
            "liquidation_price": _safe_float(raw.get("liqPx")) or None,
            "unrealized_pnl": _safe_float(raw.get("upl")),
            "unrealized_pnl_pct": _safe_float(raw.get("uplRatio")) * 100,
            "source": "strategy" if symbol in tracked else "manual",
        }
        if current > 0 and stop_px > 0:
            item["distance_to_stop_pct"] = (
                (current - stop_px) / current * 100
                if side == "long"
                else (stop_px - current) / current * 100
            )
        if current > 0 and take_profit_px > 0:
            item["distance_to_take_profit_pct"] = (
                (take_profit_px - current) / current * 100
                if side == "long"
                else (current - take_profit_px) / current * 100
            )
        items.append(item)

    return {
        "in_position": bool(items),
        "dynamic": True,
        "positions": items,
        "open_positions": len(items),
        "current_notional_usd": sum(item["notional_usd"] for item in items),
    }


def _empty_account_summary() -> dict:
    return {
        "total_equity": 0.0,
        "available_balance": 0.0,
        "cash_balance": 0.0,
        "unrealized_pnl": 0.0,
        "initial_margin": 0.0,
        "position_notional_usd": 0.0,
    }


async def _get_account_summary(strategy: Strategy) -> dict:
    """Return a minimal account-equity snapshot for the read-only iOS client."""
    strategy_instance = strategy_manager.get_strategy(strategy.id)
    exchange = getattr(strategy_instance, "exchange", None)
    owns_exchange = False
    if not exchange or not hasattr(exchange, "get_balance"):
        try:
            exchange = api_config_service.get_exchange(
                user_id=strategy.user_id,
                config_id=strategy.api_config_id,
            )
            owns_exchange = True
        except Exception as exc:
            logger.warning(f"策略 {strategy.id} 创建账户查询客户端失败: {exc}")
            return _empty_account_summary()
    try:
        balance = await exchange.get_balance()
    except Exception as exc:
        logger.warning(f"策略 {strategy.id} 获取账户权益失败: {exc}")
        return _empty_account_summary()
    finally:
        if owns_exchange and hasattr(exchange, "close"):
            await exchange.close()

    details = balance.get("details", []) if isinstance(balance, dict) else []
    return {
        "total_equity": _safe_float(balance.get("totalEq")),
        "available_balance": sum(_safe_float(item.get("availBal")) for item in details),
        "cash_balance": sum(_safe_float(item.get("cashBal")) for item in details),
        "unrealized_pnl": sum(_safe_float(item.get("upl")) for item in details),
        "initial_margin": _safe_float(balance.get("imr")),
        "position_notional_usd": abs(_safe_float(balance.get("notionalUsd"))),
    }


async def _build_strategy_pnl(
    db: Session,
    strategy: Strategy,
    position_status: dict | None = None,
) -> dict:
    """Combine persisted realized PnL with only the current runtime exposure."""
    persisted = _get_persistent_strategy_pnl(db, strategy.id)
    runtime = {}
    strategy_instance = strategy_manager.get_strategy(strategy.id)
    if strategy_instance and hasattr(strategy_instance, "calculate_pnl"):
        runtime = await strategy_instance.calculate_pnl()

    if position_status is None:
        position_status = await _get_exchange_position_status(strategy.id)
    if position_status is not None:
        live_positions = position_status.get("positions", [])
        unrealized = sum(
            _safe_float(item.get("unrealized_pnl")) for item in live_positions
        )
        open_positions = len(live_positions)
    else:
        unrealized = float(runtime.get("unrealized_pnl", 0) or 0)
        open_positions = int(runtime.get("open_positions", 0) or 0)
    realized = float(persisted["realized_pnl"])
    total_trades = int(persisted["total_trades"])
    result = dict(runtime)
    result.update(
        {
            "total_pnl": realized + unrealized,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "total_trades": total_trades,
            "win_rate": float(persisted["win_rate"]),
            "open_positions": open_positions,
            "buy_count": int(runtime.get("buy_count", total_trades) or 0),
            "sell_count": int(runtime.get("sell_count", total_trades) or 0),
            "total_fee": float(runtime.get("total_fee", 0) or 0),
            "pnl_rate": float(runtime.get("pnl_rate", 0) or 0),
        }
    )
    return result


def _build_strategy_stats(
    strategy: Strategy,
    persisted: dict,
    position_status: dict | None = None,
) -> dict:
    runtime = strategy_manager.get_strategy_stats(strategy.id)
    stats = (
        dict(runtime)
        if runtime
        else {
            "strategy_id": strategy.id,
            "is_running": False,
        }
    )
    stats["realized_pnl"] = float(persisted["realized_pnl"])
    stats["total_trades"] = int(persisted["total_trades"])
    if position_status is not None:
        stats["position_status"] = position_status
    return stats


def _select_mobile_strategy(db: Session, user_id: int) -> Strategy | None:
    """Prefer a running momentum strategy, otherwise use the newest one."""
    strategies = (
        db.query(Strategy)
        .filter(
            Strategy.user_id == user_id,
            Strategy.type == "explosive_momentum_chaser",
        )
        .order_by(desc(Strategy.id))
        .all()
    )
    return next(
        (
            strategy
            for strategy in strategies
            if strategy.status == StrategyStatus.RUNNING
            or strategy.status == StrategyStatus.RUNNING.value
        ),
        strategies[0] if strategies else None,
    )


async def _build_mobile_snapshot(db: Session, strategy: Strategy) -> dict:
    persisted = _get_persistent_strategy_pnl(db, strategy.id)
    strategy_position_status = await _get_exchange_position_status(strategy.id)
    account_position_status = await _get_account_position_status(strategy)
    account = await _get_account_summary(strategy)
    if account_position_status is not None:
        live_positions = account_position_status.get("positions", [])
        live_notional = sum(
            _safe_float(item.get("notional_usd")) for item in live_positions
        )
        live_margin = sum(
            _safe_float(item.get("notional_usd"))
            / max(_safe_float(item.get("leverage"), 1.0), 1.0)
            for item in live_positions
        )
        if live_notional > 0:
            account["position_notional_usd"] = live_notional
        if live_margin > 0 and account["initial_margin"] <= 0:
            account["initial_margin"] = live_margin

    pnl = await _build_strategy_pnl(db, strategy, strategy_position_status)
    pnl["strategy_open_positions"] = int(pnl.get("open_positions", 0))
    if account_position_status is not None:
        pnl["open_positions"] = int(account_position_status.get("open_positions", 0))

    return {
        "strategy": {
            "id": strategy.id,
            "name": strategy.name,
            "status": (
                strategy.status.value
                if hasattr(strategy.status, "value")
                else str(strategy.status)
            ),
        },
        "account": account,
        "stats": _build_strategy_stats(strategy, persisted, account_position_status),
        "pnl": pnl,
    }


@router.get("/adaptive-grid-trend/recommendation")
async def get_adaptive_grid_trend_recommendation(
    user_id: int = Depends(get_current_user_id),
):
    """获取1000U稳健实盘配置和候选币推荐。"""
    exchange = OKXExchange(
        api_key=settings.OKX_API_KEY,
        secret_key=settings.OKX_SECRET_KEY,
        passphrase=settings.OKX_PASSPHRASE,
        simulated=settings.OKX_SIMULATED,
        proxy=settings.OKX_PROXY,
    )
    try:
        tickers = await exchange.get_tickers("SWAP")
        recommendation = select_stable_1000u_symbols(tickers=tickers, active_limit=3)
        recommendation["user_id"] = user_id
        return recommendation
    except Exception as exc:
        logger.warning(f"获取自适应趋势网格推荐失败，返回静态推荐: {exc}")
        recommendation = select_stable_1000u_symbols(active_limit=3)
        recommendation["user_id"] = user_id
        recommendation["warning"] = f"实时行情不可用，已返回静态推荐: {exc}"
        return recommendation
    finally:
        await exchange.close()


@router.get("/mobile/current-snapshot")
async def get_current_strategy_mobile_snapshot(
    db: Session = Depends(get_db),
    user_id: int = Depends(require_mobile_read_user_id),
):
    """Return the running or newest explosive strategy without a hard-coded id."""
    strategy = _select_mobile_strategy(db, user_id)
    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到爆量急拉策略",
        )
    return await _build_mobile_snapshot(db, strategy)


@router.get("/adaptive-grid-trend/recommendation")
async def get_adaptive_grid_trend_recommendation(
    user_id: int = Depends(get_current_user_id),
):
    """获取1000U稳健实盘配置和候选币推荐。"""
    exchange = OKXExchange(
        api_key=settings.OKX_API_KEY,
        secret_key=settings.OKX_SECRET_KEY,
        passphrase=settings.OKX_PASSPHRASE,
        simulated=settings.OKX_SIMULATED,
        proxy=settings.OKX_PROXY,
    )
    try:
        tickers = await exchange.get_tickers("SWAP")
        recommendation = select_stable_1000u_symbols(tickers=tickers, active_limit=3)
        recommendation["user_id"] = user_id
        return recommendation
    except Exception as exc:
        logger.warning(f"获取自适应趋势网格推荐失败，返回静态推荐: {exc}")
        recommendation = select_stable_1000u_symbols(active_limit=3)
        recommendation["user_id"] = user_id
        recommendation["warning"] = f"实时行情不可用，已返回静态推荐: {exc}"
        return recommendation
    finally:
        await exchange.close()


@router.get("/", response_model=StrategyListResponse)
async def list_strategies(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """获取策略列表"""
    try:
        # 查询策略总数
        total = db.query(Strategy).filter(Strategy.user_id == user_id).count()

        # 查询策略列表
        strategies = (
            db.query(Strategy)
            .filter(Strategy.user_id == user_id)
            .order_by(desc(Strategy.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

        # 为每个策略动态计算统计数据
        strategy_responses = []
        for strategy in strategies:
            try:
                pnl_data = await _build_strategy_pnl(db, strategy)
                total_profit = float(pnl_data["total_pnl"])
                total_trades = int(pnl_data["total_trades"])
                win_rate = float(pnl_data["win_rate"])
            except Exception as calc_error:
                logger.warning(f"计算策略{strategy.id}统计数据失败: {calc_error}")
                total_profit = float(strategy.total_profit or 0)
                total_trades = int(strategy.total_trades or 0)
                win_rate = float(strategy.win_rate or 0)

            # 创建响应对象并更新统计数据
            strategy_dict = {
                "id": strategy.id,
                "user_id": strategy.user_id,
                "api_config_id": strategy.api_config_id,
                "name": strategy.name,
                "type": strategy.type,
                "symbol": strategy.symbol,
                "timeframe": strategy.timeframe,
                "status": strategy.status,
                "parameters": strategy.parameters,
                "description": strategy.description,
                "total_profit": total_profit,
                "total_trades": total_trades,
                "win_rate": round(win_rate, 2),
                "created_at": strategy.created_at,
                "updated_at": strategy.updated_at,
                "started_at": strategy.started_at,
                "stopped_at": strategy.stopped_at,
            }

            strategy_responses.append(StrategyResponse(**strategy_dict))

        return StrategyListResponse(total=total, items=strategy_responses)

    except Exception as e:
        logger.error(f"获取策略列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取策略列表失败: {str(e)}",
        )


@router.post("/", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED)
async def create_strategy(
    strategy_data: StrategyCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """创建策略"""
    try:
        # 将strategy_data.type转换为字符串值（小写）
        if isinstance(strategy_data.type, str):
            strategy_type_value = strategy_data.type
        else:
            # 如果是枚举对象，获取其value属性
            strategy_type_value = (
                strategy_data.type.value
                if hasattr(strategy_data.type, "value")
                else str(strategy_data.type).split(".")[-1].lower()
            )

        logger.debug(f"策略类型转换: {strategy_data.type} -> {strategy_type_value}")

        if strategy_type_value not in SUPPORTED_STRATEGY_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"后端当前仅支持{SUPPORTED_STRATEGY_TYPE_LABEL}",
            )

        parameters = strategy_data.parameters or {}
        if strategy_type_value == "adaptive_grid_trend":
            parameters = normalize_adaptive_grid_trend_params(parameters)

        bound_api_config = None
        if strategy_data.api_config_id is not None:
            bound_api_config = api_config_service.get_config(
                user_id=user_id,
                config_id=strategy_data.api_config_id,
                db=db,
            )
            if not bound_api_config:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="绑定的API配置不存在",
                )
            if not bound_api_config.is_valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"绑定的API配置无效: {bound_api_config.error_message or '请先验证配置'}",
                )

        db_strategy = Strategy(
            user_id=user_id,
            api_config_id=strategy_data.api_config_id,
            name=strategy_data.name,
            type=strategy_type_value,
            symbol=strategy_data.symbol,
            timeframe=strategy_data.timeframe,
            parameters=parameters,
            description=strategy_data.description,
            status="stopped",  # 直接使用小写字符串
        )

        db.add(db_strategy)
        db.commit()
        db.refresh(db_strategy)

        logger.info(f"创建策略成功: ID={db_strategy.id}, 名称={db_strategy.name}")

        return StrategyResponse.model_validate(db_strategy)

    except HTTPException:
        # 重新抛出HTTPException（包括余额不足的错误）
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"创建策略失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建策略失败: {str(e)}",
        )


@router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """获取策略详情"""
    strategy = (
        db.query(Strategy)
        .filter(Strategy.id == strategy_id, Strategy.user_id == user_id)
        .first()
    )

    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"策略 {strategy_id} 不存在"
        )

    return StrategyResponse.model_validate(strategy)


@router.put("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: int,
    strategy_data: StrategyUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """更新策略"""
    try:
        # 查询策略
        strategy = (
            db.query(Strategy)
            .filter(Strategy.id == strategy_id, Strategy.user_id == user_id)
            .first()
        )

        if not strategy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"策略 {strategy_id} 不存在",
            )

        # 检查策略是否在运行
        if (
            strategy.status == StrategyStatus.RUNNING.value
            or strategy.status == "running"
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="策略正在运行，无法修改"
            )

        # 更新字段
        update_data = strategy_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(strategy, field, value)

        strategy.updated_at = datetime.now()

        db.commit()
        db.refresh(strategy)

        logger.info(f"更新策略成功: ID={strategy_id}")

        return StrategyResponse.model_validate(strategy)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"更新策略失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新策略失败: {str(e)}",
        )


@router.delete("/{strategy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """删除策略（会自动撤销所有未成交订单）"""
    from app.models.order import Order, OrderStatus as OS
    from app.services.api_config_service import api_config_service
    from datetime import datetime, timezone

    try:
        # 查询策略
        strategy = (
            db.query(Strategy)
            .filter(Strategy.id == strategy_id, Strategy.user_id == user_id)
            .first()
        )

        if not strategy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"策略 {strategy_id} 不存在",
            )

        # 若策略正在运行，先停止并平仓，再执行删除
        if (
            strategy.status == StrategyStatus.RUNNING.value
            or strategy.status == "running"
        ):
            logger.info(f"删除前自动停止并平仓策略 {strategy_id}")
            try:
                await strategy_manager.stop_strategy(
                    strategy_id, cancel_orders=True, close_position=True
                )
            except Exception as e:
                logger.warning(f"删除时停止策略 {strategy_id} 失败（继续删除）: {e}")

        # 删除前先撤销所有未成交订单（安全措施）
        pending_orders = (
            db.query(Order)
            .filter(
                Order.strategy_id == strategy_id,
                Order.status.in_([OS.PENDING, OS.SUBMITTED, OS.PARTIAL_FILLED]),
            )
            .all()
        )

        cancel_count = 0
        if pending_orders:
            logger.info(f"删除策略前撤销 {len(pending_orders)} 个未成交订单")

            # 获取策略绑定的交易所实例；旧策略未绑定时回退到当前激活配置
            exchange = api_config_service.get_exchange(
                user_id=user_id,
                config_id=strategy.api_config_id,
            )

            for order in pending_orders:
                try:
                    await exchange.cancel_order(
                        symbol=order.symbol, order_id=order.order_id
                    )
                    order.status = OS.CANCELED
                    order.canceled_at = datetime.now(timezone.utc)
                    cancel_count += 1
                    logger.info(f"✓ 撤销订单: {order.order_id}")
                except Exception as e:
                    logger.warning(f"撤销订单 {order.order_id} 失败: {e} (将继续删除)")

            await exchange.close()
            db.commit()

        # 删除策略
        db.delete(strategy)
        db.commit()

        logger.info(f"删除策略成功: ID={strategy_id}, 撤销订单: {cancel_count} 个")

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"删除策略失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除策略失败: {str(e)}",
        )


@router.post("/{strategy_id}/start", response_model=StrategyResponse)
async def start_strategy(
    strategy_id: int,
    force_start: bool = False,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """启动策略"""
    try:
        # 查询策略
        strategy = (
            db.query(Strategy)
            .filter(Strategy.id == strategy_id, Strategy.user_id == user_id)
            .first()
        )

        if not strategy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"策略 {strategy_id} 不存在",
            )

        # 检查策略状态
        if (
            strategy.status == StrategyStatus.RUNNING.value
            or strategy.status == "running"
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="策略已在运行中"
            )

        strategy_type_value = (
            strategy.type.value
            if hasattr(strategy.type, "value")
            else str(strategy.type)
        )
        if strategy_type_value not in SUPPORTED_STRATEGY_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"后端当前仅支持启动{SUPPORTED_STRATEGY_TYPE_LABEL}",
            )

        preflight = await build_strategy_start_preflight(strategy, user_id, db)
        if preflight["blockers"] or (preflight["warnings"] and not force_start):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "策略启动前检查未通过，请确认风险后重试",
                    "preflight": preflight,
                    "require_force_start": True,
                },
            )

        # 获取交易所实例（优先使用数据库配置，否则使用.env配置）
        try:
            exchange = api_config_service.get_exchange(
                user_id=user_id,
                config_id=strategy.api_config_id,
            )
            logger.info(f"策略使用数据库API配置启动")
        except Exception as e:
            logger.warning(f"获取数据库API配置失败，使用.env配置: {e}")
            exchange = strategy_manager.get_exchange(
                api_key=settings.OKX_API_KEY,
                secret_key=settings.OKX_SECRET_KEY,
                passphrase=settings.OKX_PASSPHRASE,
            )

        # 启动策略
        success = await strategy_manager.start_strategy(
            strategy_id=strategy.id,
            strategy_type=strategy.type,
            symbol=strategy.symbol,
            parameters=strategy.parameters or {},
            exchange=exchange,
            user_id=user_id,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="启动策略失败"
            )

        # 更新策略状态
        strategy.status = "running"  # 直接使用字符串
        strategy.started_at = datetime.now()
        db.commit()
        db.refresh(strategy)

        logger.info(f"启动策略成功: ID={strategy_id}")

        return StrategyResponse.model_validate(strategy)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"启动策略失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"启动策略失败: {str(e)}",
        )


@router.get("/{strategy_id}/start-preflight")
async def start_strategy_preflight(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """策略启动前安全检查。"""
    strategy = (
        db.query(Strategy)
        .filter(Strategy.id == strategy_id, Strategy.user_id == user_id)
        .first()
    )
    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"策略 {strategy_id} 不存在"
        )

    return {
        "code": 0,
        "msg": "success",
        "data": await build_strategy_start_preflight(strategy, user_id, db),
    }


async def build_strategy_start_preflight(
    strategy: Strategy, user_id: int, db: Session
) -> dict:
    """构建策略启动前安全检查报告。"""
    warnings = []
    blockers = []
    checks = {}

    strategy_type_value = (
        strategy.type.value if hasattr(strategy.type, "value") else str(strategy.type)
    )
    if strategy_type_value not in SUPPORTED_STRATEGY_TYPES:
        blockers.append(f"后端当前仅支持{SUPPORTED_STRATEGY_TYPE_LABEL}")
    if strategy_type_value in ANALYSIS_ONLY_STRATEGY_TYPES:
        blockers.append(
            "涨幅榜前三15m动量策略当前为分析/监控配置，暂未接入自动下单执行器"
        )

    api_config = api_config_service.get_config(
        user_id=user_id, config_id=strategy.api_config_id, db=db
    )
    if not api_config:
        blockers.append("未找到策略绑定的 API 配置")
    else:
        checks["api_config"] = {
            "id": api_config.id,
            "name": api_config.name,
            "is_simulated": api_config.is_simulated,
            "is_valid": api_config.is_valid,
        }
        if not api_config.is_valid:
            blockers.append(
                f"API 配置无效: {api_config.error_message or '请先验证配置'}"
            )
        if not api_config.is_simulated:
            warnings.append(f"当前策略绑定实盘 API: {api_config.name}")

    same_symbol_running = (
        db.query(Strategy)
        .filter(
            Strategy.user_id == user_id,
            Strategy.id != strategy.id,
            Strategy.symbol == strategy.symbol,
            Strategy.status == StrategyStatus.RUNNING,
        )
        .all()
    )
    if same_symbol_running:
        warnings.append(
            f"{strategy.symbol} 已有 {len(same_symbol_running)} 个运行中策略"
        )
    checks["same_symbol_running_strategy_ids"] = [s.id for s in same_symbol_running]

    params = strategy.parameters or {}
    is_dynamic_universe_strategy = strategy_type_value in {
        "top_gainers_momentum",
        "explosive_momentum_chaser",
    }
    checks["parameters"] = {
        "symbol": strategy.symbol,
        "timeframe": params.get("trend_timeframe")
        or params.get("timeframe")
        or strategy.timeframe,
        "leverage": params.get("leverage") or params.get("max_leverage"),
        "max_position_usd": params.get("max_position_usd"),
        "max_total_position_usd": params.get("max_total_position_usd"),
        "risk_per_trade": params.get("risk_per_trade"),
        "direction": params.get("direction"),
    }

    if api_config and api_config.is_valid:
        exchange = None
        try:
            exchange = api_config_service.get_exchange(
                user_id=user_id, config_id=strategy.api_config_id
            )

            balance = await exchange.get_balance()
            total_eq = float(balance.get("totalEq") or 0)
            max_position_usd = float(params.get("max_position_usd") or 0)
            leverage = float(params.get("leverage") or params.get("max_leverage") or 1)
            estimated_margin = (
                max_position_usd / leverage if leverage > 0 else max_position_usd
            )
            checks["account"] = {
                "total_equity": total_eq,
                "estimated_strategy_margin": round(estimated_margin, 4),
                "estimated_margin_pct": (
                    round(estimated_margin / total_eq * 100, 2)
                    if total_eq > 0
                    else None
                ),
            }
            if total_eq > 0 and estimated_margin / total_eq > 0.3:
                warnings.append(
                    f"本策略预计保证金约 {estimated_margin:.2f} USDT，占账户权益超过 30%"
                )

            if not is_dynamic_universe_strategy:
                positions = await exchange.get_positions(inst_id=strategy.symbol)
                active_positions = []
                for pos in positions:
                    try:
                        size = float(pos.get("pos") or 0)
                    except (TypeError, ValueError):
                        size = 0
                    if size != 0:
                        active_positions.append(
                            {
                                "inst_id": pos.get("instId"),
                                "pos_side": pos.get("posSide"),
                                "size": size,
                                "avg_price": pos.get("avgPx"),
                                "upl": pos.get("upl"),
                                "notional_usd": pos.get("notionalUsd"),
                                "leverage": pos.get("lever"),
                            }
                        )
                checks["existing_positions"] = active_positions
                if active_positions:
                    warnings.append(
                        f"检测到 {strategy.symbol} 已有交易所持仓，请确认是否让策略接管"
                    )
            else:
                checks["existing_positions"] = []
                warnings.append(
                    "动态币池策略会自动选择OKX USDT永续币种，启动后可能在山寨币上自动市价开平仓"
                )

            all_positions = await exchange.get_positions(inst_type="SWAP")
            active_all_positions = []
            total_position_notional = 0.0
            for pos in all_positions:
                try:
                    size = abs(float(pos.get("pos") or 0))
                except (TypeError, ValueError):
                    size = 0
                if size <= 0:
                    continue
                try:
                    notional = abs(float(pos.get("notionalUsd") or 0))
                except (TypeError, ValueError):
                    notional = 0.0
                total_position_notional += notional
                active_all_positions.append(
                    {
                        "inst_id": pos.get("instId"),
                        "pos_side": pos.get("posSide"),
                        "size": size,
                        "notional_usd": notional,
                        "upl": pos.get("upl"),
                    }
                )
            checks["account"]["active_swap_positions"] = active_all_positions
            checks["account"]["total_position_notional_usd"] = round(
                total_position_notional, 4
            )
            checks["account"]["total_position_notional_pct"] = (
                round(total_position_notional / total_eq * 100, 2)
                if total_eq > 0
                else None
            )
            if total_eq > 0 and total_position_notional / total_eq > 2:
                warnings.append(
                    f"当前合约持仓名义价值约 {total_position_notional:.2f} USDT，超过账户权益 2 倍"
                )
            if is_dynamic_universe_strategy and active_all_positions:
                alt_positions = [
                    pos
                    for pos in active_all_positions
                    if str(pos.get("inst_id") or "").endswith("-USDT-SWAP")
                    and str(pos.get("inst_id") or "")
                    not in {"BTC-USDT-SWAP", "ETH-USDT-SWAP"}
                ]
                if alt_positions:
                    warnings.append(
                        f"检测到 {len(alt_positions)} 个山寨币USDT永续已有持仓，"
                        "动态策略不会自动接管这些历史持仓，请确认风险"
                    )

            if not is_dynamic_universe_strategy:
                pending_orders = await exchange.get_orders_pending(
                    inst_type="SWAP", inst_id=strategy.symbol
                )
                checks["pending_orders"] = [
                    {
                        "ord_id": order.get("ordId"),
                        "side": order.get("side"),
                        "pos_side": order.get("posSide"),
                        "ord_type": order.get("ordType"),
                        "price": order.get("px"),
                        "size": order.get("sz"),
                        "state": order.get("state"),
                    }
                    for order in pending_orders
                ]
                if pending_orders:
                    warnings.append(
                        f"检测到 {len(pending_orders)} 个未成交订单，启动前建议确认或撤销"
                    )
            else:
                checks["pending_orders"] = []

        except Exception as exc:
            blockers.append(f"交易所检查失败: {exc}")
        finally:
            if exchange:
                await exchange.close()

    return {
        "ok": len(blockers) == 0 and len(warnings) == 0,
        "can_force_start": len(blockers) == 0,
        "warnings": warnings,
        "blockers": blockers,
        "checks": checks,
    }


@router.post("/{strategy_id}/stop", response_model=StrategyResponse)
async def stop_strategy(
    strategy_id: int,
    cancel_orders: bool = True,
    close_position: bool = True,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    停止策略

    Args:
        strategy_id: 策略ID
        cancel_orders: 是否撤销所有未成交订单，默认True
        close_position: 是否市价平掉当前持仓，默认True
    """
    try:
        # 查询策略
        strategy = (
            db.query(Strategy)
            .filter(Strategy.id == strategy_id, Strategy.user_id == user_id)
            .first()
        )

        if not strategy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"策略 {strategy_id} 不存在",
            )

        # 检查策略状态
        if (
            strategy.status != StrategyStatus.RUNNING.value
            and strategy.status != "running"
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="策略未在运行"
            )

        # 停止策略（传递 cancel_orders / close_position 参数）
        success = await strategy_manager.stop_strategy(
            strategy_id, cancel_orders=cancel_orders, close_position=close_position
        )

        if not success:
            # 监控循环异常退出时，管理器会清理内存实例，但数据库中的
            # running 状态可能尚未来得及同步。没有持仓状态时允许把这类
            # 残留记录收敛为 stopped，避免用户永远无法停止策略。
            if close_position and bool(
                getattr(strategy, "position_in_position", False)
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="策略运行实例已不存在，但数据库仍记录持仓；请先核对并平仓",
                )
            logger.warning(
                f"策略 {strategy_id} 运行实例不存在，按残留状态修正为 stopped"
            )
            strategy_manager.log_strategy_event(
                strategy_id=strategy_id,
                event_type="stop_reconcile",
                level="warning",
                title="策略停止状态修正",
                message="运行实例已退出，数据库状态已修正为停止",
                data={
                    "cancel_orders": cancel_orders,
                    "close_position": close_position,
                },
                parameter_snapshot=(
                    strategy.parameters
                    if isinstance(strategy.parameters, dict)
                    else None
                ),
                user_id=user_id,
            )

        # 更新策略状态
        strategy.status = "stopped"  # 直接使用字符串
        strategy.stopped_at = datetime.now()
        db.commit()
        db.refresh(strategy)

        logger.info(f"停止策略成功: ID={strategy_id}")

        return StrategyResponse.model_validate(strategy)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"停止策略失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"停止策略失败: {str(e)}",
        )


@router.get("/{strategy_id}/stats", response_model=StrategyStatsResponse)
async def get_strategy_stats(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """获取策略实时统计信息"""
    try:
        # 查询策略
        strategy = (
            db.query(Strategy)
            .filter(Strategy.id == strategy_id, Strategy.user_id == user_id)
            .first()
        )

        if not strategy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"策略 {strategy_id} 不存在",
            )

        persisted = _get_persistent_strategy_pnl(db, strategy_id)
        position_status = await _get_exchange_position_status(strategy_id)
        return StrategyStatsResponse(
            **_build_strategy_stats(strategy, persisted, position_status)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取策略统计失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取策略统计失败: {str(e)}",
        )


@router.get("/{strategy_id}/orders")
async def get_strategy_orders(
    strategy_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """获取策略的交易历史记录"""
    try:
        from app.models.order import Order

        # 验证策略存在且属于当前用户
        strategy = (
            db.query(Strategy)
            .filter(Strategy.id == strategy_id, Strategy.user_id == user_id)
            .first()
        )

        if not strategy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"策略 {strategy_id} 不存在",
            )

        # 查询订单总数
        total = db.query(Order).filter(Order.strategy_id == strategy_id).count()

        # 查询订单列表（按创建时间倒序）
        orders = (
            db.query(Order)
            .filter(Order.strategy_id == strategy_id)
            .order_by(desc(Order.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

        # 转换为字典格式
        order_list = []
        for order in orders:
            order_list.append(
                {
                    "id": order.id,
                    "order_id": order.order_id,
                    "symbol": order.symbol,
                    "side": (
                        order.side.value if hasattr(order.side, "value") else order.side
                    ),
                    "order_type": (
                        order.order_type.value
                        if hasattr(order.order_type, "value")
                        else order.order_type
                    ),
                    "status": (
                        order.status.value
                        if hasattr(order.status, "value")
                        else order.status
                    ),
                    "price": order.price,
                    "amount": order.amount,
                    "filled_amount": order.filled_amount,
                    "avg_price": order.avg_price,
                    "fee": order.fee,
                    "fee_currency": order.fee_currency,
                    "created_at": (
                        order.created_at.isoformat() if order.created_at else None
                    ),
                    "submitted_at": (
                        order.submitted_at.isoformat() if order.submitted_at else None
                    ),
                    "filled_at": (
                        order.filled_at.isoformat() if order.filled_at else None
                    ),
                    "canceled_at": (
                        order.canceled_at.isoformat() if order.canceled_at else None
                    ),
                    "note": order.note,
                }
            )

        return {
            "code": 0,
            "msg": "success",
            "data": {"total": total, "items": order_list},
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取策略交易历史失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取策略交易历史失败: {str(e)}",
        )


@router.get("/{strategy_id}/events")
async def get_strategy_events(
    strategy_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """获取策略运行事件时间线"""
    strategy = (
        db.query(Strategy)
        .filter(Strategy.id == strategy_id, Strategy.user_id == user_id)
        .first()
    )
    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"策略 {strategy_id} 不存在"
        )

    total = (
        db.query(StrategyEvent).filter(StrategyEvent.strategy_id == strategy_id).count()
    )
    events = (
        db.query(StrategyEvent)
        .filter(StrategyEvent.strategy_id == strategy_id)
        .order_by(desc(StrategyEvent.created_at))
        .offset(skip)
        .limit(min(limit, 300))
        .all()
    )

    return {
        "code": 0,
        "msg": "success",
        "data": {
            "total": total,
            "items": [
                {
                    "id": event.id,
                    "strategy_id": event.strategy_id,
                    "event_type": event.event_type,
                    "level": event.level,
                    "title": event.title,
                    "message": event.message,
                    "data": event.data or {},
                    "parameter_snapshot": event.parameter_snapshot or {},
                    "created_at": (
                        event.created_at.isoformat() if event.created_at else None
                    ),
                }
                for event in events
            ],
        },
    }


@router.get("/{strategy_id}/performance")
async def get_strategy_performance(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """获取策略性能统计(优化版:使用策略实例的calculate_pnl)"""
    from app.models.order import Order, OrderStatus, OrderSide
    from sqlalchemy import func, case
    from decimal import Decimal

    # 验证策略所有权
    strategy = (
        db.query(Strategy)
        .filter(Strategy.id == strategy_id, Strategy.user_id == user_id)
        .first()
    )

    if not strategy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="策略不存在")

    # 优先使用策略实例的calculate_pnl获取准确数据
    try:
        strategy_instance = strategy_manager.get_strategy(strategy_id)
        if strategy_instance and hasattr(strategy_instance, "calculate_pnl"):
            pnl_data = await strategy_instance.calculate_pnl()

            # 使用策略实例的盈亏数据
            total_profit = pnl_data.get("total_pnl", 0.0)
            realized_profit = pnl_data.get("realized_pnl", 0.0)
            unrealized_profit = pnl_data.get("unrealized_pnl", 0.0)
            total_fee = pnl_data.get("total_fee", 0.0)
            buy_count = pnl_data.get("buy_count", 0)
            sell_count = pnl_data.get("sell_count", 0)
            in_position = bool(pnl_data.get("in_position", False))
            position_side = pnl_data.get("position_side", "")

            # 计算总交易次数和收益率
            total_trades = int(pnl_data.get("total_trades", buy_count + sell_count))
            total_orders = int(pnl_data.get("total_orders", buy_count + sell_count))
            if strategy.parameters:
                base_amount = Decimal(
                    str(
                        strategy.parameters.get("initial_amount")
                        or strategy.parameters.get("risk_base_usd")
                        or strategy.parameters.get("max_position_usd")
                        or 0
                    )
                )
                total_profit_rate = (
                    (Decimal(str(total_profit)) / base_amount * 100)
                    if base_amount > 0
                    else Decimal("0")
                )
            else:
                total_profit_rate = Decimal("0")

            # 简化胜率计算
            win_rate = float(
                pnl_data.get(
                    "win_rate",
                    100.0 if realized_profit > 0 else 0.0 if total_trades > 0 else 0.0,
                )
            )

            logger.info(
                f"使用策略实例计算性能: total_pnl={total_profit}, realized={realized_profit}, unrealized={unrealized_profit}"
            )

            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "strategy_id": strategy_id,
                    "total_profit": float(total_profit),
                    "total_profit_rate": float(total_profit_rate),
                    "realized_profit": float(realized_profit),
                    "unrealized_profit": float(unrealized_profit),
                    "total_trades": total_trades,
                    "total_orders": total_orders,
                    "in_position": in_position,
                    "position_side": position_side,
                    "successful_trades": buy_count if realized_profit > 0 else 0,
                    "failed_trades": 0,
                    "win_rate": win_rate,
                    "total_fee": float(total_fee),
                    "max_drawdown": 0,
                    "profit_history": [],
                    "daily_profits": [],
                },
            }
    except Exception as e:
        logger.warning(f"使用策略实例计算失败,回退到订单计算: {e}")

    # 回退方案:从订单计算(保留原有逻辑)

    # 获取所有已成交订单
    filled_orders = (
        db.query(Order)
        .filter(
            Order.strategy_id == strategy_id, Order.status == OrderStatus.FILLED.value
        )
        .order_by(Order.filled_at)
        .all()
    )

    if not filled_orders:
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "strategy_id": strategy_id,
                "total_profit": 0,
                "total_profit_rate": 0,
                "realized_profit": 0,
                "unrealized_profit": 0,
                "total_trades": 0,
                "successful_trades": 0,
                "failed_trades": 0,
                "win_rate": 0,
                "total_fee": 0,
                "max_drawdown": 0,
                "profit_history": [],
                "daily_profits": [],
            },
        }

    # 计算已实现盈亏 (配对买卖单)
    buy_orders = [o for o in filled_orders if o.side == OrderSide.BUY.value]
    sell_orders = [o for o in filled_orders if o.side == OrderSide.SELL.value]

    realized_profit = Decimal("0")
    successful_trades = 0
    failed_trades = 0
    total_fee = Decimal("0")

    # 简单配对: 按时间顺序配对买卖单
    paired_count = min(len(buy_orders), len(sell_orders))
    for i in range(paired_count):
        buy_order = buy_orders[i]
        sell_order = sell_orders[i]

        buy_cost = Decimal(str(buy_order.avg_price or buy_order.price)) * Decimal(
            str(buy_order.filled_amount)
        )
        sell_income = Decimal(str(sell_order.avg_price or sell_order.price)) * Decimal(
            str(sell_order.filled_amount)
        )

        profit = sell_income - buy_cost
        realized_profit += profit

        total_fee += Decimal(str(buy_order.fee or 0)) + Decimal(
            str(sell_order.fee or 0)
        )

        if profit > 0:
            successful_trades += 1
        else:
            failed_trades += 1

    # 计算未实现盈亏 (未配对的订单)
    unrealized_profit = Decimal("0")
    unpaired_buy = len(buy_orders) - paired_count
    unpaired_sell = len(sell_orders) - paired_count

    # 获取当前价格估算未实现盈亏
    try:
        from app.api.endpoints.market import get_public_okx_exchange

        exchange = get_public_okx_exchange()
        ticker = await exchange.get_ticker(strategy.symbol)
        current_price = Decimal(str(ticker.get("last", 0)))
        await exchange.close()

        # 多余的买单(持仓),用当前价格估值
        for i in range(paired_count, len(buy_orders)):
            buy_order = buy_orders[i]
            buy_cost = Decimal(str(buy_order.avg_price or buy_order.price)) * Decimal(
                str(buy_order.filled_amount)
            )
            current_value = current_price * Decimal(str(buy_order.filled_amount))
            unrealized_profit += current_value - buy_cost
    except Exception as e:
        logger.warning(f"获取当前价格失败,未实现盈亏设为0: {e}")

    # 总盈亏
    total_profit = realized_profit + unrealized_profit - total_fee

    # 计算收益率 (基于策略投资金额)
    if strategy.parameters and "total_amount" in strategy.parameters:
        total_amount = Decimal(str(strategy.parameters["total_amount"]))
        total_profit_rate = (
            (total_profit / total_amount * 100) if total_amount > 0 else Decimal("0")
        )
    else:
        total_profit_rate = Decimal("0")

    # 胜率
    total_completed = successful_trades + failed_trades
    win_rate = (successful_trades / total_completed * 100) if total_completed > 0 else 0

    # 盈亏历史 (累计盈亏曲线)
    profit_history = []
    cumulative_profit = Decimal("0")

    for i in range(paired_count):
        buy_order = buy_orders[i]
        sell_order = sell_orders[i]

        buy_cost = Decimal(str(buy_order.avg_price or buy_order.price)) * Decimal(
            str(buy_order.filled_amount)
        )
        sell_income = Decimal(str(sell_order.avg_price or sell_order.price)) * Decimal(
            str(sell_order.filled_amount)
        )
        profit = sell_income - buy_cost

        cumulative_profit += profit

        profit_history.append(
            {
                "timestamp": (
                    sell_order.filled_at.isoformat() if sell_order.filled_at else None
                ),
                "profit": float(profit),
                "cumulative_profit": float(cumulative_profit),
            }
        )

    # 按日统计盈亏
    daily_profits = {}
    for record in profit_history:
        if record["timestamp"]:
            date = record["timestamp"][:10]  # YYYY-MM-DD
            if date not in daily_profits:
                daily_profits[date] = 0
            daily_profits[date] += record["profit"]

    daily_profits_list = [
        {"date": date, "profit": profit}
        for date, profit in sorted(daily_profits.items())
    ]

    # 计算最大回撤
    max_drawdown = Decimal("0")
    peak = Decimal("0")
    for record in profit_history:
        current = Decimal(str(record["cumulative_profit"]))
        if current > peak:
            peak = current
        drawdown = peak - current
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    return {
        "code": 0,
        "msg": "success",
        "data": {
            "strategy_id": strategy_id,
            "total_profit": float(total_profit),
            "total_profit_rate": float(total_profit_rate),
            "realized_profit": float(realized_profit),
            "unrealized_profit": float(unrealized_profit),
            "total_trades": len(filled_orders),
            "successful_trades": successful_trades,
            "failed_trades": failed_trades,
            "win_rate": round(win_rate, 2),
            "total_fee": float(total_fee),
            "max_drawdown": float(max_drawdown),
            "profit_history": profit_history,
            "daily_profits": daily_profits_list,
        },
    }


@router.get("/{strategy_id}/pnl")
async def get_strategy_pnl(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取策略的实时盈亏统计

    Returns:
        {
            "total_pnl": 总盈亏 (USDT),
            "realized_pnl": 已实现盈亏,
            "unrealized_pnl": 未实现盈亏,
            "total_fee": 总手续费,
            "pnl_rate": 收益率 (%),
            "buy_count": 买入成交次数,
            "sell_count": 卖出成交次数,
            ...
        }
    """
    try:
        # 检查策略是否存在且属于当前用户
        strategy = (
            db.query(Strategy)
            .filter(Strategy.id == strategy_id, Strategy.user_id == user_id)
            .first()
        )

        if not strategy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="策略不存在"
            )

        return await _build_strategy_pnl(db, strategy)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取策略盈亏失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取盈亏数据失败: {str(e)}",
        )


@router.get("/{strategy_id}/mobile-snapshot")
async def get_strategy_mobile_snapshot(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_mobile_read_user_id),
):
    """Return an atomic, scoped read-only snapshot for the iOS app."""
    strategy = (
        db.query(Strategy)
        .filter(
            Strategy.id == strategy_id,
            Strategy.user_id == user_id,
        )
        .first()
    )
    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="策略不存在",
        )
    return await _build_mobile_snapshot(db, strategy)


@router.post("/{strategy_id}/backtest")
async def backtest_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """回测策略"""
    # TODO: 实现回测逻辑
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="回测功能尚未实现"
    )
