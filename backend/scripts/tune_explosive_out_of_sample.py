#!/usr/bin/env python3
"""Tune explosive momentum on long history and validate on a later period."""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backtest_altcoin_pump_short import load_cache
from optimize_explosive_momentum import Config, build_snapshots, evaluate


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
BASE_CONFIG = Config(
    min_signal=0.04,
    min_gap=0.01,
    min_vol_ratio=3.0,
    hold_hours=8,
    stop_loss_pct=0.08,
    take_profit_pct=0.10,
    market_filter="none",
    universe_size=80,
    leverage=3,
    cooldown_hours=2,
)

SPACE = {
    "min_signal": [0.04, 0.05, 0.055, 0.06, 0.07, 0.08],
    "min_gap": [0.0, 0.005, 0.01, 0.015, 0.02, 0.03],
    "min_vol_ratio": [2.0, 2.5, 3.0, 4.0, 5.0],
    "hold_hours": [4, 6, 8, 10, 12],
    "stop_loss_pct": [0.04, 0.06, 0.08, 0.10],
    "take_profit_pct": [0.06, 0.08, 0.10, 0.12, 0.15, None],
    "market_filter": ["none", "btc_4h_positive"],
    "universe_size": [30, 50, 80],
    "leverage": [3],
    "cooldown_hours": [0, 2, 4, 8],
}


def generate_configs(count: int, seed: int) -> list[Config]:
    rng = random.Random(seed)
    fields = list(SPACE)
    configs = {BASE_CONFIG}
    while len(configs) < count:
        configs.add(Config(**{field: rng.choice(SPACE[field]) for field in fields}))
    return list(configs)


def fold_ranges(start: datetime, end: datetime, folds: int) -> list[tuple[int, int]]:
    span = (end - start) / folds
    return [
        (
            int((start + span * index).timestamp() * 1000),
            int((start + span * (index + 1)).timestamp() * 1000),
        )
        for index in range(folds)
    ]


def robust_metrics(config, snapshots, indexes, ranges) -> dict:
    folds = [evaluate(config, snapshots, indexes, start, end) for start, end in ranges]
    returns = [item["return_pct"] for item in folds]
    drawdowns = [item["max_drawdown_pct"] for item in folds]
    trades = [item["trades"] for item in folds]
    worst = min(returns)
    max_drawdown = max(drawdowns)
    median_return = statistics.median(returns)
    score = median_return + 0.50 * worst - 0.30 * max_drawdown
    return {
        "config": asdict(config),
        "score": score,
        "positive_fold_rate_pct": sum(value > 0 for value in returns) / len(returns) * 100,
        "median_fold_return_pct": median_return,
        "worst_fold_return_pct": worst,
        "max_fold_drawdown_pct": max_drawdown,
        "median_fold_trades": statistics.median(trades),
        "fold_returns_pct": returns,
        "fold_drawdowns_pct": drawdowns,
        "fold_trades": trades,
    }


