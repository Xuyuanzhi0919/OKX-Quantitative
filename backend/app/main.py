"""
FastAPI主应用
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import socketio
from app.core.config import settings
from app.api import api_router
from app.websocket import sio, okx_ws_client
from app.models.strategy import StrategyStatus

# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="OKK量化交易系统API",
    docs_url="/docs",
    redoc_url="/redoc",
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "healthy"}


# 注册API路由
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    from loguru import logger
    from app.core.database import SessionLocal, engine
    from app.models.strategy import Strategy
    from app.models.api_config import APIConfig

    # 自动创建新增的 account_snapshots 表（checkfirst=True 保证幂等）
    try:
        from app.models.account_snapshot import AccountSnapshot
        AccountSnapshot.__table__.create(bind=engine, checkfirst=True)
        logger.info("✅ account_snapshots 表已就绪")
    except Exception as e:
        logger.error(f"❌ 创建 account_snapshots 表失败: {e}")
    from app.services.strategy.manager import strategy_manager
    from app.websocket.okx_websocket import OKXWebSocketClient
    from app.websocket.manager import ws_manager
    from app.services.notification import notification_service
    from app.services.altcoin_momentum_monitor import altcoin_momentum_monitor
    from app.services.tradfi_momentum_monitor import tradfi_momentum_monitor
    from app.services.account_monitor import account_monitor
    import app.websocket as websocket_module

    if not settings.DEBUG and settings.SECRET_KEY == "your-secret-key-change-in-production-please":
        raise RuntimeError("生产环境必须修改 SECRET_KEY")

    # 注入WebSocket管理器到通知服务
    notification_service.set_websocket_manager(ws_manager)
    logger.info("✅ WebSocket管理器已注入到通知服务")

    # 加载推送渠道配置
    import json
    import os
    config_path = os.path.join(os.path.dirname(__file__), "..", "notification_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                notification_config = json.load(f)
            notification_service.configure_channels(notification_config)
            logger.info("✅ 推送渠道配置已加载")

            altcoin_momentum_monitor.configure(
                notification_config.get("altcoin_momentum_monitor", {})
            )
            tradfi_momentum_monitor.configure(
                notification_config.get("tradfi_momentum_monitor", {})
            )
            account_monitor.configure(
                notification_config.get("account_risk_monitor", {})
            )
        except Exception as e:
            logger.error(f"❌ 加载推送配置失败: {e}")
    else:
        logger.warning(f"⚠️ 推送配置文件不存在: {config_path}, 跳过配置")

    # 尝试获取用户的API配置,用于Private WebSocket认证
    try:
        db = SessionLocal()
        api_config = db.query(APIConfig).filter(
            APIConfig.is_active == True
        ).first()
        db.close()

        if api_config:
            # 使用API凭证重新初始化okx_ws_client
            logger.info("🔐 检测到API配置,初始化Private WebSocket支持")
            websocket_module.okx_ws_client = OKXWebSocketClient(
                api_key=api_config.api_key,
                secret_key=api_config.secret_key,
                passphrase=api_config.passphrase,
                simulated=api_config.is_simulated
            )
            # 更新全局引用
            globals()['okx_ws_client'] = websocket_module.okx_ws_client
        else:
            logger.warning("⚠️ 未找到API配置,Private WebSocket将不可用")
    except Exception as e:
        logger.error(f"❌ 获取API配置失败: {e}")

    # 启动OKX WebSocket客户端
    await websocket_module.okx_ws_client.start()

    # 启动账户监控器(定期推送余额和持仓)
    try:
        await account_monitor.start()
        logger.info("📊 账户监控器已启动")
    except Exception as e:
        logger.error(f"账户监控器启动失败，已跳过: {e}")

    # 启动山寨币1分钟急涨监控
    try:
        await altcoin_momentum_monitor.start()
    except Exception as e:
        logger.error(f"山寨币短线异动监控启动失败，已跳过: {e}")

    # 启动 TradFi 双向异动监控（只读，不参与下单）
    try:
        await tradfi_momentum_monitor.start()
    except Exception as e:
        logger.error(f"TradFi 异动监控启动失败，已跳过: {e}")

    # 自动恢复运行中的策略
    try:
        db = SessionLocal()
        running_strategies = db.query(Strategy).filter(
            Strategy.status == StrategyStatus.RUNNING
        ).all()

        if running_strategies:
            logger.warning(
                f"🔄 检测到 {len(running_strategies)} 个策略在后端重启前处于运行状态, "
                f"正在自动恢复..."
            )

            success_count = 0
            fail_count = 0

            for strategy in running_strategies:
                try:
                    logger.info(f"正在恢复策略: {strategy.id} ({strategy.name}) - {strategy.symbol}")

                    # 获取用户的API配置和交易所实例
                    from app.services.api_config_service import APIConfigService
                    import json

                    exchange = APIConfigService.get_exchange(
                        user_id=strategy.user_id,
                        config_id=strategy.api_config_id,
                    )
                    if not exchange:
                        raise Exception(f"用户 {strategy.user_id} 没有有效的API配置")

                    # 解析策略参数
                    parameters = json.loads(strategy.parameters) if isinstance(strategy.parameters, str) else strategy.parameters

                    # 调用策略管理器启动策略
                    await strategy_manager.start_strategy(
                        strategy_id=strategy.id,
                        strategy_type=strategy.type,
                        symbol=strategy.symbol,
                        parameters=parameters,
                        exchange=exchange,
                        user_id=strategy.user_id
                    )

                    success_count += 1
                    logger.info(f"✅ 策略 {strategy.name} 恢复成功")

                except Exception as e:
                    fail_count += 1
                    logger.error(f"❌ 策略 {strategy.name} 恢复失败: {e}")

                    # 恢复失败时,将策略标记为停止状态
                    try:
                        strategy.status = 'stopped'
                        db.commit()
                        logger.warning(f"已将策略 {strategy.name} 标记为停止状态")
                    except Exception as commit_error:
                        logger.error(f"更新策略状态失败: {commit_error}")
                        db.rollback()

            logger.info(
                f"策略恢复完成: 成功 {success_count} 个, 失败 {fail_count} 个"
            )
        else:
            logger.info("✅ 没有需要恢复的策略")

        db.close()
    except Exception as e:
        logger.error(f"策略恢复过程出错: {e}")
        import traceback
        logger.error(traceback.format_exc())


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    from loguru import logger
    from app.services.strategy.manager import strategy_manager
    from app.services.account_monitor import account_monitor
    from app.services.altcoin_momentum_monitor import altcoin_momentum_monitor
    from app.services.tradfi_momentum_monitor import tradfi_momentum_monitor

    # 停止账户监控器
    await account_monitor.stop()

    # 停止山寨币短线异动监控
    await altcoin_momentum_monitor.stop()

    # 停止 TradFi 异动监控
    await tradfi_momentum_monitor.stop()

    # 停止所有运行中的策略
    try:
        running_strategy_ids = list(strategy_manager.strategies.keys())
        if running_strategy_ids:
            logger.warning(f"正在停止 {len(running_strategy_ids)} 个运行中的策略...")
            for strategy_id in running_strategy_ids:
                try:
                    # close_position=False：后端重启只停止监控，不平仓，重启后从交易所恢复持仓
                    await strategy_manager.stop_strategy(strategy_id, close_position=False)
                    logger.info(f"已停止策略 {strategy_id}")
                except Exception as e:
                    logger.error(f"停止策略 {strategy_id} 失败: {e}")
            logger.info("所有策略已停止")
    except Exception as e:
        logger.error(f"停止策略时出错: {e}")

    # 关闭所有交易所连接
    try:
        if strategy_manager.exchanges:
            logger.info(f"正在关闭 {len(strategy_manager.exchanges)} 个交易所连接...")
            for cache_key, exchange in strategy_manager.exchanges.items():
                try:
                    await exchange.close()
                    logger.debug(f"已关闭交易所连接: {cache_key}")
                except Exception as e:
                    logger.error(f"关闭交易所连接失败: {e}")
            logger.info("所有交易所连接已关闭")
    except Exception as e:
        logger.error(f"关闭交易所连接时出错: {e}")

    # 关闭OKX WebSocket客户端
    import app.websocket as websocket_module
    await websocket_module.okx_ws_client.disconnect()


# 创建Socket.IO ASGI应用 - 必须在所有路由定义之后
socket_app = socketio.ASGIApp(
    sio,
    other_asgi_app=app
)


if __name__ == "__main__":
    import uvicorn
    # from app.core.process_lock import ProcessLock

    # 获取进程锁，防止多实例启动（临时禁用）
    # process_lock = ProcessLock()
    # with process_lock:
    uvicorn.run(
        "app.main:socket_app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
