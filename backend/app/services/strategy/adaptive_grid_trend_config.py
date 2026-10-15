"""Shared defaults and coin selection for adaptive grid trend strategies."""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Dict, Iterable, List, Optional


STABLE_1000U_PROFILE_NAME = "1000U_stable_live"

STABLE_1000U_PARAMS: Dict = {
    "direction": "both",
    "trend_timeframe": "15m",
    "fast_period": 30,
    "slow_period": 60,
    "atr_period": 14,
    "entry_atr_multiple": 0.6,
    "stop_atr_multiple": 2.8,
    "take_profit_atr_multiple": 3.2,
    "risk_per_trade": 0.02,
    "max_position_usd": 800,
    "leverage": 5,
    "margin_mode": "isolated",
    "cooldown_seconds": 60 * 60,
    "notify_near_trigger": True,
    "near_trigger_pct": 0.003,
    "near_trigger_cooldown_seconds": 10 * 60,
    "risk_fuse": {
        "enabled": True,
        "max_consecutive_losses": 2,
        "daily_loss_limit_pct": 0.03,
        "max_drawdown_pct": 0.05,
        "profit_factor_window": 10,
        "min_trades_for_profit_factor": 8,
        "min_profit_factor": 0.8,
        "cancel_orders_on_trigger": True,
        "close_position_on_trigger": False,
    },
}


STABLE_1000U_ACTIVE_SYMBOLS = [
    "LTC-USDT-SWAP",
    "XRP-USDT-SWAP",
    "LINK-USDT-SWAP",
]

STABLE_1000U_WATCH_SYMBOLS = [
    "DOT-USDT-SWAP",
    "AVAX-USDT-SWAP",
    "SOL-USDT-SWAP",
]

STABLE_1000U_EXCLUDED_SYMBOLS = [
    "DOGE-USDT-SWAP",
    "TRX-USDT-SWAP",
]


# One-day validation snapshot from 2026-06-13 with the stable 1000U profile.
# It is used only as a prior; live liquidity still participates in ranking.
STABLE_1000U_VALIDATION: Dict[str, Dict[str, float]] = {
    "DOT-USDT-SWAP": {"return_pct": 2.762, "max_drawdown_pct": 1.036},
    "AVAX-USDT-SWAP": {"return_pct": 2.018, "max_drawdown_pct": 0.951},
    "LTC-USDT-SWAP": {"return_pct": 1.929, "max_drawdown_pct": 0.629},
    "XRP-USDT-SWAP": {"return_pct": 1.535, "max_drawdown_pct": 0.643},
    "LINK-USDT-SWAP": {"return_pct": 1.512, "max_drawdown_pct": 0.772},
    "BCH-USDT-SWAP": {"return_pct": 1.238, "max_drawdown_pct": 1.740},
    "SOL-USDT-SWAP": {"return_pct": 1.063, "max_drawdown_pct": 1.714},
    "ADA-USDT-SWAP": {"return_pct": 1.012, "max_drawdown_pct": 1.708},
    "BTC-USDT-SWAP": {"return_pct": 0.505, "max_drawdown_pct": 0.676},
    "ETH-USDT-SWAP": {"return_pct": 0.497, "max_drawdown_pct": 0.592},
    "DOGE-USDT-SWAP": {"return_pct": 0.142, "max_drawdown_pct": 1.923},
    "TRX-USDT-SWAP": {"return_pct": 0.067, "max_drawdown_pct": 0.486},
}


def adaptive_grid_trend_stable_params(overrides: Optional[Dict] = None) -> Dict:
    """Return the 1000U stable live parameter set with optional overrides."""
    params = deepcopy(STABLE_1000U_PARAMS)
    if overrides:
        risk_fuse = params.get("risk_fuse", {})
        override_risk_fuse = overrides.get("risk_fuse")
        params.update({k: v for k, v in overrides.items() if k != "risk_fuse"})
        if isinstance(override_risk_fuse, dict):
            risk_fuse.update(override_risk_fuse)
            params["risk_fuse"] = risk_fuse
    return params


def normalize_adaptive_grid_trend_params(parameters: Optional[Dict]) -> Dict:
    """Fill missing adaptive-grid-trend parameters from the stable 1000U profile."""
    params = adaptive_grid_trend_stable_params(parameters or {})
    if "timeframe" in params and "trend_timeframe" not in params:
        params["trend_timeframe"] = params["timeframe"]
    return params


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _ticker_by_symbol(tickers: Optional[Iterable[Dict]]) -> Dict[str, Dict]:
    if not tickers:
        return {}
    return {str(item.get("instId") or ""): item for item in tickers if item.get("instId")}


