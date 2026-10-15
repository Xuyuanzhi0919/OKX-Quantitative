#!/usr/bin/env python3
"""No-lookahead OKX spot/perpetual funding-and-basis walk-forward research."""
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

from return_first_walkforward import ROOT, load_data
from app.services.exchange.okx import OKXExchange


BASES = ["BTC", "ETH", "SOL"]


@dataclass(frozen=True)
class Params:
    leverage: float
    utilization: float
    min_funding_rate: float
    min_basis: float
    exit_funding_rate: float
    max_hold_hours: int


async def load_funding(days: int, cache_path: Path) -> dict[str, list[dict[str, float]]]:
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - days * 86_400_000
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if cached.get("start_ms", 0) <= start_ms and cached.get("end_ms", 0) >= end_ms - 28_800_000:
            return cached["data"]
    exchange = OKXExchange(api_key="", secret_key="", passphrase="", simulated=False)
    output: dict[str, list[dict[str, float]]] = {}
    try:
        for base in BASES:
            symbol = f"{base}-USDT-SWAP"
            cursor = end_ms + 1
            records: dict[int, float] = {}
            while cursor > start_ms:
                response = await exchange._request(
                    "GET", "/api/v5/public/funding-rate-history",
                    params={"instId": symbol, "limit": "100", "after": str(cursor)}, auth_required=False,
                )
                batch = response.get("data", [])
                if not batch:
                    break
                oldest = cursor
                for item in batch:
                    ts = int(item["fundingTime"])
                    oldest = min(oldest, ts)
                    if start_ms <= ts <= end_ms:
                        records[ts] = float(item.get("realizedRate") or item.get("fundingRate") or 0)
                if oldest >= cursor or oldest < start_ms:
                    break
                cursor = oldest
                await asyncio.sleep(0.05)
            output[base] = [{"ts": ts, "rate": records[ts]} for ts in sorted(records)]
    finally:
        await exchange.close()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"start_ms": start_ms, "end_ms": end_ms, "data": output}))
    return output


