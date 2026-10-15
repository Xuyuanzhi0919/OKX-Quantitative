"""
AI市场分析API端点
提供多因子分析、决策建议等功能
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from app.core.database import get_db
from app.api.deps import require_current_user_id
from app.services.exchange.okx import OKXExchange
from app.services.ai.multi_factor_analyzer import MultiFactorAnalyzer
from app.models.api_config import APIConfig
from datetime import datetime
import asyncio
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


get_current_user_api_config = require_current_user_id


class AnalysisRequest(BaseModel):
    symbol: str
    detailed: bool = False  # 是否返回详细分析


class AnalysisResponse(BaseModel):
    symbol: str
    timestamp: str
    decision: str  # long | short | wait
    confidence: float
    scores: dict
    factors: dict
    risk_level: str
    suggested_strategy: Optional[str]
    reasoning: str


class TopAltcoinStrategyRequest(BaseModel):
    limit: int = 5
    inst_type: str = "SWAP"
    quote_ccy: str = "USDT"
    min_volume_usdt: float = 1000000
    exclude_majors: bool = True


class StealthAltcoinStrategyRequest(BaseModel):
    limit: int = 5
    inst_type: str = "SWAP"
    quote_ccy: str = "USDT"
    min_volume_usdt: float = 3000000
    min_range_pct: float = 3
    max_range_pct: float = 12
    max_change_pct: float = 8
    min_change_pct: float = -8
    trend_timeframe: str = "15m"
    trend_lookback: int = 192
    max_lookback_drop_pct: float = 10
    min_ma_gap_pct: float = -2
    max_recent_position: float = 0.75
    exclude_majors: bool = True


MAJOR_AND_STABLE_COINS = {
    "BTC",
    "ETH",
    "USDT",
    "USDC",
    "DAI",
    "FDUSD",
    "TUSD",
    "USDD",
    "USD",
}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _base_ccy_from_inst_id(inst_id: str) -> str:
    return inst_id.split("-")[0].upper() if inst_id else ""


def _ticker_change_pct(ticker: Dict[str, Any]) -> float:
    last = _to_float(ticker.get("last"))
    open24h = _to_float(ticker.get("open24h"))
    if last <= 0 or open24h <= 0:
        return 0.0
    return (last - open24h) / open24h * 100


def _ticker_volume_usdt(ticker: Dict[str, Any]) -> float:
    volume_ccy = _to_float(ticker.get("volCcy24h"))
    last = _to_float(ticker.get("last"))
    return max(
        volume_ccy,
        volume_ccy * last,
        _to_float(ticker.get("vol24h")) * last,
    )


def _range_position(ticker: Dict[str, Any]) -> float:
    last = _to_float(ticker.get("last"))
    high = _to_float(ticker.get("high24h"))
    low = _to_float(ticker.get("low24h"))
    if last <= 0 or high <= low:
        return 1.0
    return max(0.0, min(1.0, (last - low) / (high - low)))


def _range_pct(ticker: Dict[str, Any]) -> float:
    high = _to_float(ticker.get("high24h"))
    low = _to_float(ticker.get("low24h"))
    last = _to_float(ticker.get("last"))
    if high <= low or last <= 0:
        return 0.0
    return (high - low) / last * 100


def _stealth_score(ticker: Dict[str, Any]) -> float:
    change_pct = _ticker_change_pct(ticker)
    position = _range_position(ticker)
    range_pct = _range_pct(ticker)
    volume_usdt = _ticker_volume_usdt(ticker)

    volume_score = min(30.0, volume_usdt / 5000000)
    location_score = max(0.0, 35.0 * (1.0 - abs(position - 0.35) / 0.35))
    change_score = max(0.0, 20.0 - abs(change_pct - 1.5) * 2.0)
    range_score = min(15.0, range_pct)
    return volume_score + location_score + change_score + range_score


def _stealth_trend_metrics(klines: List[Dict[str, Any]]) -> Dict[str, float]:
    closes = [_to_float(kline.get("c")) for kline in reversed(klines)]
    closes = [close for close in closes if close > 0]
    if len(closes) < 60:
        return {
            "lookback_change_pct": 0.0,
            "ma_gap_pct": -100.0,
            "recent_position": 1.0,
        }

    first_close = closes[0]
    last_close = closes[-1]
    lookback_change_pct = (
        (last_close - first_close) / first_close * 100 if first_close > 0 else 0.0
    )

    fast_window = closes[-24:]
    slow_window = closes[-96:] if len(closes) >= 96 else closes
    fast_ma = sum(fast_window) / len(fast_window)
    slow_ma = sum(slow_window) / len(slow_window)
    ma_gap_pct = (fast_ma - slow_ma) / slow_ma * 100 if slow_ma > 0 else -100.0

    recent_window = closes[-96:] if len(closes) >= 96 else closes
    recent_low = min(recent_window)
    recent_high = max(recent_window)
    recent_position = (
        (last_close - recent_low) / (recent_high - recent_low)
        if recent_high > recent_low
        else 1.0
    )

    return {
        "lookback_change_pct": lookback_change_pct,
        "ma_gap_pct": ma_gap_pct,
        "recent_position": max(0.0, min(1.0, recent_position)),
    }


async def _get_stealth_trend_metrics(
    exchange: OKXExchange,
    symbol: str,
    timeframe: str,
    lookback: int,
) -> Dict[str, float]:
    klines = await exchange.get_kline(
        symbol, timeframe=timeframe, limit=min(max(lookback, 60), 300)
    )
    return _stealth_trend_metrics(klines)


def _analysis_for_stealth_candidate(
    symbol: str, candidate: Dict[str, Any], score: float
) -> Dict[str, Any]:
    confidence = max(0.35, min(0.85, score / 100))
    position = candidate.get("range_position", 1.0)
    change_pct = candidate.get("change_pct", 0.0)

    if position <= 0.45 and change_pct > -6:
        decision = "long"
        suggested_strategy = "swing_long"
        long_score = confidence
        short_score = max(0.05, 1 - confidence)
    else:
        decision = "wait"
        suggested_strategy = None
        long_score = confidence
        short_score = 1 - confidence

    return {
        "symbol": symbol,
        "timestamp": datetime.now().isoformat(),
        "decision": decision,
        "confidence": round(confidence, 3),
        "scores": {
            "long_score": round(long_score, 3),
            "short_score": round(short_score, 3),
            "wait_score": round(max(0.0, 1 - long_score - short_score), 3),
        },
        "factors": {
            "stealth": {
                "score": round(score, 2),
                "weight": 1,
                "details": {
                    "change_pct": round(change_pct, 2),
                    "range_position": round(position, 3),
                    "range_pct": round(candidate.get("range_pct", 0), 2),
                    "volume_usdt": round(candidate.get("volume_usdt", 0), 2),
                    "lookback_change_pct": round(
                        candidate.get("lookback_change_pct", 0), 2
                    ),
                    "ma_gap_pct": round(candidate.get("ma_gap_pct", 0), 2),
                    "recent_position": round(candidate.get("recent_position", 1), 3),
                },
            }
        },
        "risk_level": "medium" if candidate.get("range_pct", 0) > 12 else "low",
        "suggested_strategy": suggested_strategy,
        "reasoning": (
            f"潜伏候选评分 {score:.1f}。24h涨幅 {change_pct:.2f}%，"
            f"价格位于24h区间 {position*100:.1f}% 位置，"
            f"近周期涨跌 {candidate.get('lookback_change_pct', 0):.2f}%，"
            f"均线差 {candidate.get('ma_gap_pct', 0):.2f}%，"
            f"成交额约 {candidate.get('volume_usdt', 0):,.0f} USDT。"
        ),
    }


def _strategy_from_analysis(
    analysis: Dict[str, Any], change_pct: float, volume_usdt: float
) -> Dict[str, Any]:
    decision = analysis.get("decision") or "wait"
    risk_level = analysis.get("risk_level") or "high"
    confidence = _to_float(analysis.get("confidence"))

    if decision == "long":
        direction = "long"
    elif decision == "short":
        direction = "short"
    else:
        direction = "both"

    if risk_level == "low" and confidence >= 0.7:
        risk_per_trade = 0.02
        max_position_usd = 2000
        leverage = 3
    elif risk_level == "medium":
        risk_per_trade = 0.015
        max_position_usd = 1500
        leverage = 3
    else:
        risk_per_trade = 0.01
        max_position_usd = 1000
        leverage = 2

    if volume_usdt < 5000000:
        max_position_usd = min(max_position_usd, 500)
        leverage = min(leverage, 2)

    return {
        "type": "adaptive_grid_trend",
        "label": "自适应趋势网格",
        "direction": direction,
        "timeframe": "15m",
        "parameters": {
            "direction": direction,
            "trend_timeframe": "15m",
            "fast_period": 30,
            "slow_period": 120,
            "atr_period": 14,
            "entry_atr_multiple": 0.2,
            "stop_atr_multiple": 1.6,
            "take_profit_atr_multiple": 3.0,
            "risk_per_trade": risk_per_trade,
            "max_position_usd": max_position_usd,
            "leverage": leverage,
            "margin_mode": "isolated",
            "cooldown_seconds": 1800,
            "notify_near_trigger": True,
            "near_trigger_pct": 0.003,
            "near_trigger_cooldown_seconds": 600,
            "risk_fuse": {
                "enabled": True,
                "max_consecutive_losses": 3,
                "daily_loss_limit_pct": 0.02,
                "max_drawdown_pct": 0.05,
                "profit_factor_window": 10,
                "min_trades_for_profit_factor": 8,
                "min_profit_factor": 0.8,
                "cancel_orders_on_trigger": True,
                "close_position_on_trigger": False,
            },
        },
    }


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_market(
    request: AnalysisRequest,
    user_id: int = Depends(get_current_user_api_config),
    db: Session = Depends(get_db),
):
    """
    AI市场分析接口

    多因子综合分析:
    - 技术指标 (40%)
    - 市场情绪 (30%)
    - AI深度分析 (30%)
    """
    try:
        # 获取用户的API配置
        api_config = (
            db.query(APIConfig)
            .filter(APIConfig.user_id == user_id, APIConfig.is_active == True)
            .first()
        )

        if not api_config:
            raise HTTPException(status_code=400, detail="请先配置OKX API密钥")

        # 获取用户的AI配置
        from app.models.ai_config import AIConfig

        ai_config = (
            db.query(AIConfig)
            .filter(AIConfig.user_id == user_id, AIConfig.is_active == True)
            .first()
        )

        if not ai_config:
            raise HTTPException(status_code=400, detail="请先配置AI服务")

        # 创建交易所实例
        exchange = OKXExchange(
            api_key=api_config.api_key,
            secret_key=api_config.secret_key,
            passphrase=api_config.passphrase,
            simulated=api_config.is_simulated,
        )

        # 创建分析器
        analyzer = MultiFactorAnalyzer(exchange, ai_config.api_key)

        # 执行分析
        result = await analyzer.analyze(request.symbol)

        logger.info(
            f"分析完成: {request.symbol} -> {result['decision']} (信心度: {result['confidence']})"
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"市场分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


@router.get("/analysis/{symbol}")
async def get_analysis(
    symbol: str,
    user_id: int = Depends(get_current_user_api_config),
    db: Session = Depends(get_db),
):
    """
    GET方式调用分析（简化版）
    """
    return await analyze_market(
        AnalysisRequest(symbol=symbol, detailed=False), user_id, db
    )


@router.post("/analyze/batch")
async def analyze_batch(
    symbols: list[str],
    user_id: int = Depends(get_current_user_api_config),
    db: Session = Depends(get_db),
):
    """
    批量分析多个交易对

    返回每个交易对的分析结果
    """
    try:
        # 获取用户的API配置
        api_config = (
            db.query(APIConfig)
            .filter(APIConfig.user_id == user_id, APIConfig.is_active == True)
            .first()
        )

        if not api_config:
            raise HTTPException(status_code=400, detail="请先配置API密钥")

        exchange = OKXExchange(
            api_key=api_config.api_key,
            secret_key=api_config.secret_key,
            passphrase=api_config.passphrase,
            simulated=api_config.is_simulated,
        )

        analyzer = MultiFactorAnalyzer(exchange)

        results = []
        for symbol in symbols:
            try:
                result = await analyzer.analyze(symbol)
                results.append(result)
            except Exception as e:
                logger.error(f"分析{symbol}失败: {e}")
                results.append({"symbol": symbol, "error": str(e)})

        return {"results": results}

    except Exception as e:
        logger.error(f"批量分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量分析失败: {str(e)}")


@router.post("/top-altcoin-strategies")
async def analyze_top_altcoin_strategies(
    request: TopAltcoinStrategyRequest,
    user_id: int = Depends(get_current_user_api_config),
    db: Session = Depends(get_db),
):
    """
    选择24h涨幅榜前N个USDT山寨币并给出策略建议。
    """
    api_config = (
        db.query(APIConfig)
        .filter(APIConfig.user_id == user_id, APIConfig.is_active == True)
        .first()
    )

    if not api_config:
        raise HTTPException(status_code=400, detail="请先配置OKX API密钥")

    from app.models.ai_config import AIConfig

    ai_config = (
        db.query(AIConfig)
        .filter(AIConfig.user_id == user_id, AIConfig.is_active == True)
        .first()
    )

    exchange = OKXExchange(
        api_key=api_config.api_key,
        secret_key=api_config.secret_key,
        passphrase=api_config.passphrase,
        simulated=api_config.is_simulated,
    )

    try:
        tickers = await exchange.get_tickers(request.inst_type.upper())
        suffix = (
            f"-{request.quote_ccy.upper()}-SWAP"
            if request.inst_type.upper() == "SWAP"
            else f"-{request.quote_ccy.upper()}"
        )

        candidates = []
        for ticker in tickers:
            inst_id = ticker.get("instId", "")
            if not inst_id.endswith(suffix):
                continue

            base_ccy = _base_ccy_from_inst_id(inst_id)
            if request.exclude_majors and base_ccy in MAJOR_AND_STABLE_COINS:
                continue

            change_pct = _ticker_change_pct(ticker)
            volume_usdt = _ticker_volume_usdt(ticker)
            if change_pct <= 0 or volume_usdt < request.min_volume_usdt:
                continue

            candidates.append(
                {
                    "symbol": inst_id,
                    "base_ccy": base_ccy,
                    "last": _to_float(ticker.get("last")),
                    "open24h": _to_float(ticker.get("open24h")),
                    "high24h": _to_float(ticker.get("high24h")),
                    "low24h": _to_float(ticker.get("low24h")),
                    "volume_usdt": volume_usdt,
                    "change_pct": change_pct,
                }
            )

        top_candidates = sorted(
            candidates, key=lambda item: item["change_pct"], reverse=True
        )[: request.limit]
        analyzer = MultiFactorAnalyzer(
            exchange, ai_config.api_key if ai_config else None
        )

        results: List[Dict[str, Any]] = []
        for candidate in top_candidates:
            try:
                analysis = await analyzer.analyze(candidate["symbol"])
            except Exception as exc:
                logger.error(f"涨幅榜分析失败 {candidate['symbol']}: {exc}")
                analysis = analyzer._get_default_analysis(candidate["symbol"])

            recommendation = _strategy_from_analysis(
                analysis,
                candidate["change_pct"],
                candidate["volume_usdt"],
            )
            results.append(
                {
                    **candidate,
                    "change_pct": round(candidate["change_pct"], 2),
                    "volume_usdt": round(candidate["volume_usdt"], 2),
                    "analysis": analysis,
                    "recommended_strategy": recommendation,
                }
            )

        return {
            "code": 0,
            "msg": "success",
            "data": {
                "items": results,
                "universe_count": len(candidates),
                "ai_enabled": ai_config is not None,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"涨幅榜山寨币策略分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"涨幅榜分析失败: {str(e)}")
    finally:
        await exchange.close()


@router.post("/stealth-altcoin-strategies")
async def analyze_stealth_altcoin_strategies(
    request: StealthAltcoinStrategyRequest,
    user_id: int = Depends(get_current_user_api_config),
    db: Session = Depends(get_db),
):
    """
    筛选适合潜伏的USDT山寨币候选：成交量足够、未明显过热、价格位置偏低。
    """
    api_config = (
        db.query(APIConfig)
        .filter(APIConfig.user_id == user_id, APIConfig.is_active == True)
        .first()
    )

    if not api_config:
        raise HTTPException(status_code=400, detail="请先配置OKX API密钥")

    exchange = OKXExchange(
        api_key=api_config.api_key,
        secret_key=api_config.secret_key,
        passphrase=api_config.passphrase,
        simulated=api_config.is_simulated,
    )

    try:
        tickers = await exchange.get_tickers(request.inst_type.upper())
        suffix = (
            f"-{request.quote_ccy.upper()}-SWAP"
            if request.inst_type.upper() == "SWAP"
            else f"-{request.quote_ccy.upper()}"
        )

        candidates = []
        for ticker in tickers:
            inst_id = ticker.get("instId", "")
            if not inst_id.endswith(suffix):
                continue

            base_ccy = _base_ccy_from_inst_id(inst_id)
            if request.exclude_majors and base_ccy in MAJOR_AND_STABLE_COINS:
                continue

            change_pct = _ticker_change_pct(ticker)
            volume_usdt = _ticker_volume_usdt(ticker)
            range_pct = _range_pct(ticker)
            range_position = _range_position(ticker)

            if volume_usdt < request.min_volume_usdt:
                continue
            if (
                change_pct < request.min_change_pct
                or change_pct > request.max_change_pct
            ):
                continue
            if range_pct < request.min_range_pct or range_pct > request.max_range_pct:
                continue
            if range_position > 0.65:
                continue

            score = _stealth_score(ticker)
            candidates.append(
                {
                    "symbol": inst_id,
                    "base_ccy": base_ccy,
                    "last": _to_float(ticker.get("last")),
                    "open24h": _to_float(ticker.get("open24h")),
                    "high24h": _to_float(ticker.get("high24h")),
                    "low24h": _to_float(ticker.get("low24h")),
                    "volume_usdt": volume_usdt,
                    "change_pct": change_pct,
                    "range_pct": range_pct,
                    "range_position": range_position,
                    "stealth_score": score,
                }
            )

        preliminary_candidates = sorted(
            candidates,
            key=lambda item: item["stealth_score"],
            reverse=True,
        )[: max(request.limit * 8, 20)]

        semaphore = asyncio.Semaphore(6)

        async def enrich_candidate(
            candidate: Dict[str, Any]
        ) -> Optional[Dict[str, Any]]:
            try:
                async with semaphore:
                    metrics = await _get_stealth_trend_metrics(
                        exchange,
                        candidate["symbol"],
                        request.trend_timeframe,
                        request.trend_lookback,
                    )
                lookback_change_pct = metrics["lookback_change_pct"]
                ma_gap_pct = metrics["ma_gap_pct"]
                recent_position = metrics["recent_position"]
                if lookback_change_pct < -request.max_lookback_drop_pct:
                    return None
                if ma_gap_pct < request.min_ma_gap_pct:
                    return None
                if recent_position > request.max_recent_position:
                    return None

                trend_score = max(
                    0.0, min(10.0, lookback_change_pct + request.max_lookback_drop_pct)
                )
                ma_score = max(0.0, min(10.0, ma_gap_pct - request.min_ma_gap_pct))
                candidate.update(metrics)
                candidate["stealth_score"] = (
                    candidate["stealth_score"] + trend_score + ma_score
                )
                return candidate
            except Exception as exc:
                logger.warning(f"潜伏候选趋势过滤失败 {candidate['symbol']}: {exc}")
                return None

        enriched_candidates = await asyncio.gather(
            *[enrich_candidate(candidate) for candidate in preliminary_candidates]
        )
        top_candidates = sorted(
            [candidate for candidate in enriched_candidates if candidate is not None],
            key=lambda item: item["stealth_score"],
            reverse=True,
        )[: request.limit]

        results: List[Dict[str, Any]] = []
        for candidate in top_candidates:
            analysis = _analysis_for_stealth_candidate(
                candidate["symbol"],
                candidate,
                candidate["stealth_score"],
            )
            recommendation = _strategy_from_analysis(
                analysis,
                candidate["change_pct"],
                candidate["volume_usdt"],
            )
            recommendation["parameters"]["direction"] = "both"
            recommendation["parameters"]["fast_period"] = 30
            recommendation["parameters"]["slow_period"] = 120
            recommendation["parameters"]["entry_atr_multiple"] = 0.8
            recommendation["parameters"]["stop_atr_multiple"] = 2.8
            recommendation["parameters"]["take_profit_atr_multiple"] = 6.0
            recommendation["parameters"]["cooldown_seconds"] = 7200
            recommendation["parameters"]["risk_fuse"]["daily_loss_limit_pct"] = 0.03
            recommendation["parameters"]["risk_fuse"]["max_drawdown_pct"] = 0.08
            recommendation["direction"] = "both"
            results.append(
                {
                    **candidate,
                    "change_pct": round(candidate["change_pct"], 2),
                    "volume_usdt": round(candidate["volume_usdt"], 2),
                    "range_pct": round(candidate["range_pct"], 2),
                    "range_position": round(candidate["range_position"], 3),
                    "lookback_change_pct": round(
                        candidate.get("lookback_change_pct", 0), 2
                    ),
                    "ma_gap_pct": round(candidate.get("ma_gap_pct", 0), 2),
                    "recent_position": round(candidate.get("recent_position", 1), 3),
                    "stealth_score": round(candidate["stealth_score"], 2),
                    "analysis": analysis,
                    "recommended_strategy": recommendation,
                }
            )

        return {
            "code": 0,
            "msg": "success",
            "data": {
                "items": results,
                "universe_count": len(candidates),
                "preliminary_count": len(preliminary_candidates),
                "trend_filtered_count": len(
                    [
                        candidate
                        for candidate in enriched_candidates
                        if candidate is not None
                    ]
                ),
                "ai_enabled": False,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"潜伏山寨币策略分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"潜伏候选分析失败: {str(e)}")
    finally:
        await exchange.close()
