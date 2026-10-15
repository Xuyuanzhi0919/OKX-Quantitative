#!/usr/bin/env python3
"""Walk-forward OI + funding crowding/squeeze event research for OKX swaps."""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from funding_basis_walkforward import BASES, load_funding
from return_first_walkforward import ROOT, ema, load_data
from app.services.exchange.okx import OKXExchange


@dataclass(frozen=True)
class Params:
    mode: str
    leverage: float
    utilization: float
    oi_change_pct: float
    funding_threshold: float
    price_move_pct: float
    stop_atr: float
    take_r: float
    max_hold_hours: int


async def load_oi(days: int, cache_path: Path) -> dict[str, list[dict[str, float]]]:
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - days * 86_400_000
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if cached.get("start_ms", 0) <= start_ms and cached.get("end_ms", 0) >= end_ms - 3_600_000:
            return cached["data"]
    exchange = OKXExchange(api_key="", secret_key="", passphrase="", simulated=False)
    output: dict[str, list[dict[str, float]]] = {}
    try:
        for base in BASES:
            symbol = f"{base}-USDT-SWAP"
            cursor = end_ms + 1
            records: dict[int, float] = {}
            while cursor > start_ms:
                begin = max(start_ms, cursor - 99 * 3_600_000)
                response = await exchange._request(
                    "GET", "/api/v5/rubik/stat/contracts/open-interest-history",
                    params={
                        "instId": symbol, "period": "1H", "limit": "100",
                        "begin": str(begin), "end": str(cursor),
                    },
                    auth_required=False,
                )
                batch = response.get("data", [])
                if not batch:
                    break
                oldest = cursor
                for item in batch:
                    ts = int(item[0])
                    oldest = min(oldest, ts)
                    if start_ms <= ts <= end_ms:
                        records[ts] = float(item[3])  # open interest in USD
                if oldest >= cursor or begin <= start_ms:
                    break
                cursor = oldest - 1
                await asyncio.sleep(0.05)
            output[base] = [{"ts": ts, "oi_usd": records[ts]} for ts in sorted(records)]
    finally:
        await exchange.close()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"start_ms": start_ms, "end_ms": end_ms, "data": output}))
    return output


def atr(rows: list[dict[str, float]]) -> list[float]:
    values = []
    for i, row in enumerate(rows):
        values.append(row["high"] - row["low"] if i == 0 else max(
            row["high"] - row["low"], abs(row["high"] - rows[i - 1]["close"]),
            abs(row["low"] - rows[i - 1]["close"]),
        ))
    return ema(values, 14)


