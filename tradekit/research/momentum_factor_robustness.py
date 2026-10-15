#!/usr/bin/env python3
"""Robustness checks for the fixed 24-hour cross-sectional momentum factor."""
from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

from factor_discovery_walkforward import evaluate_factor, samples
from return_first_walkforward import ROOT


DAY = 86_400_000


def period_returns(periods: list[dict], factor: str, direction: float,
                   leverage: float, cost: float,
                   shuffled: bool = False, rng: random.Random | None = None) -> list[float]:
    returns = []
    for period in periods:
        ordered = list(range(len(period["rows"])))
        if shuffled:
            assert rng is not None
            rng.shuffle(ordered)
        else:
            ordered.sort(key=lambda i: direction * period["rows"][i]["factors"][factor])
        short_return = statistics.mean(period["rows"][i]["forward"] for i in ordered[:2])
        long_return = statistics.mean(period["rows"][i]["forward"] for i in ordered[-2:])
        returns.append(leverage * (0.5 * (long_return - short_return) - cost))
    return returns


def compounded(returns: list[float]) -> float:
    equity = 1.0
    for value in returns:
        equity *= 1 + value
    return equity - 1


def significance(periods: list[dict], factor: str, direction: float,
                 leverage: float, cost: float,
                 trials: int = 5000) -> dict:
    actual_returns = period_returns(periods, factor, direction, leverage, cost)
    actual = compounded(actual_returns)
    rng = random.Random(20260715)
    null_returns = [compounded(period_returns(periods, factor, direction, leverage, cost, True, rng))
                    for _ in range(trials)]
    p_value = (1 + sum(value >= actual for value in null_returns)) / (trials + 1)
    boot = []
    for _ in range(trials):
        sampled = [rng.choice(actual_returns) for _ in actual_returns]
        boot.append(compounded(sampled))
    boot.sort()
    return {
        "permutation_trials": trials,
        "one_sided_p_value": p_value,
        "bootstrap_return_95pct": [boot[int(0.025 * trials)] * 100,
                                    boot[int(0.975 * trials)] * 100],
    }


def metric(data: dict[str, list[dict]], start: int, end: int, factor: str,
           direction: float, horizon: int, leverage: float, cost: float) -> dict:
    periods = samples(data, start, end, horizon)
    result = evaluate_factor(periods, factor, direction, leverage, cost)
    result["significance"] = significance(periods, factor, direction, leverage, cost)
    result.update({"start_ts": start, "end_ts": end})
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--factor", default="momentum_24h")
    parser.add_argument("--direction", type=float, default=1.0)
    parser.add_argument("--leverage", type=float, default=1.0)
    parser.add_argument("--roundtrip-cost", type=float, default=0.0008)
    parser.add_argument("--cache", type=Path, default=ROOT / ".run/research/okx_1h_majors.json")
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / ".run/research/momentum_factor_robustness.json",
    )
    args = parser.parse_args()

    cache = json.loads(args.cache.read_text())
    data = cache["data"]
    common_start = max(int(rows[0]["ts"]) for rows in data.values())
    common_end = min(int(rows[-1]["ts"]) for rows in data.values())

    # Three disjoint 30-day blocks reveal whether the result is concentrated
    # in the final holdout month. The factor and direction are fixed upfront.
    blocks = []
    block_count = max(1, (common_end - common_start) // (30 * DAY) + 1)
    for index in range(block_count):
        start = common_start + index * 30 * DAY
        end = min(start + 30 * DAY - 1, common_end)
        blocks.append({"block": index + 1, **metric(
            data, start, end, args.factor, args.direction,
            args.horizon, args.leverage, args.roundtrip_cost
        )})

    # Leave one symbol out while keeping all rules unchanged.
    leave_one_out = {}
    for omitted in data:
        subset = {symbol: rows for symbol, rows in data.items() if symbol != omitted}
        leave_one_out[omitted] = metric(
            subset, common_start, common_end, args.factor, args.direction, args.horizon,
            args.leverage, args.roundtrip_cost,
        )

    result = {
        "factor": args.factor,
        "direction": args.direction,
        "horizon_hours": args.horizon,
        "leverage": args.leverage,
        "roundtrip_cost_per_gross_notional": args.roundtrip_cost,
        "symbols": list(data),
        "thirty_day_blocks": blocks,
        "leave_one_out": leave_one_out,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