def main() -> None:
    args = parse_args()
    started = time.monotonic()
    train_symbols, train_candles, train_meta = load_cache(args.train_cache)
    valid_symbols, valid_candles, valid_meta = load_cache(args.validation_cache)
    train_snapshots, train_indexes = build_snapshots(train_symbols, train_candles)
    valid_snapshots, valid_indexes = build_snapshots(valid_symbols, valid_candles)

    train_start = datetime.fromisoformat(train_meta["analysis_start_utc"])
    train_end = datetime.fromisoformat(train_meta["end_utc"]) + timedelta(hours=1)
    validation_start = datetime.strptime(
        args.validation_start, "%Y-%m-%d %H:%M"
    ).replace(tzinfo=LOCAL_TZ)
    validation_end = datetime.fromisoformat(valid_meta["end_utc"]) + timedelta(hours=1)
    train_start_ms = int(train_start.timestamp() * 1000)
    train_end_ms = int(train_end.timestamp() * 1000)
    validation_start_ms = int(validation_start.timestamp() * 1000)
    validation_end_ms = int(validation_end.timestamp() * 1000)

    configs = generate_configs(args.config_count, args.seed)
    aggregate = []
    for config in configs:
        metrics = evaluate(config, train_snapshots, train_indexes, train_start_ms, train_end_ms)
        if metrics["trades"] >= args.minimum_train_trades:
            aggregate.append(metrics)
    aggregate.sort(
        key=lambda item: item["return_pct"] - 0.50 * item["max_drawdown_pct"],
        reverse=True,
    )

    shortlist = [Config(**item["config"]) for item in aggregate[: args.shortlist]]
    if BASE_CONFIG not in shortlist:
        shortlist.append(BASE_CONFIG)
    ranges = fold_ranges(train_start, train_end, args.folds)
    robust = [
        robust_metrics(config, train_snapshots, train_indexes, ranges)
        for config in shortlist
    ]
    eligible = [
        item
        for item in robust
        if item["positive_fold_rate_pct"] >= args.minimum_positive_fold_rate
        and item["median_fold_trades"] >= args.minimum_fold_trades
    ]
    if not eligible:
        raise RuntimeError("no configuration passed the robustness thresholds")
    eligible.sort(key=lambda item: item["score"], reverse=True)
    candidate = Config(**eligible[0]["config"])

    base_validation = evaluate(
        BASE_CONFIG,
        valid_snapshots,
        valid_indexes,
        validation_start_ms,
        validation_end_ms,
        include_trades=True,
    )
    candidate_validation = evaluate(
        candidate,
        valid_snapshots,
        valid_indexes,
        validation_start_ms,
        validation_end_ms,
        include_trades=True,
    )
    candidate_is_better = (
        candidate_validation["trades"] >= 3
        and candidate_validation["return_pct"] > base_validation["return_pct"]
        and candidate_validation["max_drawdown_pct"] <= base_validation["max_drawdown_pct"]
    )
    decision = "candidate" if candidate_is_better else "base"

    result = {
        "method": {
            "selection_uses_validation": False,
            "generated_configs": len(configs),
            "aggregate_eligible": len(aggregate),
            "shortlist": len(shortlist),
            "folds": args.folds,
            "seed": args.seed,
            "adoption_rule": (
                "candidate validation trades >= 3, return > base, "
                "and drawdown <= base"
            ),
        },
        "periods": {
            "training_start": train_start.isoformat(),
            "training_end": train_end.isoformat(),
            "validation_start": validation_start.isoformat(),
            "validation_end": validation_end.astimezone(LOCAL_TZ).isoformat(),
        },
        "base_config": asdict(BASE_CONFIG),
        "candidate_config": asdict(candidate),
        "base_training": evaluate(
            BASE_CONFIG, train_snapshots, train_indexes, train_start_ms, train_end_ms
        ),
        "candidate_training": evaluate(
            candidate, train_snapshots, train_indexes, train_start_ms, train_end_ms
        ),
        "candidate_robustness": eligible[0],
        "base_validation": base_validation,
        "candidate_validation": candidate_validation,
        "decision": decision,
        "selected_config": asdict(candidate if candidate_is_better else BASE_CONFIG),
        "top_robust_candidates": eligible[:20],
        "runtime_seconds": time.monotonic() - started,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = dict(result)
    summary.pop("top_robust_candidates")
    for key in ("base_validation", "candidate_validation"):
        summary[key] = {
            name: value
            for name, value in result[key].items()
            if name != "trades_detail"
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-cache", type=Path, required=True)
    parser.add_argument("--validation-cache", type=Path, required=True)
    parser.add_argument("--validation-start", default="2026-07-23 00:00")
    parser.add_argument("--config-count", type=int, default=8000)
    parser.add_argument("--shortlist", type=int, default=800)
    parser.add_argument("--folds", type=int, default=6)
    parser.add_argument("--minimum-train-trades", type=int, default=60)
    parser.add_argument("--minimum-fold-trades", type=float, default=8)
    parser.add_argument("--minimum-positive-fold-rate", type=float, default=66.0)
    parser.add_argument("--seed", type=int, default=20260725)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    main()