def select_stable_1000u_symbols(tickers: Optional[Iterable[Dict]] = None, active_limit: int = 3) -> Dict:
    """
    Rank adaptive-grid-trend symbols for a 1000 USDT account.

    The ranking intentionally prefers the stable initial basket over simply chasing
    yesterday's highest return. Liquidity is added when live OKX tickers are provided.
    """
    ticker_map = _ticker_by_symbol(tickers)
    candidate_symbols = list(dict.fromkeys(
        STABLE_1000U_ACTIVE_SYMBOLS
        + STABLE_1000U_WATCH_SYMBOLS
        + list(STABLE_1000U_VALIDATION.keys())
    ))
    volumes = [
        _safe_float(ticker_map.get(symbol, {}).get("volCcy24h"))
        for symbol in candidate_symbols
    ]
    max_log_volume = max((math.log10(value + 1) for value in volumes if value > 0), default=1.0)

    candidates: List[Dict] = []
    for symbol in candidate_symbols:
        validation = STABLE_1000U_VALIDATION.get(symbol, {})
        return_pct = _safe_float(validation.get("return_pct"))
        drawdown_pct = _safe_float(validation.get("max_drawdown_pct"))
        ticker = ticker_map.get(symbol, {})
        volume = _safe_float(ticker.get("volCcy24h"))
        liquidity_score = (math.log10(volume + 1) / max_log_volume * 20) if volume > 0 else 8
        stability_bonus = 20 if symbol in STABLE_1000U_ACTIVE_SYMBOLS else 10 if symbol in STABLE_1000U_WATCH_SYMBOLS else 0
        excluded_penalty = 50 if symbol in STABLE_1000U_EXCLUDED_SYMBOLS else 0
        score = return_pct * 12 - drawdown_pct * 5 + liquidity_score + stability_bonus - excluded_penalty
        candidates.append({
            "symbol": symbol,
            "score": round(score, 2),
            "return_pct": return_pct,
            "max_drawdown_pct": drawdown_pct,
            "volume_24h": volume,
            "liquidity_score": round(liquidity_score, 2),
            "recommended": symbol in STABLE_1000U_ACTIVE_SYMBOLS,
            "watch": symbol in STABLE_1000U_WATCH_SYMBOLS,
            "excluded": symbol in STABLE_1000U_EXCLUDED_SYMBOLS,
            "reason": _selection_reason(symbol),
        })

    ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
    excluded = [item for item in ranked if item["excluded"]]
    eligible = [item for item in ranked if not item["excluded"]]
    active = [item for item in eligible if item["symbol"] in STABLE_1000U_ACTIVE_SYMBOLS][:active_limit]
    active_symbols = {item["symbol"] for item in active}
    watch = [
        item for item in eligible
        if item["symbol"] not in active_symbols and (
            item["symbol"] in STABLE_1000U_WATCH_SYMBOLS or item["score"] >= 20
        )
    ][:max(0, 6 - len(active))]

    return {
        "profile": STABLE_1000U_PROFILE_NAME,
        "account_equity_usdt": 1000,
        "params": adaptive_grid_trend_stable_params(),
        "active": active,
        "watch": watch,
        "excluded": excluded,
        "ranked": ranked,
        "rules": {
            "max_active_symbols": active_limit,
            "daily_account_stop_loss_pct": 3,
            "pause_symbol_after_consecutive_losses": 2,
            "preferred_start": STABLE_1000U_ACTIVE_SYMBOLS,
        },
    }


def _selection_reason(symbol: str) -> str:
    if symbol in STABLE_1000U_ACTIVE_SYMBOLS:
        return "1000U账户首选实盘篮子，兼顾成交质量、回测收益和回撤"
    if symbol in STABLE_1000U_WATCH_SYMBOLS:
        return "收益弹性较好，适合作为观察/加仓候选"
    if symbol in STABLE_1000U_EXCLUDED_SYMBOLS:
        return "昨日稳定版回测质量偏弱，1000U账户先暂缓"
    return "备选主流永续，需结合当日流动性和趋势再决定"
