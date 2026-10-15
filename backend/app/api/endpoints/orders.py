"""
订单管理API
"""

from fastapi import APIRouter, HTTPException, Body, Query, Depends
from typing import Optional, List
from decimal import Decimal
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.services.exchange.okx import OKXExchange
from app.services.api_config_service import api_config_service
from app.core.database import get_db
from app.api.deps import require_current_user_id
from app.models.order import Order as OrderModel
from app.models.strategy import Strategy
from loguru import logger
from datetime import datetime
import asyncio

router = APIRouter()


def get_okx_exchange(user_id: int) -> OKXExchange:
    """获取OKX交易所实例 (优先使用数据库配置)"""
    try:
        return api_config_service.get_exchange(user_id=user_id)
    except Exception as e:
        logger.error(f"获取交易所实例失败: {e}")
        raise HTTPException(status_code=500, detail=f"API配置错误: {str(e)}")


class CreateOrderRequest(BaseModel):
    """下单请求"""

    symbol: str = Field(..., description="产品ID,如 BTC-USDT")
    side: str = Field(..., description="订单方向: buy/sell")
    order_type: str = Field(..., description="订单类型: market/limit/post_only/fok/ioc")
    amount: Decimal = Field(..., gt=0, description="委托数量")
    price: Optional[Decimal] = Field(None, description="委托价格(限价单必填)")
    td_mode: str = Field("cash", description="交易模式: cash/isolated/cross")
    cl_ord_id: Optional[str] = Field(None, description="客户自定义订单ID")
    pos_side: Optional[str] = Field(None, description="持仓方向: long/short/net")
    reduce_only: bool = Field(False, description="是否只减仓")
    tgt_ccy: Optional[str] = Field(
        None, description="市价单数量单位: base_ccy/quote_ccy"
    )


class CancelOrderRequest(BaseModel):
    """撤单请求"""

    symbol: str = Field(..., description="产品ID,如 BTC-USDT")
    order_id: Optional[str] = Field(None, description="订单ID")
    cl_ord_id: Optional[str] = Field(None, description="客户自定义订单ID")


class GetOrderRequest(BaseModel):
    """查询订单请求"""

    symbol: str = Field(..., description="产品ID,如 BTC-USDT")
    order_id: Optional[str] = Field(None, description="订单ID")
    cl_ord_id: Optional[str] = Field(None, description="客户自定义订单ID")


