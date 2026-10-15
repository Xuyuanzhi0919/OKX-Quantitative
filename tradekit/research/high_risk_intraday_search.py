#!/usr/bin/env python3
"""Search high-risk intraday OKX swap strategies.

Research-only. It ranks liquid USDT swaps each hour, executes at next-hour open,
and tests short holding windows suited for aggressive 3x/5x variants.
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import math
import os
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.services.exchange.okx import OKXExchange  # noqa: E402


logger.remove()

HOUR_MS = 3_600_000
DAY_MS = 86_400_000


@dataclass(frozen=True)
class Params:
    mode: str
    rank_feature: str
    hold_hours: int
    top_n: int
    min_signal: float
    min_gap: float
    min_vol_ratio: float
    stop_loss_pct: float
    market_filter: str


BENCHMARK_SYMBOLS = {"BTC-USDT-SWAP", "ETH-USDT-SWAP"}


def pct(a: float, b: float) -> float:
    return a / b - 1 if b else 0.0


async def fetch_symbol(exchange: OKXExchange, symbol: str, start_ms: int, end_ms: int) -> tuple[str, list[dict[str, float]]]:
    cursor = end_ms + 1
    rows: dict[int, dict[str, float]] = {}
    while cursor > start_ms:
        batch = await exchange.get_history_kline(symbol, "1H", limit=100, after=str(cursor))
        if not batch:
            break
        oldest = cursor
        for item in batch:
            ts = int(item["ts"])
            oldest = min(oldest, ts)
            if start_ms <= ts <= end_ms and str(item.get("confirm", "1")) == "1":
                rows[ts] = {
                    "open": float(item["o"]),
                    "high": float(item["h"]),
                    "low": float(item["l"]),
                    "close": float(item["c"]),
                    "volume": float(item.get("volCcyQuote") or item.get("volCcy") or item.get("vol") or 0),
                }
        if oldest >= cursor:
            break
        cursor = oldest
        await asyncio.sleep(0.03)
    return symbol, [{"ts": ts, **rows[ts]} for ts in sorted(rows)]


async def load_data(days: int, universe_size: int, cache_path: Path) -> dict[str, list[dict[str, float]]]:
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - days * DAY_MS
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if (
            cached.get("days") >= days
            and cached.get("universe_size") >= universe_size
            and cached.get("end_ms", 0) >= end_ms - 2 * HOUR_MS
            and BENCHMARK_SYMBOLS.issubset(set(cached.get("data", {})))
        ):
            return {k: v for k, v in cached["data"].items() if len(v) >= days * 18}

    proxy = os.getenv("OKX_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    exchange = OKXExchange(api_key="", secret_key="", passphrase="", simulated=False, proxy=proxy)
    try:
        tickers = await exchange.get_tickers("SWAP")
        ranked = []
        for ticker in tickers:
            symbol = ticker.get("instId", "")
            if not symbol.endswith("-USDT-SWAP"):
                continue
            vol = float(ticker.get("volCcy24h") or ticker.get("vol24h") or 0)
            last = float(ticker.get("last") or 0)
            if vol > 0 and last > 0:
                ranked.append((vol, symbol))
        symbols = [symbol for _, symbol in sorted(ranked, reverse=True)[:universe_size]]
        for symbol in sorted(BENCHMARK_SYMBOLS):
            if symbol not in symbols:
                symbols.append(symbol)

        semaphore = asyncio.Semaphore(5)

        async def limited(symbol: str) -> tuple[str, list[dict[str, float]]]:
            async with semaphore:
                return await fetch_symbol(exchange, symbol, start_ms, end_ms)

        pairs = await asyncio.gather(*(limited(symbol) for symbol in symbols))
    finally:
        await exchange.close()

    data = {symbol: rows for symbol, rows in pairs if len(rows) >= days * 18}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "days": days,
        "universe_size": universe_size,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "data": data,
    }))
    return data


def row_feature(rows: list[dict[str, float]], i: int) -> dict[str, float]:
    ret_1h = pct(rows[i]["close"], rows[i - 1]["close"])
    ret_4h = pct(rows[i]["close"], rows[i - 4]["close"])
    ret_24h = pct(rows[i]["close"], rows[i - 24]["close"])
    vol_now = rows[i]["volume"]
    vol_mean = statistics.mean(row["volume"] for row in rows[i - 24:i]) or 1.0
    return {
        "ret_1h": ret_1h,
        "ret_4h": ret_4h,
        "ret_24h": ret_24h,
        "vol_ratio": vol_now / vol_mean,
    }


def market_ok(features_by_symbol: dict[str, dict[int, dict[str, float]]], ts: int, market_filter: str) -> bool:
    if market_filter == "none":
        return True
    btc = features_by_symbol.get("BTC-USDT-SWAP", {}).get(ts)
    eth = features_by_symbol.get("ETH-USDT-SWAP", {}).get(ts)
    if not btc or not eth:
        return False
    if market_filter == "btc_4h_positive":
        return btc["ret_4h"] > 0
    if market_filter == "btc_eth_1h_positive":
        return btc["ret_1h"] > 0 and eth["ret_1h"] > 0
    if market_filter == "btc_eth_4h_positive":
        return btc["ret_4h"] > 0 and eth["ret_4h"] > 0
    raise ValueError(market_filter)


def backtest(
    data: dict[str, list[dict[str, float]]],
    maps: dict[str, dict[int, int]],
    features_by_symbol: dict[str, dict[int, dict[str, float]]],
    timeline: list[int],
    params: Params,
    leverage: float,
    cost: float,
    start_ms: int,
    end_ms: int,
) -> dict[str, Any]:
    equity = peak = 1.0
    max_dd = 0.0
    trades: list[float] = []
    trade_log: list[dict[str, Any]] = []
    next_entry_ts = 0

    for ts in timeline:
        if ts < start_ms or ts > end_ms:
            continue
        if ts < next_entry_ts:
            continue
        if not market_ok(features_by_symbol, ts, params.market_filter):
            continue
        ranked = []
        for symbol, rows in data.items():
            if symbol in BENCHMARK_SYMBOLS:
                continue
            i = maps[symbol].get(ts)
            if i is None or i < 24 or i + params.hold_hours >= len(rows):
                continue
            features = features_by_symbol[symbol].get(ts)
            if not features:
                continue
            if features["vol_ratio"] < params.min_vol_ratio:
                continue
            score = features[params.rank_feature]
            entry = rows[i + 1]["open"]
            exit_row = rows[i + params.hold_hours]
            exit_px = exit_row["close"]
            if params.mode == "short_top":
                stop_px = entry * (1 + params.stop_loss_pct)
                if exit_row["high"] >= stop_px:
                    exit_px = stop_px
            else:
                stop_px = entry * (1 - params.stop_loss_pct)
                if exit_row["low"] <= stop_px:
                    exit_px = stop_px
            forward = pct(exit_px, entry)
            ranked.append((score, symbol, forward, features))
        if len(ranked) < max(12, params.top_n * 5):
            continue
        ranked.sort(reverse=True)
        top = ranked[:params.top_n]
        bottom = ranked[-params.top_n:]
        if top[0][0] < params.min_signal:
            continue
        if len(ranked) > 1 and top[0][0] - ranked[1][0] < params.min_gap:
            continue

        if params.mode == "short_top":
            gross = -statistics.mean(row[2] for row in top)
            selected = top
        elif params.mode == "long_top":
            gross = statistics.mean(row[2] for row in top)
            selected = top
        elif params.mode == "long_bottom_short_top":
            gross = statistics.mean(row[2] for row in bottom) - statistics.mean(row[2] for row in top)
            gross *= 0.5
            selected = top + bottom
        else:
            raise ValueError(params.mode)

        ret = leverage * (gross - cost)
        equity *= max(0.0, 1.0 + ret)
        trades.append(ret)
        trade_log.append({
            "ts": ts,
            "symbols": [row[1] for row in selected],
            "gross_pct": gross * 100,
            "ret_pct": ret * 100,
            "top_score_pct": top[0][0] * 100,
            "top_vol_ratio": top[0][3]["vol_ratio"],
        })
        next_entry_ts = ts + params.hold_hours * HOUR_MS
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0.0)

    wins = [ret for ret in trades if ret > 0]
    losses = [ret for ret in trades if ret < 0]
    return {
        "params": asdict(params),
        "leverage": leverage,
        "return_pct": (equity - 1) * 100,
        "max_drawdown_pct": max_dd,
        "trades": len(trades),
        "win_rate_pct": len(wins) / len(trades) * 100 if trades else 0.0,
        "mean_trade_pct": statistics.mean(trades) * 100 if trades else 0.0,
        "worst_trade_pct": min(trades) * 100 if trades else 0.0,
        "best_trade_pct": max(trades) * 100 if trades else 0.0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else (math.inf if wins else 0.0),
        "last_3d_trades": [row for row in trade_log if row["ts"] >= end_ms - 3 * DAY_MS],
        "recent_trades": trade_log[-20:],
    }


def compact(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "params": result["params"],
        "leverage": result["leverage"],
        "return_pct": round(result["return_pct"], 2),
        "max_drawdown_pct": round(result["max_drawdown_pct"], 2),
        "trades": result["trades"],
        "win_rate_pct": round(result["win_rate_pct"], 2),
        "mean_trade_pct": round(result["mean_trade_pct"], 3),
        "worst_trade_pct": round(result["worst_trade_pct"], 2),
        "best_trade_pct": round(result["best_trade_pct"], 2),
        "profit_factor": result["profit_factor"] if result["profit_factor"] != math.inf else "inf",
        "last_3d_trades": result["last_3d_trades"],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--test-days", type=int, default=15)
    parser.add_argument("--universe-size", type=int, default=50)
    parser.add_argument("--cache", type=Path, default=ROOT / ".run/research/okx_1h_liquid_60d_50.json")
    parser.add_argument("--output", type=Path, default=ROOT / ".run/research/high_risk_intraday_search.json")
    parser.add_argument("--cost", type=float, default=0.0012)
    args = parser.parse_args()

    data = await load_data(args.days, args.universe_size, args.cache)
    maps = {symbol: {int(row["ts"]): i for i, row in enumerate(rows)} for symbol, rows in data.items()}
    features_by_symbol = {
        symbol: {int(rows[i]["ts"]): row_feature(rows, i) for i in range(24, len(rows))}
        for symbol, rows in data.items()
    }
    timeline = sorted({int(row["ts"]) for rows in data.values() for row in rows})
    start_ms = min(timeline)
    end_ms = max(timeline)
    split_ms = end_ms - args.test_days * DAY_MS

    grid = [
        Params(*values)
        for values in itertools.product(
            ("long_top",),
            ("ret_1h", "ret_4h"),
            (2, 4, 6),
            (1, 2),
            (0.06, 0.10),
            (0.0, 0.005, 0.01),
            (1.2, 1.8),
            (0.04, 0.06, 0.09, 0.12),
            ("none", "btc_4h_positive", "btc_eth_1h_positive", "btc_eth_4h_positive"),
        )
    ]
    prelim = []
    for params in grid:
        train = backtest(data, maps, features_by_symbol, timeline, params, 1.0, args.cost, start_ms, split_ms - 1)
        if train["trades"] < 8 or train["return_pct"] <= 0:
            continue
        test_1x = backtest(data, maps, features_by_symbol, timeline, params, 1.0, args.cost, split_ms, end_ms)
        if test_1x["trades"] < 2:
            continue
        prelim.append({"params_obj": params, "params": asdict(params), "train": train, "test_1x": test_1x})

    prelim.sort(key=lambda row: (
        row["test_1x"]["return_pct"] > 0,
        row["test_1x"]["return_pct"] - row["test_1x"]["max_drawdown_pct"] * 0.2,
        row["train"]["return_pct"],
    ), reverse=True)

    rows = []
    for row in prelim[:200]:
        params = row["params_obj"]
        test_3x = backtest(data, maps, features_by_symbol, timeline, params, 3.0, args.cost, split_ms, end_ms)
        test_5x = backtest(data, maps, features_by_symbol, timeline, params, 5.0, args.cost, split_ms, end_ms)
        rows.append({
            "params": row["params"], "train": row["train"], "test_1x": row["test_1x"],
            "test_3x": test_3x, "test_5x": test_5x,
        })

    rows.sort(key=lambda row: (
        row["test_3x"]["return_pct"] > 0,
        row["test_3x"]["return_pct"] - row["test_3x"]["max_drawdown_pct"] * 0.2,
        row["train"]["return_pct"],
    ), reverse=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols": sorted(data),
        "period": {
            "start": datetime.fromtimestamp(start_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "split": datetime.fromtimestamp(split_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "end": datetime.fromtimestamp(end_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M"),
        },
        "cost": args.cost,
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    print(json.dumps({
        "symbols": len(data),
        "period": payload["period"],
        "candidates": len(rows),
        "top_10": [
            {
                "train": compact(row["train"]),
                "test_1x": compact(row["test_1x"]),
                "test_3x": compact(row["test_3x"]),
                "test_5x": compact(row["test_5x"]),
            }
            for row in rows[:10]
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