def backtest(candles: dict[str, list[dict[str, float]]], funding: dict[str, list[dict[str, float]]],
             params: Params, start_ms: int, end_ms: int, fee: float, slippage: float) -> dict[str, Any]:
    spot_maps = {base: {int(row["ts"]): row for row in candles[f"{base}-USDT"]} for base in BASES}
    perp_maps = {base: {int(row["ts"]): row for row in candles[f"{base}-USDT-SWAP"]} for base in BASES}
    funding_maps = {base: {int(row["ts"]): row["rate"] for row in funding[base]} for base in BASES}
    timeline = sorted(set.intersection(*[
        set(spot_maps[base]) & set(perp_maps[base]) for base in BASES
    ]))
    timeline = [ts for ts in timeline if start_ms <= ts <= end_ms]
    equity = 1000.0
    peak = equity
    max_dd = 0.0
    last_rate = {base: 0.0 for base in BASES}
    position: dict[str, Any] | None = None
    trades: list[float] = []
    funding_income = 0.0
    trading_cost = 0.0
    basis_pnl_total = 0.0

    for ts in timeline:
        for base in BASES:
            if ts in funding_maps[base]:
                last_rate[base] = funding_maps[base][ts]
                if position and position["base"] == base:
                    perp_px = perp_maps[base][ts]["close"]
                    income = position["qty"] * perp_px * last_rate[base]
                    equity += income
                    funding_income += income
                    position["funding_accrued"] += income

        if position:
            base = position["base"]
            spot = spot_maps[base][ts]["close"]
            perp = perp_maps[base][ts]["close"]
            edge = (perp - spot) / spot
            position["hours"] += 1
            should_exit = last_rate[base] <= params.exit_funding_rate or position["hours"] >= params.max_hold_hours
            if should_exit:
                spot_exit = spot * (1 - slippage)
                perp_exit = perp * (1 + slippage)
                spot_pnl = (spot_exit - position["spot_entry"]) * position["qty"]
                perp_pnl = (position["perp_entry"] - perp_exit) * position["qty"]
                close_fee = (spot_exit + perp_exit) * position["qty"] * fee
                net = spot_pnl + perp_pnl - position["open_cost"] - close_fee
                equity += net
                trading_cost += position["open_cost"] + close_fee
                basis_pnl_total += spot_pnl + perp_pnl
                trades.append(net + position["funding_accrued"])
                position = None

        if not position:
            choices = []
            for base in BASES:
                spot = spot_maps[base][ts]["close"]
                perp = perp_maps[base][ts]["close"]
                basis = (perp - spot) / spot
                if last_rate[base] >= params.min_funding_rate and basis >= params.min_basis:
                    choices.append((last_rate[base] + basis / 30, base, basis))
            if choices:
                _, base, basis = max(choices)
                spot = spot_maps[base][ts]["close"] * (1 + slippage)
                perp = perp_maps[base][ts]["close"] * (1 - slippage)
                max_notional = equity * params.utilization / (1 + 1 / params.leverage)
                qty = max_notional / spot
                open_cost = (spot + perp) * qty * fee
                position = {
                    "base": base, "qty": qty, "spot_entry": spot, "perp_entry": perp,
                    "open_cost": open_cost, "hours": 0, "entry_basis": basis,
                    "funding_accrued": 0.0,
                }

        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0)

    if position and timeline:
        base = position["base"]
        ts = timeline[-1]
        spot = spot_maps[base][ts]["close"] * (1 - slippage)
        perp = perp_maps[base][ts]["close"] * (1 + slippage)
        spot_pnl = (spot - position["spot_entry"]) * position["qty"]
        perp_pnl = (position["perp_entry"] - perp) * position["qty"]
        close_fee = (spot + perp) * position["qty"] * fee
        net = spot_pnl + perp_pnl - position["open_cost"] - close_fee
        equity += net
        trading_cost += position["open_cost"] + close_fee
        basis_pnl_total += spot_pnl + perp_pnl
        trades.append(net + position["funding_accrued"])

    wins = [value for value in trades if value > 0]
    losses = [value for value in trades if value < 0]
    return {
        "return_pct": (equity / 1000 - 1) * 100,
        "final_equity": equity,
        "max_drawdown_pct": max_dd,
        "trades": len(trades),
        "win_rate_pct": len(wins) / len(trades) * 100 if trades else 0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else (math.inf if wins else 0),
        "funding_income": funding_income,
        "basis_pnl": basis_pnl_total,
        "trading_cost": trading_cost,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument("--fee", type=float, default=0.0005)
    parser.add_argument("--slippage", type=float, default=0.0002)
    parser.add_argument("--output", type=Path, default=ROOT / ".run/research/funding_basis_result.json")
    args = parser.parse_args()
    symbols = list(itertools.chain.from_iterable((f"{base}-USDT", f"{base}-USDT-SWAP") for base in BASES))
    candles = await load_data(symbols, args.days, ROOT / ".run/research/okx_1h_basis.json")
    funding = await load_funding(args.days, ROOT / ".run/research/okx_funding.json")
    common_start = max(int(rows[0]["ts"]) for rows in candles.values() if rows)
    common_end = min(int(rows[-1]["ts"]) for rows in candles.values() if rows)
    split = common_end - args.test_days * 86_400_000
    grid = [Params(*values) for values in itertools.product(
        [1.0, 2.0, 3.0], [0.7, 0.9], [0.0, 0.00005, 0.0001],
        [-0.001, 0.0, 0.001], [-0.00005, 0.0], [72, 168, 336],
    )]
    ranked = []
    for params in grid:
        train = backtest(candles, funding, params, common_start, split - 1, args.fee, args.slippage)
        score = (
            train["return_pct"] - max(0.0, train["max_drawdown_pct"] - 15) * 2
            if train["trades"] > 0 else -math.inf
        )
        ranked.append((score, train, params))
    ranked.sort(key=lambda item: item[0], reverse=True)
    finalists = []
    for score, train, params in ranked[:12]:
        test = backtest(candles, funding, params, split, common_end, args.fee, args.slippage)
        finalists.append({"params": asdict(params), "train": train, "test": test, "train_score": score})
    finalists.sort(key=lambda item: item["test"]["return_pct"], reverse=True)
    result = {
        "method": "spot long + perp short; observed funding only; four-leg costs; holdout test",
        "fee_rate": args.fee, "slippage_rate": args.slippage,
        "train": [datetime.fromtimestamp(common_start / 1000, timezone.utc).isoformat(), datetime.fromtimestamp(split / 1000, timezone.utc).isoformat()],
        "test": [datetime.fromtimestamp(split / 1000, timezone.utc).isoformat(), datetime.fromtimestamp(common_end / 1000, timezone.utc).isoformat()],
        "finalists": finalists,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
