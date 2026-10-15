"""
行情数据API
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from app.services.exchange.okx import OKXExchange
from app.core.config import settings
from loguru import logger

router = APIRouter()


def get_okx_exchange() -> OKXExchange:
    """获取OKX交易所实例(私有API使用)"""
    if (
        not settings.OKX_API_KEY
        or not settings.OKX_SECRET_KEY
        or not settings.OKX_PASSPHRASE
    ):
        raise HTTPException(
            status_code=500,
            detail="OKX API配置未设置,请在.env文件中配置OKX_API_KEY、OKX_SECRET_KEY、OKX_PASSPHRASE",
        )

    return OKXExchange(
        api_key=settings.OKX_API_KEY,
        secret_key=settings.OKX_SECRET_KEY,
        passphrase=settings.OKX_PASSPHRASE,
        simulated=settings.OKX_SIMULATED,
        proxy=settings.OKX_PROXY,
    )


def get_public_okx_exchange() -> OKXExchange:
    """获取OKX交易所实例(公共API使用,不需要认证)"""
    return OKXExchange(
        api_key="",  # 公共API不需要密钥
        secret_key="",
        passphrase="",
        simulated=False,
        proxy=settings.OKX_PROXY,
    )


@router.get("/ticker/{symbol}")
async def get_ticker(symbol: str):
    """
    获取实时价格(公共API,无需认证)

    Args:
        symbol: 产品ID,如 BTC-USDT、BTC-USD-SWAP

    Returns:
        实时行情数据
    """
    try:
        exchange = get_public_okx_exchange()
        ticker = await exchange.get_ticker(symbol)
        await exchange.close()

        return {"code": 0, "msg": "success", "data": ticker}
    except Exception as e:
        logger.error(f"获取ticker失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/kline/{symbol}")
async def get_kline(
    symbol: str,
    timeframe: str = Query("1m", description="时间粒度,如 1m/5m/1H/1D"),
    limit: int = Query(100, ge=1, le=300, description="返回数量,最大300"),
    after: Optional[str] = Query(None, description="请求此时间戳之前的数据"),
    before: Optional[str] = Query(None, description="请求此时间戳之后的数据"),
):
    """
    获取K线数据

    Args:
        symbol: 产品ID,如 BTC-USDT
        timeframe: 时间粒度,支持 1m/3m/5m/15m/30m/1H/2H/4H/1D等
        limit: 返回K线数量,最大300
        after: 请求此时间戳之前的数据(更旧)
        before: 请求此时间戳之后的数据(更新)

    Returns:
        K线数据数组
    """
    try:
        exchange = get_public_okx_exchange()  # 使用公共API
        klines = await exchange.get_kline(
            symbol=symbol, timeframe=timeframe, limit=limit, after=after, before=before
        )
        await exchange.close()

        return {"code": 0, "msg": "success", "data": klines}
    except Exception as e:
        logger.error(f"获取K线失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orderbook/{symbol}")
async def get_orderbook(
    symbol: str, depth: int = Query(20, ge=1, le=400, description="深度档位,最大400")
):
    """
    获取订单簿

    Args:
        symbol: 产品ID,如 BTC-USDT
        depth: 深度档位数量,最大400

    Returns:
        订单簿数据
    """
    try:
        exchange = get_public_okx_exchange()  # 使用公共API
        orderbook = await exchange.get_orderbook(symbol, depth)
        await exchange.close()

        return {"code": 0, "msg": "success", "data": orderbook}
    except Exception as e:
        logger.error(f"获取订单簿失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/instruments")
async def get_instruments(
    inst_type: str = Query(
        "SPOT",
        description="产品类型: SPOT(币币)/SWAP(永续合约)/FUTURES(交割合约)/OPTION(期权)",
    ),
    uly: Optional[str] = Query(None, description="标的指数,如 BTC-USD (仅适用于合约)"),
    inst_id: Optional[str] = Query(None, description="产品ID,如 BTC-USDT"),
    quote_ccy: Optional[str] = Query(None, description="计价货币筛选,如 USDT"),
):
    """
    获取交易产品列表(公共API,无需认证)

    Args:
        inst_type: 产品类型 (SPOT/SWAP/FUTURES/OPTION)
        uly: 标的指数
        inst_id: 具体产品ID
        quote_ccy: 计价货币筛选(USDT/USDC/BTC等)

    Returns:
        交易产品列表,包含产品ID、交易精度、最小下单量等信息
    """
    try:
        exchange = get_public_okx_exchange()
        instruments = await exchange.get_instruments(
            inst_type=inst_type, uly=uly, inst_id=inst_id
        )
        await exchange.close()

        # 如果指定了计价货币,进行筛选
        # 注意: SWAP类型使用settleCcy字段, SPOT类型使用quoteCcy字段
        if quote_ccy:
            if inst_type == "SWAP":
                # 永续合约使用settleCcy字段
                instruments = [
                    inst for inst in instruments if inst.get("settleCcy") == quote_ccy
                ]
            else:
                # 现货等其他类型使用quoteCcy字段
                instruments = [
                    inst for inst in instruments if inst.get("quoteCcy") == quote_ccy
                ]

        # 只返回状态为live的产品
        instruments = [inst for inst in instruments if inst.get("state") == "live"]

        logger.info(f"获取交易产品成功: type={inst_type}, count={len(instruments)}")

        return {"code": 0, "msg": "success", "data": instruments}
    except Exception as e:
        logger.error(f"获取交易产品失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
