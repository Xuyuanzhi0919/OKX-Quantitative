#!/usr/bin/env python3
"""Trade intraday cross-sectional factors only when signal dispersion is extreme."""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from intraday_factor_walkforward import DAY_MS, build_periods
from return_first_walkforward import ROOT


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1)))]


def backtest(periods: list[dict], factor: str, direction: int, threshold: float,
             leverage: float, cost: float) -> dict:
    equity = peak = 1.0
    max_dd = 0.0
    trades = []
    for period in periods:
        raw = [row["factors"][factor] for row in period["rows"]]
        if max(raw) - min(raw) < threshold:
            continue
        values = [direction * value for value in raw]
        order = sorted(range(len(values)), key=values.__getitem__)
        forward = [row["forward"] for row in period["rows"]]
        value = leverage * (0.5 * (forward[order[-1]] - forward[order[0]]) - cost)
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
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=ROOT / ".run/research/okx_15m_intraday_120d.json")
    parser.add_argument("--cost", type=float, default=0.0004)
    parser.add_argument("--leverage", type=float, default=1)
    parser.add_argument("--output", type=Path, default=ROOT / ".run/research/intraday_event_result.json")
    args = parser.parse_args()
    data = json.loads(args.cache.read_text())["data"]
    start = max(rows[0]["ts"] for rows in data.values())
    end = min(rows[-1]["ts"] for rows in data.values())
    split = end - 30 * DAY_MS
    output = []
    for hold in (4, 8, 16, 32):
        train, test = build_periods(data, start, split - 1, hold), build_periods(data, split, end, hold)
        for factor in train[0]["rows"][0]["factors"]:
            # Direction comes only from training gross performance.
            candidates = []
            for direction in (1, -1):
                spreads = [max(row["factors"][factor] for row in p["rows"]) -
                           min(row["factors"][factor] for row in p["rows"]) for p in train]
                for q in (0.5, 0.7, 0.8, 0.9, 0.95):
                    threshold = percentile(spreads, q)
                    result = backtest(train, factor, direction, threshold, args.leverage, args.cost)
                    if result["trades"] >= 20:
                        candidates.append((result["return_pct"], direction, q, threshold, result))
            if not candidates:
                continue
            _, direction, q, threshold, train_result = max(candidates, key=lambda row: row[0])
            test_result = backtest(test, factor, direction, threshold, args.leverage, args.cost)
            output.append({
                "hold_hours": hold / 4, "factor": factor, "direction": direction,
                "train_quantile": q, "threshold": threshold,
                "train": train_result, "test": test_result,
            })
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    for row in sorted(output, key=lambda item: item["test"]["return_pct"], reverse=True):
        if row["train"]["return_pct"] > 0 and row["test"]["return_pct"] > 0:
            print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
