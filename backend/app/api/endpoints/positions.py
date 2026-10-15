"""
持仓和账户管理API
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime, timedelta, timezone
from app.services.exchange.okx import OKXExchange
from app.services.api_config_service import api_config_service
from app.api.deps import require_current_user_id
from loguru import logger

router = APIRouter()


def get_okx_exchange(user_id: int) -> OKXExchange:
    """获取OKX交易所实例 (优先使用数据库配置)"""
    try:
        return api_config_service.get_exchange(user_id=user_id)
    except Exception as e:
        logger.error(f"获取交易所实例失败: {e}")
        raise HTTPException(status_code=500, detail=f"API配置错误: {str(e)}")


@router.get("/balance")
async def get_balance(
    ccy: Optional[str] = Query(None, description="币种,如 BTC,ETH。支持多个,逗号分隔"),
    user_id: int = Depends(require_current_user_id),
):
    """
    获取账户余额

    Args:
        ccy: 币种,支持多个币种查询(不超过20个),逗号分隔。不传则返回所有资产

    Returns:
        账户余额信息
    """
    try:
        exchange = get_okx_exchange(user_id)
        balance = await exchange.get_balance(ccy=ccy)
        await exchange.close()

        return {"code": 0, "msg": "success", "data": balance}
    except Exception as e:
        logger.error(f"获取余额失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_positions(
    inst_type: Optional[str] = Query(
        None, description="产品类型: MARGIN/SWAP/FUTURES/OPTION"
    ),
    inst_id: Optional[str] = Query(None, description="产品ID,如 BTC-USDT-SWAP"),
    pos_id: Optional[str] = Query(None, description="持仓ID"),
    user_id: int = Depends(require_current_user_id),
):
    """
    获取持仓列表

    Args:
        inst_type: 产品类型
        inst_id: 产品ID,支持多个(不超过10个),逗号分隔
        pos_id: 持仓ID,支持多个(不超过20个),逗号分隔

    Returns:
        持仓列表
    """
    try:
        exchange = get_okx_exchange(user_id)
        positions = await exchange.get_positions(
            inst_type=inst_type, inst_id=inst_id, pos_id=pos_id
        )
        await exchange.close()

        # 安全转换函数
        def safe_float(value, default=0.0):
            """安全地转换为float,处理空字符串和None"""
            if value is None or value == "" or value == "":
                return default
            try:
                return float(value)
            except (ValueError, TypeError):
                return default

        # 转换为前端需要的格式(直接返回数组)
        result = []
        for idx, pos in enumerate(positions):
            pos_size = safe_float(pos.get("pos", 0))
            if pos_size == 0:
                continue  # 跳过空持仓

            avg_px = safe_float(pos.get("avgPx", 0))
            mark_px = safe_float(pos.get("markPx", avg_px))
            last_px = safe_float(pos.get("last", mark_px))
            upl = safe_float(pos.get("upl", 0))
            upl_ratio = safe_float(pos.get("uplRatio", 0))
            margin = safe_float(pos.get("margin", 0))
            imr = safe_float(pos.get("imr", 0))
            mmr = safe_float(pos.get("mmr", 0))
            mgn_ratio = safe_float(pos.get("mgnRatio", 0))
            liq_px = safe_float(pos.get("liqPx", 0))
            lever = safe_float(pos.get("lever", 0))
            pos_side = pos.get("posSide") or "net"
            side = (
                pos_side
                if pos_side in ("long", "short")
                else ("long" if pos_size > 0 else "short")
            )
            # notionalUsd: OKX 已按合约面值算好的名义价值（USD），SWAP 张数≠币数，
            # 前端必须用此值，否则直接 size×price 会差一个合约面值倍数
            notional_usd = safe_float(pos.get("notionalUsd", 0))

            # OKX uTime/cTime 是毫秒级 Unix 时间戳字符串，需转为 ISO 格式再返回前端
            def ms_to_iso(ms_str: str) -> str:
                if not ms_str:
                    return ""
                try:
                    from datetime import datetime, timezone

                    return datetime.fromtimestamp(
                        int(ms_str) / 1000, tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    return ms_str

            result.append(
                {
                    "id": pos.get("posId") or idx + 1,
                    "pos_id": pos.get("posId", ""),
                    "pos_side": pos_side,
                    "mgn_mode": pos.get("mgnMode", ""),
                    "strategy_id": None,
                    "strategy_name": None,
                    "symbol": pos.get("instId", ""),
                    "inst_type": pos.get("instType", "SWAP"),
                    "side": side,
                    "size": abs(pos_size),
                    "avg_price": avg_px,
                    "current_price": mark_px,
                    "last_price": last_px,
                    "unrealized_pnl": upl,
                    "unrealized_pnl_pct": upl_ratio * 100,
                    "notional_usd": notional_usd if notional_usd > 0 else None,
                    "margin": margin,
                    "imr": imr,
                    "mmr": mmr,
                    "mgn_ratio": mgn_ratio,
                    "leverage": lever,
                    "adl": safe_float(pos.get("adl", 0)),
                    "liquidation_price": liq_px if liq_px > 0 else None,
                    "created_at": ms_to_iso(pos.get("cTime", "")),
                    "updated_at": ms_to_iso(pos.get("uTime", "")),
                }
            )

        logger.info(f"获取到 {len(result)} 个持仓")
        return result
    except Exception as e:
        logger.error(f"获取持仓失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/account-snapshots")
async def get_account_snapshots(
    days: int = Query(7, ge=1, le=30, description="查询天数，最多30天"),
    user_id: int = Depends(require_current_user_id),
):
    """
    获取账户净值历史快照

    返回近 N 天的净值快照列表，并计算期间的最大回撤。
    快照由后台每小时自动保存一次（服务首次启动时立即保存一次）。
    """
    from app.core.database import SessionLocal
    from app.models.account_snapshot import AccountSnapshot

    tz_utc8 = timezone(timedelta(hours=8))
    now = datetime.now(tz_utc8)
    start_time = now - timedelta(days=days)

    db = SessionLocal()
    try:
        snapshots = (
            db.query(AccountSnapshot)
            .filter(
                AccountSnapshot.user_id == user_id,
                AccountSnapshot.created_at >= start_time,
            )
            .order_by(AccountSnapshot.created_at.asc())
            .all()
        )

        snap_list = [
            {
                "total_equity": s.total_equity,
                "available_balance": s.available_balance,
                "unrealized_pnl": s.unrealized_pnl,
                "timestamp": s.created_at.isoformat(),
            }
            for s in snapshots
        ]

        # 计算最大回撤（从峰值到谷值的最大跌幅）
        max_drawdown = 0.0
        max_drawdown_pct = 0.0
        if snap_list:
            # 过滤异常快照：equity <= 0 的点直接跳过
            # 同时过滤极端异常值：若某点低于所有快照中位数的 20%，视为数据异常
            valid_equities = [
                s["total_equity"] for s in snap_list if s["total_equity"] > 0
            ]
            if valid_equities:
                sorted_eq = sorted(valid_equities)
                median_eq = sorted_eq[len(sorted_eq) // 2]
                threshold = median_eq * 0.2  # 低于中位数 20% 视为异常
                valid_snaps = [s for s in snap_list if s["total_equity"] >= threshold]
            else:
                valid_snaps = []

            if valid_snaps:
                peak = valid_snaps[0]["total_equity"]
                for snap in valid_snaps:
                    equity = snap["total_equity"]
                    if equity > peak:
                        peak = equity
                    if peak > 0:
                        dd_pct = (peak - equity) / peak * 100
                        if dd_pct > max_drawdown_pct:
                            max_drawdown_pct = dd_pct
                            max_drawdown = peak - equity

        return {
            "code": 0,
            "msg": "success",
            "data": {
                "snapshots": snap_list,
                "max_drawdown": round(max_drawdown, 4),
                "max_drawdown_pct": round(max_drawdown_pct, 4),
                "days": days,
                "count": len(snap_list),
            },
        }
    except Exception as e:
        logger.error(f"获取账户快照失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/daily-pnl")
async def get_daily_pnl(
    user_id: int = Depends(require_current_user_id),
):
    """
    获取今日盈亏基线（UTC+8 自然日 0:00 重置）

    返回今日0:00最近一次快照的净值作为基线，前端结合当前净值计算今日盈亏。
    若今日无快照，则返回昨日最后一条快照作为替代基线。
    """
    from app.core.database import SessionLocal
    from app.models.account_snapshot import AccountSnapshot

    tz_utc8 = timezone(timedelta(hours=8))
    now = datetime.now(tz_utc8)
    # 今日 UTC+8 0:00
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    db = SessionLocal()
    try:
        # 优先获取今日0:00之后的第一条快照作为基线
        baseline = (
            db.query(AccountSnapshot)
            .filter(
                AccountSnapshot.user_id == user_id,
                AccountSnapshot.created_at >= today_start,
            )
            .order_by(AccountSnapshot.created_at.asc())
            .first()
        )

        # 若今日暂无快照，取昨日最后一条
        if not baseline:
            baseline = (
                db.query(AccountSnapshot)
                .filter(
                    AccountSnapshot.user_id == user_id,
                    AccountSnapshot.created_at < today_start,
                )
                .order_by(AccountSnapshot.created_at.desc())
                .first()
            )

        if baseline:
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "baseline_equity": baseline.total_equity,
                    "baseline_time": baseline.created_at.isoformat(),
                    "has_baseline": True,
                },
            }
        else:
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "baseline_equity": None,
                    "baseline_time": None,
                    "has_baseline": False,
                },
            }
    except Exception as e:
        logger.error(f"获取今日盈亏基线失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