def backtest(candles: dict[str, list[dict[str, float]]], funding: dict[str, list[dict[str, float]]],
             oi: dict[str, list[dict[str, float]]], params: Params, start_ms: int, end_ms: int,
             fee: float, slippage: float) -> dict[str, Any]:
    maps = {base: {int(row["ts"]): row for row in candles[f"{base}-USDT-SWAP"]} for base in BASES}
    indexes = {base: {int(row["ts"]): i for i, row in enumerate(candles[f"{base}-USDT-SWAP"])} for base in BASES}
    atrs = {base: atr(candles[f"{base}-USDT-SWAP"]) for base in BASES}
    oi_maps = {base: {int(row["ts"]): row["oi_usd"] for row in oi[base]} for base in BASES}
    funding_maps = {base: {int(row["ts"]): row["rate"] for row in funding[base]} for base in BASES}
    timeline = sorted(set.intersection(*[set(maps[base]) & set(oi_maps[base]) for base in BASES]))
    timeline = [ts for ts in timeline if start_ms <= ts <= end_ms]
    equity = 1000.0
    peak = equity
    max_dd = 0.0
    last_rate = {base: 0.0 for base in BASES}
    position: dict[str, Any] | None = None
    pending: tuple[str, str] | None = None
    pnls: list[float] = []
    long_pnls: list[float] = []
    short_pnls: list[float] = []
    costs = 0.0

    for ts in timeline:
        for base in BASES:
            if ts in funding_maps[base]:
                last_rate[base] = funding_maps[base][ts]
        if position:
            base = position["base"]
            row = maps[base][ts]
            i = indexes[base][ts]
            position["hours"] += 1
            exit_px = None
            if position["direction"] == "long":
                if row["low"] <= position["stop"]:
                    exit_px = position["stop"] * (1 - slippage)
                elif row["high"] >= position["take"]:
                    exit_px = position["take"] * (1 - slippage)
            else:
                if row["high"] >= position["stop"]:
                    exit_px = position["stop"] * (1 + slippage)
                elif row["low"] <= position["take"]:
                    exit_px = position["take"] * (1 + slippage)
            if exit_px is None and position["hours"] >= params.max_hold_hours:
                exit_px = row["close"] * (1 - slippage if position["direction"] == "long" else 1 + slippage)
            if exit_px is not None:
                gross = ((exit_px - position["entry"]) if position["direction"] == "long" else
                         (position["entry"] - exit_px)) * position["qty"]
                exit_fee = exit_px * position["qty"] * fee
                net = gross - position["entry_fee"] - exit_fee
                equity += net
                costs += position["entry_fee"] + exit_fee
                pnls.append(net)
                (long_pnls if position["direction"] == "long" else short_pnls).append(net)
                position = None

        if pending and not position:
            base, direction = pending
            row = maps[base][ts]
            i = indexes[base][ts]
            entry = row["open"] * (1 + slippage if direction == "long" else 1 - slippage)
            distance = params.stop_atr * atrs[base][i]
            qty = equity * params.utilization * params.leverage / entry
            if qty > 0 and distance > 0:
                position = {
                    "base": base, "direction": direction, "entry": entry, "qty": qty,
                    "stop": entry - distance if direction == "long" else entry + distance,
                    "take": entry + params.take_r * distance if direction == "long" else entry - params.take_r * distance,
                    "entry_fee": entry * qty * fee, "hours": 0,
                }
            pending = None

        if not position and not pending:
            candidates = []
            for base in BASES:
                i = indexes[base].get(ts)
                if i is None or i < 24:
                    continue
                row = maps[base][ts]
                prev = candles[f"{base}-USDT-SWAP"][i - 24]
                prev_hour = candles[f"{base}-USDT-SWAP"][i - 1]
                old_ts = int(prev["ts"])
                old_oi = oi_maps[base].get(old_ts)
                if not old_oi:
                    continue
                oi_change = (oi_maps[base][ts] / old_oi - 1) * 100
                price_change = (row["close"] / prev["close"] - 1) * 100
                direction = None
                if oi_change >= params.oi_change_pct:
                    if params.mode == "crowded_reversal":
                        if last_rate[base] >= params.funding_threshold and price_change >= params.price_move_pct and row["close"] < prev_hour["close"]:
                            direction = "short"
                        elif last_rate[base] <= -params.funding_threshold and price_change <= -params.price_move_pct and row["close"] > prev_hour["close"]:
                            direction = "long"
                    else:  # squeeze continuation: price and funding disagree
                        if last_rate[base] <= -params.funding_threshold and price_change >= params.price_move_pct:
                            direction = "long"
                        elif last_rate[base] >= params.funding_threshold and price_change <= -params.price_move_pct:
                            direction = "short"
                if direction:
                    candidates.append((oi_change + abs(price_change), base, direction))
            if candidates:
                _, base, direction = max(candidates)
                pending = (base, direction)

        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0)

    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    return {
        "return_pct": (equity / 1000 - 1) * 100, "final_equity": equity,
        "max_drawdown_pct": max_dd, "trades": len(pnls),
        "win_rate_pct": len(wins) / len(pnls) * 100 if pnls else 0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else (math.inf if wins else 0),
        "long_trades": len(long_pnls), "short_trades": len(short_pnls),
        "long_pnl": sum(long_pnls), "short_pnl": sum(short_pnls), "trading_cost": costs,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument("--fee", type=float, default=0.0005)
    parser.add_argument("--slippage", type=float, default=0.0003)
    parser.add_argument("--output", type=Path, default=ROOT / ".run/research/oi_funding_event_result.json")
    args = parser.parse_args()
    symbols = [f"{base}-USDT-SWAP" for base in BASES]
    candles = await load_data(symbols, args.days, ROOT / ".run/research/okx_1h_oi_event.json")
    funding = await load_funding(args.days, ROOT / ".run/research/okx_funding.json")
    oi = await load_oi(args.days, ROOT / ".run/research/okx_oi_1h_v2.json")
    common_start = max(int(rows[0]["ts"]) for rows in candles.values() if rows)
    common_end = min(int(rows[-1]["ts"]) for rows in candles.values() if rows)
    split = common_end - args.test_days * 86_400_000
    grid = [Params(*values) for values in itertools.product(
        ["crowded_reversal", "squeeze_continuation"], [2.0, 3.0], [0.5, 0.8],
        [3.0, 5.0, 8.0], [0.00005, 0.0001], [2.0, 4.0],
        [1.5, 2.0], [2.0, 3.0], [24, 48],
    )]
    ranked = []
    for params in grid:
        train = backtest(candles, funding, oi, params, common_start, split - 1, args.fee, args.slippage)
        score = train["return_pct"] - max(0.0, train["max_drawdown_pct"] - 30) * 2 if train["trades"] >= 5 else -math.inf
        ranked.append((score, train, params))
    ranked.sort(key=lambda item: item[0], reverse=True)
    eligible = [item for item in ranked if math.isfinite(item[0])]
    all_holdouts = []
    for score, train, params in eligible:
        test = backtest(candles, funding, oi, params, split, common_end, args.fee, args.slippage)
        all_holdouts.append((score, train, test, params))
    finalists = []
    for score, train, test, params in all_holdouts[:16]:
        finalists.append({"params": asdict(params), "train": train, "test": test, "train_score": score})
    finalists.sort(key=lambda item: item["test"]["return_pct"], reverse=True)
    result = {
        "method": "OI expansion + funding crowding event; next-bar execution; holdout test",
        "fee_rate": args.fee, "slippage_rate": args.slippage,
        "train": [datetime.fromtimestamp(common_start / 1000, timezone.utc).isoformat(), datetime.fromtimestamp(split / 1000, timezone.utc).isoformat()],
        "test": [datetime.fromtimestamp(split / 1000, timezone.utc).isoformat(), datetime.fromtimestamp(common_end / 1000, timezone.utc).isoformat()],
        "robustness": {
            "eligible_parameter_sets": len(all_holdouts),
            "positive_train_and_test": sum(1 for _, train, test, _ in all_holdouts if train["return_pct"] > 0 and test["return_pct"] > 0),
            "positive_test_with_at_least_3_trades": sum(1 for _, _, test, _ in all_holdouts if test["return_pct"] > 0 and test["trades"] >= 3),
            "tested_holdout_sets": len(all_holdouts),
        },
        "finalists": finalists,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