@router.post("/create")
async def create_order(
    request: CreateOrderRequest,
    user_id: int = Depends(require_current_user_id),
):
    """
    创建订单

    Args:
        request: 下单请求参数

    Returns:
        订单创建结果
    """
    exchange = None
    try:
        exchange = get_okx_exchange(user_id)
        result = await exchange.create_order(
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            amount=request.amount,
            price=request.price,
            td_mode=request.td_mode,
            cl_ord_id=request.cl_ord_id,
            pos_side=request.pos_side,
            reduce_only=request.reduce_only,
            tgt_ccy=request.tgt_ccy,
        )
        return {"code": 0, "msg": "success", "data": result}
    except ValueError as e:
        logger.error(f"下单参数错误: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"下单失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if exchange is not None:
            await exchange.close()


@router.post("/cancel")
async def cancel_order(
    request: CancelOrderRequest,
    user_id: int = Depends(require_current_user_id),
):
    """
    撤销订单

    Args:
        request: 撤单请求参数

    Returns:
        撤单结果
    """
    exchange = None
    try:
        exchange = get_okx_exchange(user_id)
        result = await exchange.cancel_order(
            symbol=request.symbol,
            order_id=request.order_id,
            cl_ord_id=request.cl_ord_id,
        )
        return {"code": 0, "msg": "success", "data": result}
    except ValueError as e:
        logger.error(f"撤单参数错误: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"撤单失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if exchange is not None:
            await exchange.close()


@router.post("/detail")
async def get_order(
    request: GetOrderRequest,
    user_id: int = Depends(require_current_user_id),
):
    """
    获取订单详情

    Args:
        request: 查询订单请求参数

    Returns:
        订单详细信息
    """
    exchange = None
    try:
        exchange = get_okx_exchange(user_id)
        result = await exchange.get_order(
            symbol=request.symbol,
            order_id=request.order_id,
            cl_ord_id=request.cl_ord_id,
        )
        return {"code": 0, "msg": "success", "data": result}
    except ValueError as e:
        logger.error(f"查询订单参数错误: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"查询订单失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if exchange is not None:
            await exchange.close()


@router.get("/list")
async def list_orders(
    symbol: Optional[str] = Query(None, description="产品ID,如 BTC-USDT"),
    status: Optional[str] = Query(
        None, description="订单状态: pending/filled/canceled"
    ),
    side: Optional[str] = Query(None, description="买卖方向: buy/sell"),
    strategy_id: Optional[int] = Query(None, description="策略ID"),
    limit: int = Query(100, description="返回数量,最大100"),
    db: Session = Depends(get_db),
    user_id: int = Depends(require_current_user_id),
):
    """
    获取订单列表

    优先从数据库查询(特别是策略订单),如果strategy_id为None则从OKX API获取

    Args:
        symbol: 产品ID筛选
        status: 状态筛选 (pending=未完成, filled=已成交, canceled=已撤销)
        side: 方向筛选
        strategy_id: 策略ID筛选
        limit: 返回数量
        db: 数据库session

    Returns:
        订单列表数组
    """
    try:
        result = []

        # 查询数据库订单（策略订单）
        # 如果指定了strategy_id，只查该策略；否则查所有策略订单
        query = (
            db.query(OrderModel, Strategy.name)
            .outerjoin(Strategy, OrderModel.strategy_id == Strategy.id)
            .filter(OrderModel.user_id == user_id)
        )

        # 如果指定了strategy_id，只查该策略
        if strategy_id is not None:
            logger.info(f"从数据库查询策略{strategy_id}的订单")
            query = query.filter(OrderModel.strategy_id == strategy_id)
        else:
            # 查询所有策略订单（strategy_id不为空的）
            logger.info("从数据库查询所有策略订单")
            query = query.filter(OrderModel.strategy_id.isnot(None))

        # 应用筛选条件
        if symbol:
            query = query.filter(OrderModel.symbol == symbol)
        if status:
            # 状态映射
            status_map = {
                "pending": ["pending", "submitted"],
                "partially_filled": ["partial_filled"],
                "filled": ["filled"],
                "canceled": ["canceled"],
                "failed": ["failed"],
            }
            db_statuses = status_map.get(status, [status])
            query = query.filter(OrderModel.status.in_(db_statuses))
        if side:
            query = query.filter(OrderModel.side == side)

        # 查询并转换数据库订单
        orders_with_strategy = (
            query.order_by(OrderModel.created_at.desc()).limit(limit).all()
        )

        for order, strategy_name in orders_with_strategy:
            # 状态映射: 数据库状态 -> 前端状态
            fe_status = (
                order.status.value
                if hasattr(order.status, "value")
                else str(order.status)
            )
            if fe_status in ["pending", "submitted"]:
                fe_status = "pending"
            elif fe_status == "partial_filled":
                fe_status = "partially_filled"

            result.append(
                {
                    "id": order.order_id or str(order.id),
                    "order_id": order.order_id or str(order.id),
                    "strategy_id": order.strategy_id,
                    "strategy_name": strategy_name,
                    "symbol": order.symbol,
                    "side": (
                        order.side.value
                        if hasattr(order.side, "value")
                        else str(order.side)
                    ),
                    "order_type": (
                        order.order_type.value
                        if hasattr(order.order_type, "value")
                        else str(order.order_type)
                    ),
                    "price": (
                        order.avg_price if order.avg_price else (order.price or 0)
                    ),  # 优先显示成交价
                    "size": order.amount,
                    "filled_size": order.filled_amount,
                    "avg_price": order.avg_price,  # 添加成交均价字段
                    "status": fe_status,
                    "created_at": (
                        order.created_at.isoformat() if order.created_at else ""
                    ),
                    "updated_at": (
                        (
                            order.filled_at or order.canceled_at or order.created_at
                        ).isoformat()
                        if (order.filled_at or order.canceled_at or order.created_at)
                        else ""
                    ),
                }
            )

        logger.info(f"从数据库获取到 {len(result)} 个策略订单")

        # 收集已有订单的order_id，用于去重
        existing_order_ids = set()
        for order in result:
            if order.get("order_id"):
                existing_order_ids.add(order["order_id"])

        # 如果没有指定strategy_id，还要查询OKX API（手动交易订单）
        if strategy_id is None:
            logger.info("同时从OKX API查询手动交易订单（SPOT + SWAP）")
            exchange = get_okx_exchange(user_id)
            all_orders = []

            try:
                # OKX instType 枚举：orders-history 接口 instType 为必填
                # 需要分别查询 SPOT 和 SWAP，再合并
                inst_types = ["SPOT", "SWAP"]

                if status == "pending" or status is None:
                    # orders-pending 的 instType 非必填，但传入可加速
                    pending_tasks = [
                        exchange.get_orders_pending(inst_type=it, inst_id=symbol)
                        for it in inst_types
                    ]
                    pending_results = await asyncio.gather(
                        *pending_tasks, return_exceptions=True
                    )
                    for r in pending_results:
                        if isinstance(r, list):
                            all_orders.extend(r)
                        else:
                            logger.warning(f"查询未完成订单部分失败: {r}")

                if status in ["filled", "canceled"] or status is None:
                    # 并发查 SPOT 和 SWAP 历史订单
                    history_tasks = [
                        exchange.get_orders_history(
                            inst_type=it, inst_id=symbol, state=status, limit=limit
                        )
                        for it in inst_types
                    ]
                    history_results = await asyncio.gather(
                        *history_tasks, return_exceptions=True
                    )
                    for r in history_results:
                        if isinstance(r, list):
                            all_orders.extend(r)
                        else:
                            logger.warning(f"查询历史订单部分失败: {r}")
            finally:
                await exchange.close()

            # 转换OKX订单为前端格式（跳过已经在数据库结果中的订单）
            for order in all_orders:
                okx_order_id = order.get("ordId", "")

                # 跳过已经在数据库结果中的订单（避免重复）
                if okx_order_id in existing_order_ids:
                    logger.debug(f"跳过重复订单: {okx_order_id} (已在数据库结果中)")
                    continue

                okx_state = order.get("state", "")
                if okx_state == "live":
                    fe_status = "pending"
                elif okx_state == "partially_filled":
                    fe_status = "partially_filled"
                elif okx_state == "filled":
                    fe_status = "filled"
                elif okx_state in ["canceled", "mmp_canceled"]:
                    fe_status = "canceled"
                else:
                    fe_status = "failed"

                if side and order.get("side") != side:
                    continue
                if status and fe_status != status:
                    continue

                created_at = datetime.fromtimestamp(
                    int(order.get("cTime", "0")) / 1000
                ).isoformat()
                updated_at = datetime.fromtimestamp(
                    int(order.get("uTime", "0")) / 1000
                ).isoformat()

                # avgPx 为实际成交均价；px 为委托价（市价单为空字符串）
                avg_px = order.get("avgPx", "")
                px = order.get("px", "")
                avg_price = float(avg_px) if avg_px else 0.0
                price = float(px) if px else avg_price  # 优先展示成交价

                result.append(
                    {
                        "id": okx_order_id,
                        "order_id": okx_order_id,
                        "strategy_id": None,
                        "strategy_name": None,
                        "symbol": order.get("instId", ""),
                        "side": order.get("side", ""),
                        "order_type": order.get("ordType", ""),
                        "price": price,
                        "avg_price": avg_price,
                        "size": float(order.get("sz", 0)),
                        "filled_size": float(order.get("accFillSz", 0)),
                        "status": fe_status,
                        "created_at": created_at,
                        "updated_at": updated_at,
                    }
                )

            logger.info(
                f"从OKX API获取到 {len(all_orders)} 个手动交易订单（SPOT+SWAP）"
            )

        logger.info(f"总共返回 {len(result)} 个订单（策略订单 + 手动交易订单）")
        return result

    except Exception as e:
        logger.error(f"获取订单列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{order_id}/cancel")
async def cancel_order_by_id(
    order_id: str,
    symbol: str = Body(..., embed=True),
    user_id: int = Depends(require_current_user_id),
):
    """
    通过订单ID撤销订单(用于前端按钮操作)

    Args:
        order_id: 订单ID(路径参数)
        symbol: 产品ID(请求体)

    Returns:
        撤单结果
    """
    exchange = None
    try:
        exchange = get_okx_exchange(user_id)
        result = await exchange.cancel_order(symbol=symbol, order_id=order_id)
        return {"code": 0, "msg": "success", "data": result}
    except ValueError as e:
        logger.error(f"撤单参数错误: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"撤单失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if exchange is not None:
            await exchange.close()
