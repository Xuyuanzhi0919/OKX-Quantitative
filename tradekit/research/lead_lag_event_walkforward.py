#!/usr/bin/env python3
"""BTC shock -> altcoin basket lead/lag event research on 15-minute bars."""
from __future__ import annotations

import argparse
import itertools
import json
import statistics
from dataclasses import dataclass, asdict
from pathlib import Path

from intraday_factor_walkforward import BAR_MS, DAY_MS
from return_first_walkforward import ROOT


@dataclass(frozen=True)
class Params:
    shock_bars: int
    threshold: float
    hold_bars: int
    mode: str


def backtest(data: dict[str, list[dict]], params: Params, start: int, end: int,
             leverage: float, cost: float) -> dict:
    btc = data["BTC-USDT-SWAP"]
    btc_index = {row["ts"]: i for i, row in enumerate(btc)}
    alt_symbols = [symbol for symbol in data if symbol != "BTC-USDT-SWAP"]
    alt_maps = {symbol: {row["ts"]: i for i, row in enumerate(data[symbol])}
                for symbol in alt_symbols}
    equity = peak = 1.0
    max_dd = 0.0
    trades = []
    next_allowed = start
    for ts in sorted(btc_index):
        if not start <= ts <= end or ts < next_allowed:
            continue
        i = btc_index[ts]
        if i < params.shock_bars:
            continue
        shock = btc[i]["close"] / btc[i - params.shock_bars]["close"] - 1
        if abs(shock) < params.threshold:
            continue
        direction = 1 if shock > 0 else -1
        if params.mode == "reversal":
            direction *= -1
        returns = []
        for symbol in alt_symbols:
            rows = data[symbol]
            j = alt_maps[symbol].get(ts)
            if j is None or j + params.hold_bars >= len(rows):
                break
            entry = rows[j + 1]["open"]
            exit_price = rows[j + params.hold_bars]["close"]
            returns.append(direction * (exit_price / entry - 1))
        if len(returns) != len(alt_symbols):
            continue
        value = leverage * (statistics.mean(returns) - cost)
        trades.append(value)
        equity *= max(0, 1 + value)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)
        next_allowed = ts + params.hold_bars * BAR_MS
    return {
        "trades": len(trades), "return_pct": (equity - 1) * 100,
        "max_drawdown_pct": max_dd,
        "win_rate_pct": sum(value > 0 for value in trades) / len(trades) * 100 if trades else 0,
        "mean_trade_pct": statistics.mean(trades) * 100 if trades else 0,
        "trade_std_pct": statistics.pstdev(trades) * 100 if len(trades) > 1 else 0,
        "worst_trade_pct": min(trades) * 100 if trades else 0,
        "best_trade_pct": max(trades) * 100 if trades else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=ROOT / ".run/research/okx_15m_intraday_240d.json")
    parser.add_argument("--cost", type=float, default=0.0008)
    parser.add_argument("--leverage", type=float, default=1)
    parser.add_argument("--output", type=Path, default=ROOT / ".run/research/lead_lag_result.json")
    args = parser.parse_args()
    data = json.loads(args.cache.read_text())["data"]
    start = max(rows[0]["ts"] for rows in data.values())
    end = min(rows[-1]["ts"] for rows in data.values())
    split = end - 60 * DAY_MS
    grid = [Params(*values) for values in itertools.product(
        (1, 4), (0.003, 0.005, 0.008, 0.012), (4, 8, 16), ("continuation", "reversal")
    )]
    results = []
    for params in grid:
        train = backtest(data, params, start, split - 1, args.leverage, args.cost)
        if train["trades"] < 20:
            continue
        test = backtest(data, params, split, end, args.leverage, args.cost)
        results.append({"params": asdict(params), "train": train, "test": test})
    results.sort(key=lambda row: row["train"]["return_pct"], reverse=True)
    payload = {"method": "BTC shock then equal-weight alt basket", "split_ts": split,
               "cost": args.cost, "leverage": args.leverage, "results": results}
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    for row in results[:10]:
        print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
