#!/usr/bin/env python3
"""Walk-forward test of strategies selected from the prior 24h gainers ranking."""
from __future__ import annotations

import argparse
import itertools
import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from return_first_walkforward import ROOT


DAY_MS = 86_400_000


@dataclass(frozen=True)
class Params:
    mode: str
    hold_hours: int
    top_n: int
    min_top_gain: float
    min_top_gap: float


def backtest(data: dict[str, list[dict]], params: Params, start: int, end: int,
             leverage: float, cost: float) -> dict:
    maps = {symbol: {int(row["ts"]): i for i, row in enumerate(rows)}
            for symbol, rows in data.items()}
    timeline = sorted(set.intersection(*(set(values) for values in maps.values())))
    equity = peak = 1.0
    max_dd = 0.0
    trades = []
    selections: dict[str, int] = {}
    for ts in timeline:
        if not start <= ts <= end or ts % DAY_MS:
            continue
        ranked = []
        for symbol, rows in data.items():
            i = maps[symbol][ts]
            if i < 24 or i + params.hold_hours >= len(rows):
                break
            momentum = rows[i]["close"] / rows[i - 24]["close"] - 1
            entry = rows[i + 1]["open"]
            forward = rows[i + params.hold_hours]["close"] / entry - 1
            ranked.append((momentum, symbol, forward))
        if len(ranked) != len(data):
            continue
        ranked.sort()
        top = ranked[-params.top_n:]
        bottom = ranked[:params.top_n]
        if ranked[-1][0] < params.min_top_gain:
            continue
        if ranked[-1][0] - ranked[-2][0] < params.min_top_gap:
            continue
        for _, symbol, _ in top:
            selections[symbol] = selections.get(symbol, 0) + 1
        if params.mode == "long_top":
            gross = statistics.mean(row[2] for row in top)
        elif params.mode == "short_top":
            gross = -statistics.mean(row[2] for row in top)
        elif params.mode == "long_top_short_bottom":
            gross = 0.5 * (statistics.mean(row[2] for row in top) -
                           statistics.mean(row[2] for row in bottom))
        else:
            raise ValueError(params.mode)
        value = leverage * (gross - cost)
        trades.append(value)
        equity *= max(0, 1 + value)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)
    return {
        "trades": len(trades), "return_pct": (equity - 1) * 100,
        "max_drawdown_pct": max_dd,
        "win_rate_pct": sum(value > 0 for value in trades) / len(trades) * 100 if trades else 0,
        "mean_trade_pct": statistics.mean(trades) * 100 if trades else 0,
        "worst_trade_pct": min(trades) * 100 if trades else 0,
        "best_trade_pct": max(trades) * 100 if trades else 0,
        "top_selections": selections,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=ROOT / ".run/research/okx_1h_majors_365d.json")
    parser.add_argument("--cost", type=float, default=0.0008)
    parser.add_argument("--leverage", type=float, default=1)
    parser.add_argument("--output", type=Path, default=ROOT / ".run/research/daily_gainers_result.json")
    args = parser.parse_args()
    data = json.loads(args.cache.read_text())["data"]
    start = max(int(rows[0]["ts"]) for rows in data.values())
    end = min(int(rows[-1]["ts"]) for rows in data.values())
    split = end - 60 * DAY_MS
    grid = [Params(*values) for values in itertools.product(
        ("long_top", "short_top", "long_top_short_bottom"),
        (4, 8, 12, 24), (1, 2), (0.0, 0.03, 0.05, 0.08, 0.12),
        (0.0, 0.01, 0.02, 0.03),
    )]
    results = []
    for params in grid:
        results.append({
            "params": asdict(params),
            "train": backtest(data, params, start, split - 1, args.leverage, args.cost),
            "test": backtest(data, params, split, end, args.leverage, args.cost),
        })
    results.sort(key=lambda row: row["train"]["return_pct"], reverse=True)
    args.output.write_text(json.dumps({"cost": args.cost, "leverage": args.leverage,
                                       "split_ts": split, "results": results},
                                      ensure_ascii=False, indent=2))
    for row in results:
        if row["train"]["return_pct"] > 0 or row["test"]["return_pct"] > 0:
            compact = {"params": row["params"],
                       "train": {key: value for key, value in row["train"].items() if key != "top_selections"},
                       "test": {key: value for key, value in row["test"].items() if key != "top_selections"}}
            print(json.dumps(compact, ensure_ascii=False))


if __name__ == "__main__":
    main()
