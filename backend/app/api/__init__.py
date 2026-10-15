"""
API路由聚合
"""

from fastapi import APIRouter
from .endpoints import (
    auth,
    strategies,
    orders,
    positions,
    market,
    backtest,
    api_configs,
    alerts,
    risk_control,
    ai_analysis,
    ai_configs,
)

api_router = APIRouter()

# 注册各模块路由
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_router.include_router(strategies.router, prefix="/strategies", tags=["策略管理"])
api_router.include_router(orders.router, prefix="/orders", tags=["订单管理"])
api_router.include_router(positions.router, prefix="/positions", tags=["持仓管理"])
api_router.include_router(market.router, prefix="/market", tags=["行情数据"])
api_router.include_router(backtest.router, prefix="/backtest", tags=["回测系统"])
api_router.include_router(api_configs.router, prefix="/api-configs", tags=["API配置"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["告警管理"])
api_router.include_router(
    risk_control.router, prefix="/risk-control", tags=["风控管理"]
)
api_router.include_router(ai_analysis.router, prefix="/ai", tags=["AI分析"])
api_router.include_router(ai_configs.router, prefix="/ai-configs", tags=["AI配置"])
