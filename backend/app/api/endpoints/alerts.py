"""
告警管理API端点
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from datetime import datetime

from app.core.database import get_db
from app.api.deps import require_current_user_id
from app.models.alert import Alert
from app.services.altcoin_momentum_monitor import altcoin_momentum_monitor
from app.services.tradfi_momentum_monitor import tradfi_momentum_monitor

router = APIRouter()


get_current_user_id = require_current_user_id


@router.get("/altcoin-momentum/status")
async def get_altcoin_momentum_status(
    user_id: int = Depends(get_current_user_id),
):
    """获取山寨币短线异动监控状态和最近命中。"""
    return {
        "code": 0,
        "msg": "success",
        "data": altcoin_momentum_monitor.status(),
    }


@router.get("/tradfi-momentum/status")
async def get_tradfi_momentum_status(
    user_id: int = Depends(get_current_user_id),
):
    """获取 TradFi 双向异动监控状态和最近命中。"""
    return {
        "code": 0,
        "msg": "success",
        "data": tradfi_momentum_monitor.status(),
    }


@router.get("/list")
async def get_alerts(
    skip: int = 0,
    limit: int = 50,
    strategy_id: Optional[int] = None,
    alert_type: Optional[str] = None,
    severity: Optional[str] = None,
    is_read: Optional[bool] = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取告警列表

    Args:
        skip: 跳过数量
        limit: 返回数量限制
        strategy_id: 按策略ID筛选
        alert_type: 按告警类型筛选 (stop_loss, take_profit, risk_warning, system_error)
        severity: 按严重级别筛选 (info, warning, error, success)
        is_read: 按已读状态筛选

    Returns:
        {
            "code": 0,
            "msg": "success",
            "data": {
                "total": 总数,
                "alerts": [告警列表]
            }
        }
    """
    try:
        # 构建查询
        query = db.query(Alert).filter(Alert.user_id == user_id)

        # 按条件筛选
        if strategy_id is not None:
            query = query.filter(Alert.strategy_id == strategy_id)
        if alert_type:
            query = query.filter(Alert.alert_type == alert_type)
        if severity:
            query = query.filter(Alert.severity == severity)
        if is_read is not None:
            query = query.filter(Alert.is_read == is_read)

        # 获取总数
        total = query.count()

        # 按创建时间倒序排列
        alerts = query.order_by(desc(Alert.created_at)).offset(skip).limit(limit).all()

        # 转换为字典列表
        alerts_list = []
        for alert in alerts:
            alerts_list.append(
                {
                    "id": alert.id,
                    "user_id": alert.user_id,
                    "strategy_id": alert.strategy_id,
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "title": alert.title,
                    "message": alert.message,
                    "data": alert.data,
                    "is_read": alert.is_read,
                    "is_handled": alert.is_handled,
                    "created_at": (
                        alert.created_at.isoformat() if alert.created_at else None
                    ),
                    "handled_at": (
                        alert.handled_at.isoformat() if alert.handled_at else None
                    ),
                }
            )

        return {
            "code": 0,
            "msg": "success",
            "data": {"total": total, "alerts": alerts_list},
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取告警列表失败: {str(e)}")


@router.get("/unread-count")
async def get_unread_count(
    db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)
):
    """
    获取未读告警数量

    Returns:
        {
            "code": 0,
            "msg": "success",
            "data": {
                "count": 未读数量
            }
        }
    """
    try:
        count = (
            db.query(Alert)
            .filter(Alert.user_id == user_id, Alert.is_read == False)
            .count()
        )

        return {"code": 0, "msg": "success", "data": {"count": count}}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取未读告警数量失败: {str(e)}")


@router.post("/{alert_id}/mark-read")
async def mark_alert_read(
    alert_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    标记告警为已读

    Args:
        alert_id: 告警ID

    Returns:
        {
            "code": 0,
            "msg": "success"
        }
    """
    try:
        alert = (
            db.query(Alert)
            .filter(Alert.id == alert_id, Alert.user_id == user_id)
            .first()
        )

        if not alert:
            raise HTTPException(status_code=404, detail="告警不存在")

        alert.is_read = True
        db.commit()

        return {"code": 0, "msg": "success"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"标记告警失败: {str(e)}")


@router.post("/mark-all-read")
async def mark_all_read(
    db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)
):
    """
    标记所有告警为已读

    Returns:
        {
            "code": 0,
            "msg": "success",
            "data": {
                "count": 标记数量
            }
        }
    """
    try:
        result = (
            db.query(Alert)
            .filter(Alert.user_id == user_id, Alert.is_read == False)
            .update({"is_read": True})
        )

        db.commit()

        return {"code": 0, "msg": "success", "data": {"count": result}}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"批量标记失败: {str(e)}")


@router.post("/{alert_id}/handle")
async def handle_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    标记告警为已处理

    Args:
        alert_id: 告警ID

    Returns:
        {
            "code": 0,
            "msg": "success"
        }
    """
    try:
        alert = (
            db.query(Alert)
            .filter(Alert.id == alert_id, Alert.user_id == user_id)
            .first()
        )

        if not alert:
            raise HTTPException(status_code=404, detail="告警不存在")

        alert.is_handled = True
        alert.handled_at = datetime.now()
        db.commit()

        return {"code": 0, "msg": "success"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"标记处理失败: {str(e)}")


@router.delete("/{alert_id}")
async def delete_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    删除告警

    Args:
        alert_id: 告警ID

    Returns:
        {
            "code": 0,
            "msg": "success"
        }
    """
    try:
        alert = (
            db.query(Alert)
            .filter(Alert.id == alert_id, Alert.user_id == user_id)
            .first()
        )

        if not alert:
            raise HTTPException(status_code=404, detail="告警不存在")

        db.delete(alert)
        db.commit()

        return {"code": 0, "msg": "success"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除告警失败: {str(e)}")
