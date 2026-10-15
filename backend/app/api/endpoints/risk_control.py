"""
风控管理API端点
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from loguru import logger

from app.core.database import get_db
from app.api.deps import require_current_user_id

from app.models import RiskControl, RiskAction, Strategy
from app.services.risk import RiskManager
from app.services.api_config_service import api_config_service
from app.services.strategy.manager import strategy_manager


router = APIRouter()


# ========== Pydantic 模型 ==========


class RiskControlCreate(BaseModel):
    """创建风控规则"""

    strategy_id: Optional[int] = Field(None, description="策略ID，None表示全局风控")
    level: str = Field("strategy", description="风控级别: global, strategy")
    risk_type: str = Field(
        ..., description="风控类型: capital, position, loss, drawdown, frequency"
    )
    name: str = Field(..., description="规则名称")
    description: Optional[str] = None
    is_enabled: bool = Field(True, description="是否启用")

    # 资金风控参数
    min_available_balance: Optional[float] = None
    max_position_value: Optional[float] = None
    max_order_amount: Optional[float] = None

    # 盈亏风控参数
    max_drawdown_percent: Optional[float] = None
    daily_loss_limit: Optional[float] = None
    total_loss_limit: Optional[float] = None
    max_consecutive_losses: Optional[int] = None

    # 持仓风控参数
    max_position_per_symbol: Optional[float] = None
    max_concentration_ratio: Optional[float] = None

    # 交易频率风控参数
    max_trades_per_period: Optional[int] = None
    period_seconds: Optional[int] = None

    # 风控动作
    action_on_trigger: str = Field(
        "warn", description="触发动作: warn, limit, pause, close"
    )
    warning_threshold: Optional[float] = Field(0.8, description="警告阈值")
    auto_resume: bool = Field(False, description="自动恢复")


class RiskControlUpdate(BaseModel):
    """更新风控规则"""

    is_enabled: Optional[bool] = None
    min_available_balance: Optional[float] = None
    max_position_value: Optional[float] = None
    max_order_amount: Optional[float] = None
    max_drawdown_percent: Optional[float] = None
    daily_loss_limit: Optional[float] = None
    total_loss_limit: Optional[float] = None
    max_consecutive_losses: Optional[int] = None
    max_position_per_symbol: Optional[float] = None
    max_concentration_ratio: Optional[float] = None
    max_trades_per_period: Optional[int] = None
    period_seconds: Optional[int] = None
    action_on_trigger: Optional[str] = None
    warning_threshold: Optional[float] = None
    auto_resume: Optional[bool] = None


class RiskControlResponse(BaseModel):
    """风控规则响应"""

    id: int
    user_id: int
    strategy_id: Optional[int]
    level: str
    risk_type: str
    name: str
    description: Optional[str]
    is_enabled: bool
    is_triggered: bool
    trigger_count: int
    action_on_trigger: str

    class Config:
        from_attributes = True


class EmergencyStopRequest(BaseModel):
    """紧急停止请求"""

    action: str = Field(
        ..., description="动作: pause_all(暂停所有), close_all(平仓所有)"
    )
    strategy_ids: Optional[List[int]] = Field(
        None, description="策略ID列表，None表示所有策略"
    )
    cancel_orders: bool = Field(True, description="是否撤销相关未成交订单")
    close_positions: bool = Field(
        False, description="是否市价平仓；action=close_all 时强制为 true"
    )


class EmergencyStopResponse(BaseModel):
    """紧急停止响应"""

    success: bool
    message: str
    affected_strategies: List[int]
    details: dict


# ========== API 端点 ==========


@router.post(
    "/rules", response_model=RiskControlResponse, status_code=status.HTTP_201_CREATED
)
async def create_risk_rule(
    rule_data: RiskControlCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_current_user_id),
):
    """
    创建风控规则

    - **strategy_id**: 策略ID，None表示全局风控
    - **risk_type**: capital(资金), position(持仓), loss(亏损), drawdown(回撤), frequency(频率)
    - **action_on_trigger**: warn(警告), limit(限制), pause(暂停), close(平仓)
    """
    try:
        # 创建风控规则
        risk_rule = RiskControl(user_id=user_id, **rule_data.model_dump())

        db.add(risk_rule)
        db.commit()
        db.refresh(risk_rule)

        logger.info(f"创建风控规则: {risk_rule.name} (ID: {risk_rule.id})")

        return risk_rule

    except Exception as e:
        db.rollback()
        logger.error(f"创建风控规则失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建风控规则失败: {str(e)}",
        )


@router.get("/rules", response_model=List[RiskControlResponse])
async def list_risk_rules(
    strategy_id: Optional[int] = None,
    level: Optional[str] = None,
    risk_type: Optional[str] = None,
    is_enabled: Optional[bool] = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_current_user_id),
):
    """
    查询风控规则列表

    - **strategy_id**: 按策略ID筛选
    - **level**: 按风控级别筛选 (global, strategy)
    - **risk_type**: 按风控类型筛选
    - **is_enabled**: 按启用状态筛选
    """
    try:
        query = db.query(RiskControl).filter(RiskControl.user_id == user_id)

        if strategy_id is not None:
            query = query.filter(RiskControl.strategy_id == strategy_id)
        if level:
            query = query.filter(RiskControl.level == level)
        if risk_type:
            query = query.filter(RiskControl.risk_type == risk_type)
        if is_enabled is not None:
            query = query.filter(RiskControl.is_enabled == is_enabled)

        rules = query.order_by(RiskControl.created_at.desc()).all()

        return rules

    except Exception as e:
        logger.error(f"查询风控规则失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询风控规则失败: {str(e)}",
        )


@router.get("/rules/{rule_id}", response_model=RiskControlResponse)
async def get_risk_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_current_user_id),
):
    """获取单个风控规则详情"""
    try:
        rule = (
            db.query(RiskControl)
            .filter(RiskControl.id == rule_id, RiskControl.user_id == user_id)
            .first()
        )

        if not rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="风控规则不存在"
            )

        return rule

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取风控规则失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取风控规则失败: {str(e)}",
        )


@router.put("/rules/{rule_id}", response_model=RiskControlResponse)
async def update_risk_rule(
    rule_id: int,
    rule_data: RiskControlUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_current_user_id),
):
    """更新风控规则"""
    try:
        rule = (
            db.query(RiskControl)
            .filter(RiskControl.id == rule_id, RiskControl.user_id == user_id)
            .first()
        )

        if not rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="风控规则不存在"
            )

        # 更新字段
        update_data = rule_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(rule, field, value)

        db.commit()
        db.refresh(rule)

        logger.info(f"更新风控规则: {rule.name} (ID: {rule.id})")

        return rule

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"更新风控规则失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新风控规则失败: {str(e)}",
        )


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_risk_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_current_user_id),
):
    """删除风控规则"""
    try:
        rule = (
            db.query(RiskControl)
            .filter(RiskControl.id == rule_id, RiskControl.user_id == user_id)
            .first()
        )

        if not rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="风控规则不存在"
            )

        db.delete(rule)
        db.commit()

        logger.info(f"删除风控规则: {rule.name} (ID: {rule.id})")

        return None

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"删除风控规则失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除风控规则失败: {str(e)}",
        )


@router.get("/check/{strategy_id}")
async def check_strategy_risk(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_current_user_id),
):
    """
    检查策略风控状态

    返回当前策略触发的所有风控规则
    """
    try:
        # 创建风控管理器
        risk_manager = RiskManager(db, user_id)

        # TODO: 集成交易所实例
        # risk_manager.set_exchange(exchange)

        # 检查风控
        triggered_rules = await risk_manager.check_all_risks(strategy_id)

        return {
            "strategy_id": strategy_id,
            "has_risk": len(triggered_rules) > 0,
            "triggered_count": len(triggered_rules),
            "triggered_rules": triggered_rules,
        }

    except Exception as e:
        logger.error(f"检查策略风控失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"检查策略风控失败: {str(e)}",
        )


@router.post("/emergency-stop", response_model=EmergencyStopResponse)
async def emergency_stop(
    request: EmergencyStopRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_current_user_id),
):
    """
    紧急停止

    - **pause_all**: 暂停所有策略（停止下单，但保留持仓）
    - **close_all**: 平仓所有策略（市价卖出所有持仓并暂停策略）
    """
    try:
        # 获取目标策略
        query = db.query(Strategy).filter(Strategy.user_id == user_id)

        if request.strategy_ids:
            query = query.filter(Strategy.id.in_(request.strategy_ids))
        else:
            # 所有运行中的策略
            query = query.filter(Strategy.status == "running")

        strategies = query.all()
        affected_ids = [s.id for s in strategies]

        if not strategies:
            return EmergencyStopResponse(
                success=True,
                message="没有需要停止的策略",
                affected_strategies=[],
                details={},
            )

        success_count = 0
        failed_count = 0
        details = {}

        if request.action == "pause_all":
            # 暂停所有策略，可选撤单，不平仓
            for strategy in strategies:
                try:
                    success = await strategy_manager.stop_strategy(
                        strategy.id,
                        cancel_orders=request.cancel_orders,
                        close_position=False,
                    )
                    strategy.status = "paused"
                    strategy.stopped_at = datetime.utcnow()
                    db.commit()
                    cancel_detail = {}
                    if request.cancel_orders:
                        cancel_detail = await cancel_exchange_orders_for_strategy(
                            strategy, user_id
                        )
                    if success:
                        success_count += 1
                        details[strategy.id] = {
                            "status": "已暂停",
                            "cancel": cancel_detail,
                        }
                    else:
                        success_count += 1
                        details[strategy.id] = {
                            "status": "策略未在内存运行，数据库已标记暂停",
                            "cancel": cancel_detail,
                        }
                except Exception as e:
                    failed_count += 1
                    details[strategy.id] = f"暂停失败: {str(e)}"

            message = f"紧急暂停完成: 成功 {success_count}, 失败 {failed_count}"

        elif request.action == "close_all":
            # 停止策略并尝试市价平仓
            for strategy in strategies:
                try:
                    success = await strategy_manager.stop_strategy(
                        strategy.id,
                        cancel_orders=request.cancel_orders,
                        close_position=True,
                    )
                    close_detail = await close_exchange_position_for_strategy(
                        strategy, user_id
                    )
                    strategy.status = "paused"
                    strategy.stopped_at = datetime.utcnow()
                    db.commit()
                    if success:
                        success_count += 1
                        details[strategy.id] = {
                            "status": "已暂停并尝试平仓",
                            "close": close_detail,
                        }
                    else:
                        success_count += 1
                        details[strategy.id] = {
                            "status": "策略未在内存运行，已尝试按交易所持仓平仓",
                            "close": close_detail,
                        }
                except Exception as e:
                    failed_count += 1
                    details[strategy.id] = f"处理失败: {str(e)}"

            message = f"紧急停止完成: 成功 {success_count}, 失败 {failed_count}"

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的操作: {request.action}",
            )

        logger.warning(f"紧急停止: {message}, 策略: {affected_ids}")

        return EmergencyStopResponse(
            success=failed_count == 0,
            message=message,
            affected_strategies=affected_ids,
            details=details,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"紧急停止失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"紧急停止失败: {str(e)}",
        )


async def close_exchange_position_for_strategy(
    strategy: Strategy, user_id: int
) -> dict:
    """按交易所真实持仓尝试平仓，作为急停兜底。"""
    exchange = api_config_service.get_exchange(
        user_id=user_id, config_id=strategy.api_config_id
    )
    closed = []
    canceled = []
    try:
        try:
            pending_orders = await exchange.get_orders_pending(
                inst_type="SWAP", inst_id=strategy.symbol
            )
            for order in pending_orders:
                try:
                    result = await exchange.cancel_order(
                        strategy.symbol, order_id=order.get("ordId")
                    )
                    canceled.append({"ord_id": order.get("ordId"), "result": result})
                except Exception as exc:
                    canceled.append({"ord_id": order.get("ordId"), "error": str(exc)})
        except Exception as exc:
            canceled.append({"error": f"查询/撤销未成交订单失败: {exc}"})

        positions = await exchange.get_positions(inst_id=strategy.symbol)
        for pos in positions:
            try:
                qty = float(pos.get("pos") or 0)
            except (TypeError, ValueError):
                qty = 0
            if qty == 0:
                continue

            pos_side = pos.get("posSide") or "net"
            logical_side = (
                pos_side
                if pos_side in ("long", "short")
                else ("long" if qty > 0 else "short")
            )
            order_side = "sell" if logical_side == "long" else "buy"
            result = await exchange.create_order(
                symbol=strategy.symbol,
                side=order_side,
                order_type="market",
                amount=Decimal(str(abs(qty))),
                td_mode=(strategy.parameters or {}).get("margin_mode", "isolated"),
                pos_side=pos_side if pos_side in ("long", "short") else "net",
                reduce_only=True,
            )
            closed.append(
                {
                    "pos_side": pos_side,
                    "size": qty,
                    "order_side": order_side,
                    "result": result,
                }
            )
    finally:
        await exchange.close()

    return {"canceled_orders": canceled, "closed_positions": closed}


async def cancel_exchange_orders_for_strategy(strategy: Strategy, user_id: int) -> dict:
    """撤销策略交易对的 OKX 未成交订单。"""
    exchange = api_config_service.get_exchange(
        user_id=user_id, config_id=strategy.api_config_id
    )
    canceled = []
    try:
        pending_orders = await exchange.get_orders_pending(
            inst_type="SWAP", inst_id=strategy.symbol
        )
        for order in pending_orders:
            try:
                result = await exchange.cancel_order(
                    strategy.symbol, order_id=order.get("ordId")
                )
                canceled.append({"ord_id": order.get("ordId"), "result": result})
            except Exception as exc:
                canceled.append({"ord_id": order.get("ordId"), "error": str(exc)})
    finally:
        await exchange.close()

    return {"canceled_orders": canceled}


@router.get("/actions", response_model=List[dict])
async def list_risk_actions(
    strategy_id: Optional[int] = None,
    action_type: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    user_id: int = Depends(require_current_user_id),
):
    """
    查询风控动作日志

    - **strategy_id**: 按策略筛选
    - **action_type**: 按动作类型筛选 (warn, limit, pause, close, resume)
    - **limit**: 返回数量限制
    """
    try:
        query = db.query(RiskAction).filter(RiskAction.user_id == user_id)

        if strategy_id:
            query = query.filter(RiskAction.strategy_id == strategy_id)
        if action_type:
            query = query.filter(RiskAction.action_type == action_type)

        actions = query.order_by(RiskAction.created_at.desc()).limit(limit).all()

        return [
            {
                "id": action.id,
                "strategy_id": action.strategy_id,
                "action_type": action.action_type,
                "trigger_reason": action.trigger_reason,
                "execution_status": action.execution_status,
                "created_at": (
                    action.created_at.isoformat() if action.created_at else None
                ),
            }
            for action in actions
        ]

    except Exception as e:
        logger.error(f"查询风控动作日志失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询风控动作日志失败: {str(e)}",
        )
