#!/usr/bin/env python3
"""15-minute cross-sectional factor research for high-risk intraday trading."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

import httpx

from return_first_walkforward import ROOT


SYMBOLS = [
    "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP",
    "XRP-USDT-SWAP", "DOGE-USDT-SWAP", "ADA-USDT-SWAP",
]
BAR_MS = 15 * 60_000
DAY_MS = 86_400_000


def pct(rows: list[dict], i: int, bars: int) -> float:
    return rows[i]["close"] / rows[i - bars]["close"] - 1


def volatility(rows: list[dict], i: int, bars: int) -> float:
    values = [rows[j]["close"] / rows[j - 1]["close"] - 1
              for j in range(i - bars + 1, i + 1)]
    return statistics.pstdev(values)


def factors(rows: list[dict], i: int) -> dict[str, float]:
    prior = rows[i - 16:i]
    return {
        "momentum_1h": pct(rows, i, 4),
        "momentum_4h": pct(rows, i, 16),
        "momentum_12h": pct(rows, i, 48),
        "momentum_24h": pct(rows, i, 96),
        "reversal_15m": -pct(rows, i, 1),
        "reversal_1h": -pct(rows, i, 4),
        "low_volatility_4h": -volatility(rows, i, 16),
        "volume_surprise_4h": rows[i]["volume"] / max(
            statistics.mean(row["volume"] for row in prior), 1e-12
        ),
        "breakout_4h": rows[i]["close"] / max(row["high"] for row in prior) - 1,
        "range_position_4h": (
            (rows[i]["close"] - min(row["low"] for row in prior)) /
            max(max(row["high"] for row in prior) - min(row["low"] for row in prior), 1e-12)
        ),
    }


async def fetch_symbol(client: httpx.AsyncClient, symbol: str, start: int, end: int) -> tuple[str, list[dict]]:
    cursor = end + 1
    output: dict[int, dict] = {}
    while cursor > start:
        response = await client.get("https://www.okx.com/api/v5/market/history-candles", params={
            "instId": symbol, "bar": "15m", "limit": "100", "after": str(cursor),
        })
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "0" or not payload.get("data"):
            break
        oldest = cursor
        for row in payload["data"]:
            ts = int(row[0])
            oldest = min(oldest, ts)
            if start <= ts <= end and row[8] == "1":
                output[ts] = {
                    "ts": ts, "open": float(row[1]), "high": float(row[2]),
                    "low": float(row[3]), "close": float(row[4]),
                    "volume": float(row[7] or row[5] or 0),
                }
        if oldest >= cursor or oldest < start:
            break
        cursor = oldest
        await asyncio.sleep(0.02)
    return symbol, [output[key] for key in sorted(output)]


async def load(days: int, cache: Path) -> dict[str, list[dict]]:
    end = int(datetime.now(timezone.utc).timestamp() * 1000)
    start = end - days * DAY_MS
    if cache.exists():
        saved = json.loads(cache.read_text())
        if saved.get("start", end) <= start and saved.get("end", 0) >= end - BAR_MS:
            return saved["data"]
    limits = asyncio.Semaphore(3)
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        async def one(symbol: str):
            async with limits:
                return await fetch_symbol(client, symbol, start, end)
        pairs = await asyncio.gather(*(one(symbol) for symbol in SYMBOLS))
    data = dict(pairs)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"start": start, "end": end, "data": data}))
    return data


def rank_correlation(left: list[float], right: list[float]) -> float:
    def ranks(values: list[float]) -> list[int]:
        order = sorted(range(len(values)), key=values.__getitem__)
        result = [0] * len(values)
        for place, index in enumerate(order):
            result[index] = place
        return result
    a, b = ranks(left), ranks(right)
    am, bm = statistics.mean(a), statistics.mean(b)
    numerator = sum((x - am) * (y - bm) for x, y in zip(a, b))
    denominator = math.sqrt(sum((x - am) ** 2 for x in a) * sum((y - bm) ** 2 for y in b))
    return numerator / denominator if denominator else 0.0


def build_periods(data: dict[str, list[dict]], start: int, end: int, hold_bars: int) -> list[dict]:
    maps = {symbol: {row["ts"]: i for i, row in enumerate(rows)} for symbol, rows in data.items()}
    timeline = sorted(set.intersection(*(set(values) for values in maps.values())))
    periods = []
    for ts in timeline:
        if not start <= ts <= end or (ts // BAR_MS) % hold_bars:
            continue
        cross_section = []
        for symbol, rows in data.items():
            i = maps[symbol][ts]
            if i < 96 or i + hold_bars >= len(rows):
                break
            # The factor is known only after bar i closes. Enter at the next
            # confirmed bar's open instead of unrealistically filling at the
            # signal bar close.
            entry = rows[i + 1]["open"]
            cross_section.append({
                "symbol": symbol,
                "factors": factors(rows, i),
                "forward": rows[i + hold_bars]["close"] / entry - 1,
            })
        if len(cross_section) == len(data):
            periods.append({"ts": ts, "rows": cross_section})
    return periods


def evaluate(periods: list[dict], name: str, direction: int, leverage: float, cost: float) -> dict:
    equity = peak = 1.0
    max_dd = 0.0
    returns, ics = [], []
    for period in periods:
        values = [direction * row["factors"][name] for row in period["rows"]]
        forward = [row["forward"] for row in period["rows"]]
        order = sorted(range(len(values)), key=values.__getitem__)
        gross = 0.5 * (forward[order[-1]] - forward[order[0]])
        value = leverage * (gross - cost)
        returns.append(value)
        ics.append(rank_correlation(values, forward))
        equity *= max(0, 1 + value)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)
    return {
        "periods": len(periods), "return_pct": (equity - 1) * 100,
        "max_drawdown_pct": max_dd,
        "mean_period_pct": statistics.mean(returns) * 100 if returns else 0,
        "mean_ic": statistics.mean(ics) if ics else 0,
        "positive_pct": sum(value > 0 for value in returns) / len(returns) * 100 if returns else 0,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--leverage", type=float, default=1)
    parser.add_argument("--roundtrip-cost", type=float, default=0.0008)
    parser.add_argument("--cache", type=Path, default=ROOT / ".run/research/okx_15m_intraday_120d.json")
    parser.add_argument("--output", type=Path, default=ROOT / ".run/research/intraday_factor_result.json")
    args = parser.parse_args()
    data = await load(args.days, args.cache)
    common_start = max(rows[0]["ts"] for rows in data.values())
    common_end = min(rows[-1]["ts"] for rows in data.values())
    split = common_end - 30 * DAY_MS
    result = {"symbols": list(data), "cost": args.roundtrip_cost, "leverage": args.leverage, "holds": {}}
    for hold in (4, 8, 16, 32):
        train = build_periods(data, common_start, split - 1, hold)
        test = build_periods(data, split, common_end, hold)
        names = list(train[0]["rows"][0]["factors"]) if train else []
        outcomes = {}
        for name in names:
            raw = evaluate(train, name, 1, args.leverage, args.roundtrip_cost)
            direction = 1 if raw["mean_ic"] >= 0 else -1
            outcomes[name] = {
                "direction": direction,
                "train": evaluate(train, name, direction, args.leverage, args.roundtrip_cost),
                "test": evaluate(test, name, direction, args.leverage, args.roundtrip_cost),
            }
        result["holds"][str(hold)] = {"hours": hold / 4, "factors": outcomes}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({symbol: len(rows) for symbol, rows in data.items()}))
    for hold, item in result["holds"].items():
        good = [(name, value) for name, value in item["factors"].items()
                if value["train"]["return_pct"] > 0 and value["test"]["return_pct"] > 0]
        print(hold, [(name, round(value["train"]["return_pct"], 2),
                      round(value["test"]["return_pct"], 2), value["direction"]) for name, value in good])


if __name__ == "__main__":
    asyncio.run(main())
