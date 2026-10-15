#!/usr/bin/env python3
"""Random-date robustness search for the explosive momentum strategy."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from optimize_explosive_momentum import Config, build_snapshots, evaluate, obtain_data


CURRENT_LIVE_CONFIG = Config(
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


PARAMETER_SPACE: dict[str, list[Any]] = {
    "min_signal": [0.03, 0.04, 0.05, 0.06, 0.08, 0.10],
    "min_gap": [0.0, 0.005, 0.01, 0.02, 0.03],
    "min_vol_ratio": [1.5, 2.0, 2.5, 3.0, 4.0, 5.0],
    "hold_hours": [2, 3, 4, 6, 8, 10, 12],
    "stop_loss_pct": [0.04, 0.05, 0.06, 0.08, 0.10],
    "take_profit_pct": [0.06, 0.08, 0.10, 0.12, 0.15, 0.20],
    "market_filter": ["btc_4h_positive", "none"],
    "universe_size": [30, 50, 80],
    "leverage": [3],
    "cooldown_hours": [0, 2, 4, 8, 12],
    "max_signal": [0.08, 0.10, 0.12, 0.15, None],
    "max_ret_4h": [0.10, 0.15, 0.20, 0.30, None],
    "max_ret_24h": [0.15, 0.25, 0.40, 0.60, None],
    "max_vol_ratio": [10.0, 20.0, 50.0, None],
}


def generate_configs(count: int, seed: int) -> list[Config]:
    rng = random.Random(seed)
    configs = {CURRENT_LIVE_CONFIG}
    fields = list(PARAMETER_SPACE)
    maximum = 1
    for values in PARAMETER_SPACE.values():
        maximum *= len(values)
    target = min(count, maximum)
    while len(configs) < target:
        values = {field: rng.choice(PARAMETER_SPACE[field]) for field in fields}
        configs.add(Config(**values))
    return sorted(
        configs,
        key=lambda item: tuple(
            -1.0 if value is None else value
            for value in asdict(item).values()
        ),
    )


def random_windows(
    start: datetime,
    end: datetime,
    count: int,
    window_days: int,
    seed: int,
) -> list[tuple[datetime, datetime]]:
    latest_start = end - timedelta(days=window_days)
    span_hours = int((latest_start - start).total_seconds() // 3600)
    if span_hours < 0:
        raise ValueError("training period is shorter than random window")
    rng = random.Random(seed)
    offsets = {0, span_hours}
    while len(offsets) < min(count, span_hours + 1):
        offsets.add(rng.randint(0, span_hours))
    return [
        (start + timedelta(hours=offset), start + timedelta(hours=offset, days=window_days))
        for offset in sorted(offsets)
    ]


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def score_random_windows(
    config: Config,
    windows: list[tuple[datetime, datetime]],
    snapshots,
    indexes,
) -> dict[str, Any]:
    metrics = [
        evaluate(
            config,
            snapshots,
            indexes,
            int(start.timestamp() * 1000),
            int(end.timestamp() * 1000),
        )
        for start, end in windows
    ]
    returns = [item["return_pct"] for item in metrics]
    drawdowns = [item["max_drawdown_pct"] for item in metrics]
    trades = [item["trades"] for item in metrics]
    positive = sum(value > 0 for value in returns)
    median_return = statistics.median(returns)
    p10_return = percentile(returns, 0.10)
    max_drawdown = max(drawdowns, default=0.0)
    worst_return = min(returns, default=0.0)
    # Downside-adjusted score. A large median return cannot compensate for a
    # strategy that collapses in one regime.
    robust_score = (
        median_return
        + 0.50 * p10_return
        + 0.25 * worst_return
        - 0.50 * max_drawdown
    )
    return {
        "config": asdict(config),
        "robust_score": robust_score,
        "positive_window_rate_pct": positive / len(metrics) * 100 if metrics else 0.0,
        "median_return_pct": median_return,
        "mean_return_pct": statistics.fmean(returns) if returns else 0.0,
        "p10_return_pct": p10_return,
        "worst_window_return_pct": worst_return,
        "best_window_return_pct": max(returns, default=0.0),
        "max_window_drawdown_pct": max_drawdown,
        "median_trades": statistics.median(trades) if trades else 0.0,
        "window_returns_pct": returns,
        "window_drawdowns_pct": drawdowns,
        "window_trades": trades,
    }


async def main_async(args: argparse.Namespace) -> None:
    started = time.monotonic()
    data_args = SimpleNamespace(
        cache=args.cache,
        refresh=args.refresh,
        days=args.days,
        horizons=[12],
        concurrency=args.concurrency,
        top_symbols=args.top_symbols,
    )
    symbols, candles, metadata = await obtain_data(data_args)
    snapshots, indexes = build_snapshots(symbols, candles)
    analysis_start = datetime.fromisoformat(metadata["analysis_start_utc"])
    analysis_end = datetime.fromisoformat(metadata["end_utc"])
    holdout_start = analysis_end - timedelta(days=args.holdout_days)
    windows = random_windows(
        analysis_start,
        holdout_start,
        args.window_count,
        args.window_days,
        args.seed,
    )

    configs = generate_configs(args.config_count, args.seed)
    aggregate = []
    train_start_ms = int(analysis_start.timestamp() * 1000)
    holdout_start_ms = int(holdout_start.timestamp() * 1000)
    for config in configs:
        metrics = evaluate(config, snapshots, indexes, train_start_ms, holdout_start_ms)
        if metrics["trades"] >= args.minimum_train_trades:
            aggregate.append(metrics)
    aggregate.sort(key=lambda item: item["return_pct"], reverse=True)

    # Preserve both market regimes in the shortlist. Otherwise the higher
    # in-sample returns from unfiltered configs can crowd every filtered config
    # out before random-window validation starts.
    filters = PARAMETER_SPACE["market_filter"]
    per_filter = max(1, args.shortlist // len(filters))
    shortlist_configs = []
    for market_filter in filters:
        group = [
            item
            for item in aggregate
            if item["config"]["market_filter"] == market_filter
        ][:per_filter]
        shortlist_configs.extend(Config(**item["config"]) for item in group)
    if CURRENT_LIVE_CONFIG not in shortlist_configs:
        shortlist_configs.append(CURRENT_LIVE_CONFIG)
    robust = [score_random_windows(config, windows, snapshots, indexes) for config in shortlist_configs]
    live_robust = score_random_windows(CURRENT_LIVE_CONFIG, windows, snapshots, indexes)
    eligible = [
        item
        for item in robust
        if item["positive_window_rate_pct"] >= args.minimum_positive_window_rate
        and item["median_trades"] >= args.minimum_window_trades
        and item["positive_window_rate_pct"] >= live_robust["positive_window_rate_pct"]
        and item["p10_return_pct"] >= live_robust["p10_return_pct"]
        and item["worst_window_return_pct"] >= live_robust["worst_window_return_pct"]
        and item["max_window_drawdown_pct"] <= live_robust["max_window_drawdown_pct"]
    ]
    if not eligible:
        raise RuntimeError("no configuration passed random-window robustness thresholds")
    eligible.sort(key=lambda item: item["robust_score"], reverse=True)
    selected = Config(**eligible[0]["config"])
    end_ms = int(analysis_end.timestamp() * 1000)
    result = {
        "data": metadata,
        "method": {
            "seed": args.seed,
            "generated_configs": len(configs),
            "aggregate_eligible_configs": len(aggregate),
            "shortlist_size": len(shortlist_configs),
            "random_window_count": len(windows),
            "window_days": args.window_days,
            "minimum_positive_window_rate_pct": args.minimum_positive_window_rate,
            "candidate_must_dominate_live_downside_metrics": True,
            "candidate_keeps_live_market_filter": False,
            "selection_did_not_use_holdout": True,
        },
        "split": {
            "training_start": analysis_start.isoformat(),
            "training_end": holdout_start.isoformat(),
            "holdout_start": holdout_start.isoformat(),
            "holdout_end": analysis_end.isoformat(),
        },
        "random_windows": [
            {"start": start.isoformat(), "end": end.isoformat()}
            for start, end in windows
        ],
        "current_live_config": asdict(CURRENT_LIVE_CONFIG),
        "current_live_random_validation": live_robust,
        "current_live_holdout": evaluate(
            CURRENT_LIVE_CONFIG,
            snapshots,
            indexes,
            holdout_start_ms,
            end_ms,
            include_trades=True,
        ),
        "selected_config": asdict(selected),
        "selected_random_validation": eligible[0],
        "selected_aggregate_train": evaluate(
            selected, snapshots, indexes, train_start_ms, holdout_start_ms
        ),
        "selected_holdout": evaluate(
            selected,
            snapshots,
            indexes,
            holdout_start_ms,
            end_ms,
            include_trades=True,
        ),
        "top_random_validation": eligible[:50],
        "top_aggregate_train": aggregate[:50],
        "runtime_seconds": time.monotonic() - started,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    summary = {
        key: value
        for key, value in result.items()
        if key not in {"random_windows", "top_random_validation", "top_aggregate_train"}
    }
    for key in ("current_live_holdout", "selected_holdout"):
        summary[key] = {k: v for k, v in result[key].items() if k != "trades_detail"}
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--holdout-days", type=int, default=30)
    parser.add_argument("--window-count", type=int, default=24)
    parser.add_argument("--window-days", type=int, default=14)
    parser.add_argument("--config-count", type=int, default=5000)
    parser.add_argument("--shortlist", type=int, default=400)
    parser.add_argument("--minimum-train-trades", type=int, default=30)
    parser.add_argument("--minimum-window-trades", type=float, default=4.0)
    parser.add_argument("--minimum-positive-window-rate", type=float, default=65.0)
    parser.add_argument("--top-symbols", type=int, default=80)
    parser.add_argument("--seed", type=int, default=20260722)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--cache", type=Path, default=Path("backtest_data/explosive_momentum_1h_180d_top80.json"))
    parser.add_argument("--output", type=Path, default=Path("backtest_results/explosive_momentum_randomized_180d.json"))
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main_async(parse_args()))
