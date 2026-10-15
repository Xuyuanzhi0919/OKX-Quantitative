#!/usr/bin/env python3
"""Return-first, no-lookahead walk-forward research for liquid OKX swaps.

The script is deliberately isolated from OKK's database and live strategy manager.
It downloads public 1H candles, ranks the universe using information available at
each timestamp, executes signals on the next bar, and includes round-trip costs.
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.services.exchange.okx import OKXExchange  # noqa: E402


DEFAULT_UNIVERSE = [
    "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP",
    "XRP-USDT-SWAP", "DOGE-USDT-SWAP", "ADA-USDT-SWAP",
    "LINK-USDT-SWAP", "LTC-USDT-SWAP", "BCH-USDT-SWAP",
    "AVAX-USDT-SWAP",
]


@dataclass(frozen=True)
class Params:
    leverage: float
    position_fraction: float
    stop_atr: float
    take_r: float
    trailing_atr: float
    min_momentum_pct: float
    max_rsi: float


def ema(values: list[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1)
    out: list[float] = []
    value = values[0]
    for item in values:
        value = item if not out else value + alpha * (item - value)
        out.append(value)
    return out


def indicators(rows: list[dict[str, float]]) -> dict[str, list[float]]:
    close = [row["close"] for row in rows]
    high = [row["high"] for row in rows]
    low = [row["low"] for row in rows]
    tr = []
    gains = [0.0]
    losses = [0.0]
    for i in range(len(rows)):
        tr.append(high[i] - low[i] if i == 0 else max(
            high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])
        ))
        if i:
            delta = close[i] - close[i - 1]
            gains.append(max(delta, 0.0))
            losses.append(max(-delta, 0.0))
    avg_gain = ema(gains, 14)
    avg_loss = ema(losses, 14)
    rsi = [100.0 if loss == 0 else 100 - 100 / (1 + gain / loss) for gain, loss in zip(avg_gain, avg_loss)]
    return {"ema9": ema(close, 9), "ema21": ema(close, 21), "ema55": ema(close, 55), "atr": ema(tr, 14), "rsi": rsi}


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
                    "open": float(item["o"]), "high": float(item["h"]),
                    "low": float(item["l"]), "close": float(item["c"]),
                    "volume": float(item.get("volCcy") or item.get("vol") or 0),
                }
        if oldest >= cursor:
            break
        cursor = oldest
        if oldest < start_ms:
            break
        await asyncio.sleep(0.03)
    return symbol, [{"ts": ts, **rows[ts]} for ts in sorted(rows)]


async def load_data(universe: list[str], days: int, cache_path: Path) -> dict[str, list[dict[str, float]]]:
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - days * 86_400_000
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if cached.get("start_ms", 0) <= start_ms and cached.get("end_ms", 0) >= end_ms - 3_600_000:
            return cached["data"]
    exchange = OKXExchange(api_key="", secret_key="", passphrase="", simulated=False)
    semaphore = asyncio.Semaphore(3)

    async def limited(symbol: str):
        async with semaphore:
            return await fetch_symbol(exchange, symbol, start_ms, end_ms)

    try:
        pairs = await asyncio.gather(*(limited(symbol) for symbol in universe))
    finally:
        await exchange.close()
    data = dict(pairs)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"start_ms": start_ms, "end_ms": end_ms, "data": data}))
    return data


def backtest(data: dict[str, list[dict[str, float]]], params: Params, start_ms: int, end_ms: int,
             fee_rate: float, slippage_rate: float) -> dict[str, Any]:
    maps = {symbol: {int(row["ts"]): row for row in rows} for symbol, rows in data.items()}
    inds = {symbol: indicators(rows) for symbol, rows in data.items()}
    index = {symbol: {int(row["ts"]): i for i, row in enumerate(rows)} for symbol, rows in data.items()}
    timeline = sorted({ts for symbol_map in maps.values() for ts in symbol_map if start_ms <= ts <= end_ms})
    equity = 1000.0
    peak = equity
    max_dd = 0.0
    trades: list[float] = []
    position: dict[str, float] | None = None
    pending: str | None = None
    total_cost = fee_rate + slippage_rate

    for ts in timeline:
        if position:
            symbol = str(position["symbol"])
            row = maps[symbol].get(ts)
            if row:
                i = index[symbol][ts]
                atr = inds[symbol]["atr"][i]
                if row["high"] > position["best"]:
                    position["best"] = row["high"]
                    position["stop"] = max(position["stop"], row["high"] - params.trailing_atr * atr)
                exit_px = 0.0
                if row["low"] <= position["stop"]:
                    exit_px = position["stop"]
                elif row["high"] >= position["take"]:
                    exit_px = position["take"]
                if exit_px:
                    qty = position["qty"]
                    gross = (exit_px - position["entry"]) * qty
                    exit_cost = exit_px * qty * total_cost
                    net = gross - position["entry_cost"] - exit_cost
                    equity += net
                    trades.append(net)
                    position = None
        if pending and not position:
            row = maps[pending].get(ts)
            if row:
                i = index[pending][ts]
                entry = row["open"] * (1 + slippage_rate)
                atr = inds[pending]["atr"][i]
                risk = params.stop_atr * atr
                notional = equity * params.position_fraction * params.leverage
                qty = notional / entry if entry > 0 else 0
                if qty > 0 and risk > 0:
                    position = {"symbol": pending, "entry": entry, "qty": qty, "stop": entry - risk,
                                "take": entry + params.take_r * risk, "best": entry,
                                "entry_cost": entry * qty * fee_rate}
            pending = None
        if not position and not pending and ts % (4 * 3_600_000) == 0:
            candidates = []
            for symbol, symbol_map in maps.items():
                row = symbol_map.get(ts)
                i = index[symbol].get(ts)
                rows = data[symbol]
                if not row or i is None or i < 55:
                    continue
                prior = rows[i - 24]["close"]
                momentum = (row["close"] / prior - 1) * 100 if prior > 0 else -999
                ind = inds[symbol]
                trend = row["close"] > ind["ema21"][i] > ind["ema55"][i] and ind["ema9"][i] > ind["ema21"][i]
                if trend and momentum >= params.min_momentum_pct and 48 <= ind["rsi"][i] <= params.max_rsi:
                    candidates.append((momentum, row["volume"], symbol))
            if candidates:
                pending = max(candidates)[2]
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0)

    if position:
        symbol = str(position["symbol"])
        available = [ts for ts in timeline if ts in maps[symbol]]
        if available:
            exit_px = maps[symbol][available[-1]]["close"] * (1 - slippage_rate)
            qty = position["qty"]
            net = (exit_px - position["entry"]) * qty - position["entry_cost"] - exit_px * qty * fee_rate
            equity += net
            trades.append(net)
    wins = [pnl for pnl in trades if pnl > 0]
    losses = [pnl for pnl in trades if pnl < 0]
    profit_factor = sum(wins) / abs(sum(losses)) if losses else (math.inf if wins else 0.0)
    return {"return_pct": (equity / 1000 - 1) * 100, "final_equity": equity, "max_drawdown_pct": max_dd,
            "trades": len(trades), "win_rate_pct": len(wins) / len(trades) * 100 if trades else 0,
            "profit_factor": profit_factor}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument("--fee", type=float, default=0.0005)
    parser.add_argument("--slippage", type=float, default=0.0003)
    parser.add_argument("--output", type=Path, default=ROOT / ".run/research/return_first_result.json")
    args = parser.parse_args()
    cache = ROOT / ".run/research/okx_1h_majors.json"
    data = await load_data(DEFAULT_UNIVERSE, args.days, cache)
    common_end = min(int(rows[-1]["ts"]) for rows in data.values() if rows)
    common_start = max(int(rows[0]["ts"]) for rows in data.values() if rows)
    split = common_end - args.test_days * 86_400_000
    grid = [Params(*values) for values in itertools.product(
        [2.0, 3.0, 5.0], [0.5, 0.8], [1.5, 2.0], [2.0, 3.0], [1.5, 2.0], [0.0, 2.0], [68.0, 75.0]
    )]
    ranked = []
    for params in grid:
        metrics = backtest(data, params, common_start, split - 1, args.fee, args.slippage)
        score = metrics["return_pct"] - max(0.0, metrics["max_drawdown_pct"] - 25) * 2
        ranked.append((score, metrics, params))
    ranked.sort(key=lambda item: item[0], reverse=True)
    finalists = []
    for score, train, params in ranked[:10]:
        test = backtest(data, params, split, common_end, args.fee, args.slippage)
        finalists.append({"params": asdict(params), "train": train, "test": test, "train_score": score})
    finalists.sort(key=lambda item: item["test"]["return_pct"], reverse=True)
    result = {
        "method": "dynamic cross-sectional rank, next-bar execution, train/test split",
        "universe": DEFAULT_UNIVERSE, "fee_rate": args.fee, "slippage_rate": args.slippage,
        "train": [datetime.fromtimestamp(common_start / 1000, timezone.utc).isoformat(), datetime.fromtimestamp(split / 1000, timezone.utc).isoformat()],
        "test": [datetime.fromtimestamp(split / 1000, timezone.utc).isoformat(), datetime.fromtimestamp(common_end / 1000, timezone.utc).isoformat()],
        "finalists": finalists,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
