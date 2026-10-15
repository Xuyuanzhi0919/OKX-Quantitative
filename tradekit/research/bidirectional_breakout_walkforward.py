#!/usr/bin/env python3
"""Walk-forward research for a return-first bidirectional breakout strategy."""
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

from return_first_walkforward import DEFAULT_UNIVERSE, ROOT, ema, load_data


@dataclass(frozen=True)
class Params:
    leverage: float
    position_fraction: float
    breakout_bars: int
    regime_ema: int
    stop_atr: float
    take_r: float
    trailing_atr: float
    max_hold_bars: int


def prepare(rows: list[dict[str, float]], params: Params) -> dict[str, list[float]]:
    close = [row["close"] for row in rows]
    high = [row["high"] for row in rows]
    low = [row["low"] for row in rows]
    tr = []
    for i in range(len(rows)):
        tr.append(high[i] - low[i] if i == 0 else max(
            high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])
        ))
    upper = [math.nan] * len(rows)
    lower = [math.nan] * len(rows)
    for i in range(params.breakout_bars, len(rows)):
        upper[i] = max(high[i - params.breakout_bars:i])
        lower[i] = min(low[i - params.breakout_bars:i])
    return {"regime": ema(close, params.regime_ema), "atr": ema(tr, 14), "upper": upper, "lower": lower}


