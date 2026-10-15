#!/usr/bin/env python3
"""Cross-sectional factor discovery with a strict train/holdout split."""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Callable

from return_first_walkforward import ROOT


def rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    for place, index in enumerate(order):
        result[index] = float(place)
    return result


def correlation(left: list[float], right: list[float]) -> float:
    if len(left) < 3:
        return 0.0
    lx, rx = rank(left), rank(right)
    lm, rm = statistics.mean(lx), statistics.mean(rx)
    numerator = sum((a - lm) * (b - rm) for a, b in zip(lx, rx))
    denominator = math.sqrt(sum((a - lm) ** 2 for a in lx) * sum((b - rm) ** 2 for b in rx))
    return numerator / denominator if denominator else 0.0


def pct(rows: list[dict], index: int, bars: int) -> float:
    return rows[index]["close"] / rows[index - bars]["close"] - 1


def std_returns(rows: list[dict], index: int, bars: int) -> float:
    returns = [rows[i]["close"] / rows[i - 1]["close"] - 1 for i in range(index - bars + 1, index + 1)]
    return statistics.pstdev(returns) if len(returns) > 1 else 0.0


FACTORS: dict[str, Callable[[list[dict], int], float]] = {
    "momentum_6h": lambda rows, i: pct(rows, i, 6),
    "momentum_24h": lambda rows, i: pct(rows, i, 24),
    "momentum_72h": lambda rows, i: pct(rows, i, 72),
    "reversal_1h": lambda rows, i: -pct(rows, i, 1),
    "reversal_6h": lambda rows, i: -pct(rows, i, 6),
    "vol_adj_momentum_24h": lambda rows, i: pct(rows, i, 24) / max(std_returns(rows, i, 24), 1e-9),
    "low_volatility_24h": lambda rows, i: -std_returns(rows, i, 24),
    "volume_surprise": lambda rows, i: rows[i]["volume"] / max(statistics.mean(r["volume"] for r in rows[i-24:i]), 1e-9),
    "breakout_24h": lambda rows, i: rows[i]["close"] / max(r["high"] for r in rows[i-24:i]) - 1,
    "range_position_24h": lambda rows, i: (
        (rows[i]["close"] - min(r["low"] for r in rows[i-24:i])) /
        max(max(r["high"] for r in rows[i-24:i]) - min(r["low"] for r in rows[i-24:i]), 1e-9)
    ),
}


def samples(data: dict[str, list[dict]], start: int, end: int, horizon: int) -> list[dict]:
    maps = {symbol: {int(row["ts"]): i for i, row in enumerate(rows)} for symbol, rows in data.items()}
    timeline = sorted(set.intersection(*(set(value) for value in maps.values())))
    output = []
    for ts in timeline:
        if not start <= ts <= end or ts % (horizon * 3_600_000) != 0:
            continue
        rows_at_ts = []
        for symbol, rows in data.items():
            i = maps[symbol][ts]
            if i < 72 or i + horizon >= len(rows):
                break
            forward = rows[i + horizon]["close"] / rows[i]["close"] - 1
            rows_at_ts.append({
                "symbol": symbol, "forward": forward,
                "factors": {name: function(rows, i) for name, function in FACTORS.items()},
            })
        if len(rows_at_ts) == len(data):
            output.append({"ts": ts, "rows": rows_at_ts})
    return output


def evaluate_factor(periods: list[dict], name: str, direction: float, leverage: float,
                    roundtrip_cost: float, top_n: int = 2) -> dict:
    ics, returns = [], []
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for period in periods:
        values = [row["factors"][name] * direction for row in period["rows"]]
        forward = [row["forward"] for row in period["rows"]]
        ics.append(correlation(values, forward))
        ordered = sorted(range(len(values)), key=values.__getitem__)
        short_return = statistics.mean(forward[i] for i in ordered[:top_n])
        long_return = statistics.mean(forward[i] for i in ordered[-top_n:])
        portfolio_return = leverage * (0.5 * (long_return - short_return) - roundtrip_cost)
        returns.append(portfolio_return)
        equity *= max(0.0, 1 + portfolio_return)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0)
    positive_ic = sum(1 for value in ics if value > 0)
    return {
        "periods": len(periods), "mean_ic": statistics.mean(ics) if ics else 0,
        "ic_positive_pct": positive_ic / len(ics) * 100 if ics else 0,
        "return_pct": (equity - 1) * 100, "max_drawdown_pct": max_dd,
        "mean_period_return_pct": statistics.mean(returns) * 100 if returns else 0,
    }


def composite_periods(periods: list[dict], selected: list[tuple[str, float]]) -> list[dict]:
    result = []
    for period in periods:
        factor_ranks = []
        for name, direction in selected:
            factor_ranks.append(rank([row["factors"][name] * direction for row in period["rows"]]))
        rows = []
        for i, row in enumerate(period["rows"]):
            score = statistics.mean(values[i] for values in factor_ranks)
            rows.append({**row, "factors": {"composite": score}})
        result.append({"ts": period["ts"], "rows": rows})
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--leverage", type=float, default=3.0)
    parser.add_argument("--roundtrip-cost", type=float, default=0.0008)
    parser.add_argument("--cache", type=Path, default=ROOT / ".run/research/okx_1h_majors.json")
    parser.add_argument("--output", type=Path, default=ROOT / ".run/research/factor_discovery_result.json")
    args = parser.parse_args()
    cache = json.loads(args.cache.read_text())
    data = cache["data"]
    common_start = max(int(rows[0]["ts"]) for rows in data.values())
    common_end = min(int(rows[-1]["ts"]) for rows in data.values())
    split = common_end - 30 * 86_400_000
    train_periods = samples(data, common_start, split - 1, args.horizon)
    test_periods = samples(data, split, common_end, args.horizon)
    factors = {}
    selected = []
    for name in FACTORS:
        raw = evaluate_factor(train_periods, name, 1, args.leverage, args.roundtrip_cost)
        direction = 1.0 if raw["mean_ic"] >= 0 else -1.0
        train = evaluate_factor(train_periods, name, direction, args.leverage, args.roundtrip_cost)
        test = evaluate_factor(test_periods, name, direction, args.leverage, args.roundtrip_cost)
        factors[name] = {"direction": direction, "train": train, "test": test}
    stable = sorted(
        ((name, result) for name, result in factors.items() if result["train"]["mean_ic"] > 0 and result["train"]["ic_positive_pct"] >= 52),
        key=lambda item: item[1]["train"]["mean_ic"], reverse=True,
    )[:3]
    selected = [(name, result["direction"]) for name, result in stable]
    composite = None
    if selected:
        train_composite = composite_periods(train_periods, selected)
        test_composite = composite_periods(test_periods, selected)
        composite = {
            "selected": selected,
            "train": evaluate_factor(train_composite, "composite", 1, args.leverage, args.roundtrip_cost),
            "test": evaluate_factor(test_composite, "composite", 1, args.leverage, args.roundtrip_cost),
        }
    result = {
        "method": "cross-sectional rank IC and top2-bottom2 market-neutral portfolio",
        "symbols": list(data), "horizon_hours": args.horizon, "leverage": args.leverage,
        "roundtrip_cost_per_gross_notional": args.roundtrip_cost,
        "train_periods": len(train_periods), "test_periods": len(test_periods),
        "factors": factors, "composite": composite,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