def run(data: dict[str, list[dict[str, float]]], params: Params, start_ms: int, end_ms: int,
        fee_rate: float, slippage_rate: float) -> dict[str, Any]:
    maps = {symbol: {int(row["ts"]): row for row in rows} for symbol, rows in data.items()}
    indexes = {symbol: {int(row["ts"]): i for i, row in enumerate(rows)} for symbol, rows in data.items()}
    metrics = {symbol: prepare(rows, params) for symbol, rows in data.items()}
    timeline = sorted({ts for values in maps.values() for ts in values if start_ms <= ts <= end_ms})
    equity = 1000.0
    peak = equity
    max_dd = 0.0
    trade_pnls: list[float] = []
    long_pnls: list[float] = []
    short_pnls: list[float] = []
    position: dict[str, Any] | None = None
    pending: tuple[str, str] | None = None

    def close_position(exit_px: float) -> None:
        nonlocal equity, position
        assert position is not None
        qty = float(position["qty"])
        direction = str(position["direction"])
        gross = (exit_px - position["entry"]) * qty if direction == "long" else (position["entry"] - exit_px) * qty
        net = gross - position["entry_fee"] - exit_px * qty * fee_rate
        equity += net
        trade_pnls.append(net)
        (long_pnls if direction == "long" else short_pnls).append(net)
        position = None

    for ts in timeline:
        if position:
            symbol = position["symbol"]
            row = maps[symbol].get(ts)
            if row:
                i = indexes[symbol][ts]
                atr = metrics[symbol]["atr"][i]
                position["bars"] += 1
                exit_px = None
                if position["direction"] == "long":
                    position["best"] = max(position["best"], row["high"])
                    position["stop"] = max(position["stop"], position["best"] - params.trailing_atr * atr)
                    if row["low"] <= position["stop"]:
                        exit_px = position["stop"] * (1 - slippage_rate)
                    elif row["high"] >= position["take"]:
                        exit_px = position["take"] * (1 - slippage_rate)
                else:
                    position["best"] = min(position["best"], row["low"])
                    position["stop"] = min(position["stop"], position["best"] + params.trailing_atr * atr)
                    if row["high"] >= position["stop"]:
                        exit_px = position["stop"] * (1 + slippage_rate)
                    elif row["low"] <= position["take"]:
                        exit_px = position["take"] * (1 + slippage_rate)
                if exit_px is None and position["bars"] >= params.max_hold_bars:
                    exit_px = row["close"] * (1 - slippage_rate if position["direction"] == "long" else 1 + slippage_rate)
                if exit_px is not None:
                    close_position(exit_px)

        if pending and not position:
            symbol, direction = pending
            row = maps[symbol].get(ts)
            if row:
                i = indexes[symbol][ts]
                atr = metrics[symbol]["atr"][i]
                entry = row["open"] * (1 + slippage_rate if direction == "long" else 1 - slippage_rate)
                distance = params.stop_atr * atr
                notional = equity * params.position_fraction * params.leverage
                qty = notional / entry if entry > 0 else 0
                if qty > 0 and distance > 0:
                    position = {
                        "symbol": symbol, "direction": direction, "entry": entry, "qty": qty,
                        "stop": entry - distance if direction == "long" else entry + distance,
                        "take": entry + params.take_r * distance if direction == "long" else entry - params.take_r * distance,
                        "best": entry, "bars": 0, "entry_fee": entry * qty * fee_rate,
                    }
            pending = None

        if not position and not pending:
            candidates: list[tuple[float, str, str]] = []
            warmup = max(params.regime_ema, params.breakout_bars, 24)
            for symbol, symbol_map in maps.items():
                row = symbol_map.get(ts)
                i = indexes[symbol].get(ts)
                if not row or i is None or i < warmup:
                    continue
                m = metrics[symbol]
                atr = m["atr"][i]
                if atr <= 0:
                    continue
                close = row["close"]
                momentum = (close / data[symbol][i - 24]["close"] - 1) * 100
                if close > m["upper"][i] and close > m["regime"][i]:
                    candidates.append((abs(momentum), symbol, "long"))
                elif close < m["lower"][i] and close < m["regime"][i]:
                    candidates.append((abs(momentum), symbol, "short"))
            if candidates:
                _, symbol, direction = max(candidates)
                pending = (symbol, direction)

        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak > 0 else 0)

    if position:
        symbol = position["symbol"]
        available = [ts for ts in timeline if ts in maps[symbol]]
        if available:
            close = maps[symbol][available[-1]]["close"]
            close_position(close * (1 - slippage_rate if position["direction"] == "long" else 1 + slippage_rate))

    wins = [pnl for pnl in trade_pnls if pnl > 0]
    losses = [pnl for pnl in trade_pnls if pnl < 0]
    return {
        "return_pct": (equity / 1000 - 1) * 100,
        "final_equity": equity,
        "max_drawdown_pct": max_dd,
        "trades": len(trade_pnls),
        "long_trades": len(long_pnls),
        "short_trades": len(short_pnls),
        "win_rate_pct": len(wins) / len(trade_pnls) * 100 if trade_pnls else 0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else (math.inf if wins else 0),
        "long_pnl": sum(long_pnls),
        "short_pnl": sum(short_pnls),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument("--fee", type=float, default=0.0005)
    parser.add_argument("--slippage", type=float, default=0.0003)
    parser.add_argument("--output", type=Path, default=ROOT / ".run/research/bidirectional_breakout_result.json")
    args = parser.parse_args()
    data = await load_data(DEFAULT_UNIVERSE, args.days, ROOT / ".run/research/okx_1h_majors.json")
    common_start = max(int(rows[0]["ts"]) for rows in data.values() if rows)
    common_end = min(int(rows[-1]["ts"]) for rows in data.values() if rows)
    split = common_end - args.test_days * 86_400_000
    grid = [Params(*values) for values in itertools.product(
        [2.0, 3.0], [0.5, 0.8], [12, 24, 48], [55, 100],
        [1.5, 2.0], [2.0, 3.0], [1.5, 2.0], [48, 96],
    )]
    ranked = []
    for params in grid:
        train = run(data, params, common_start, split - 1, args.fee, args.slippage)
        score = train["return_pct"] - max(0.0, train["max_drawdown_pct"] - 30) * 2
        ranked.append((score, train, params))
    ranked.sort(key=lambda item: item[0], reverse=True)
    finalists = []
    for score, train, params in ranked[:12]:
        test = run(data, params, split, common_end, args.fee, args.slippage)
        finalists.append({"params": asdict(params), "train": train, "test": test, "train_score": score})
    finalists.sort(key=lambda item: item["test"]["return_pct"], reverse=True)
    result = {
        "method": "bidirectional Donchian breakout, EMA regime, next-bar execution, walk-forward holdout",
        "fee_rate": args.fee, "slippage_rate": args.slippage, "universe": DEFAULT_UNIVERSE,
        "train": [datetime.fromtimestamp(common_start / 1000, timezone.utc).isoformat(), datetime.fromtimestamp(split / 1000, timezone.utc).isoformat()],
        "test": [datetime.fromtimestamp(split / 1000, timezone.utc).isoformat(), datetime.fromtimestamp(common_end / 1000, timezone.utc).isoformat()],
        "finalists": finalists,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
