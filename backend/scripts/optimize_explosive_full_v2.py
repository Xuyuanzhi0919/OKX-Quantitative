#!/usr/bin/env python3
"""Full walk-forward optimization for selector, regime, and exit parameters."""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backtest_altcoin_pump_short import load_cache
from optimize_explosive_momentum import Config
from research_explosive_selection_quality import Selector, build_snapshots, evaluate, percentile


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
INITIAL_NOTIONAL = 2000.0
BASE_EXIT = Config(
    min_signal=0.04, min_gap=0.01, min_vol_ratio=3.0,
    hold_hours=8, stop_loss_pct=0.08, take_profit_pct=0.10,
    market_filter="none", universe_size=80, leverage=3, cooldown_hours=2,
)

SELECTOR_SPACE: dict[str, list[Any]] = {
    "min_signal": [0.04, 0.05, 0.06, 0.07],
    "max_signal": [0.10, 0.12, 0.15, None],
    "min_gap": [0.01, 0.02, 0.03],
    "min_vol_ratio": [2.5, 3.0, 4.0, 5.0],
    "max_vol_ratio": [10.0, 15.0, 20.0, 50.0],
    "max_ret_4h": [0.15, 0.20, 0.30, None],
    "max_ret_24h": [0.30, 0.40, 0.60, None],
    "min_pre_3h": [0.0, 0.01, 0.02, 0.03],
    "max_upper_wick": [0.02, 0.03, 0.04, 0.06],
    "min_close_location": [0.65, 0.70, 0.75, 0.80, 0.85],
    "universe_size": [30, 50, 80],
    "ranking": ["ret_1h", "clean_momentum", "continuation"],
    "min_btc_4h": [-1.0, -0.015, 0.0],
    "max_btc_4h": [0.02, 0.03, 0.05, None],
    "min_btc_24h": [-0.03, 0.0, 0.02],
    "min_breadth_1h": [0.0, 0.40, 0.50, 0.60],
    "min_breadth_4h": [0.0, 0.40, 0.50, 0.60],
    "max_market_pumps": [2, 3, 5, None],
}
EXIT_SPACE: dict[str, list[Any]] = {
    "hold_hours": [2, 3, 4, 6, 8],
    "stop_loss_pct": [0.04, 0.05, 0.06, 0.08],
    "take_profit_pct": [0.06, 0.08, 0.10, 0.12, 0.15],
    "cooldown_hours": [2, 4, 8],
}


@dataclass(frozen=True)
class Candidate:
    selector: Selector
    exit_config: Config


def run(candidate, snapshots, indexes, start, end):
    return evaluate(
        candidate.selector, snapshots, indexes, start, end,
        position_cap_usdt=INITIAL_NOTIONAL,
        balance_usage_fraction=1.0,
        exit_config=candidate.exit_config,
    )


def random_windows(start, end, count, days, seed):
    latest = end - timedelta(days=days)
    span = int((latest - start).total_seconds() // 3600)
    rng = random.Random(seed)
    offsets = {0, span}
    while len(offsets) < count:
        offsets.add(rng.randrange(span + 1))
    return [(start + timedelta(hours=x), start + timedelta(hours=x, days=days)) for x in sorted(offsets)]


def window_metrics(candidate, windows, snapshots, indexes):
    rows = [run(candidate, snapshots, indexes, start, end) for start, end in windows]
    returns = [row["return_pct"] for row in rows]
    return {
        "positive_window_rate_pct": sum(x > 0 for x in returns) / len(rows) * 100,
        "median_return_pct": statistics.median(returns),
        "mean_return_pct": statistics.fmean(returns),
        "p10_return_pct": percentile(returns, 0.10),
        "worst_return_pct": min(returns),
        "median_drawdown_pct": statistics.median(row["max_drawdown_pct"] for row in rows),
        "worst_drawdown_pct": max(row["max_drawdown_pct"] for row in rows),
        "median_win_rate_pct": statistics.median(row["win_rate_pct"] for row in rows),
        "median_trades": statistics.median(row["trades"] for row in rows),
    }


def generate(base: Candidate, count: int, seed: int):
    rng = random.Random(seed)
    candidates = {base}
    selector_keys = list(SELECTOR_SPACE)
    exit_keys = list(EXIT_SPACE)
    while len(candidates) < count:
        selector = replace(base.selector, **{key: rng.choice(SELECTOR_SPACE[key]) for key in selector_keys})
        if selector.max_btc_4h is not None and selector.min_btc_4h > selector.max_btc_4h:
            continue
        exit_config = replace(base.exit_config, **{key: rng.choice(EXIT_SPACE[key]) for key in exit_keys})
        candidates.add(Candidate(selector, exit_config))
    return list(candidates)


def one_factor(base, snapshots, indexes, start, end):
    result = {}
    for field, values in SELECTOR_SPACE.items():
        result[field] = []
        for value in values:
            selector = replace(base.selector, **{field: value})
            if selector.max_btc_4h is not None and selector.min_btc_4h > selector.max_btc_4h:
                continue
            result[field].append({"value": value, **run(Candidate(selector, base.exit_config), snapshots, indexes, start, end)})
    for field, values in EXIT_SPACE.items():
        result[field] = [
            {"value": value, **run(Candidate(base.selector, replace(base.exit_config, **{field: value})), snapshots, indexes, start, end)}
            for value in values
        ]
    return result


def candidate_dict(candidate):
    return {"selector": asdict(candidate.selector), "exit": asdict(candidate.exit_config), "position_notional_usdt": INITIAL_NOTIONAL}


def main():
    args = parse_args(); started = time.monotonic()
    prior = json.loads(args.regime_result.read_text(encoding="utf-8"))
    base = Candidate(Selector(**prior["selected_regime"]["selector"]), BASE_EXIT)
    symbols, candles, meta = load_cache(args.train_cache)
    final_symbols, final_candles, _ = load_cache(args.final_cache)
    snapshots, indexes = build_snapshots(symbols, candles)
    final_snapshots, final_indexes = build_snapshots(final_symbols, final_candles)
    history_start = datetime.fromisoformat(meta["analysis_start_utc"])
    history_end = datetime.fromisoformat(meta["end_utc"]) + timedelta(hours=1)
    confirmation_start = history_end - timedelta(days=30)
    validation_start = confirmation_start - timedelta(days=30)
    windows = random_windows(history_start, validation_start, 30, 7, args.seed)

    factor_results = one_factor(base, snapshots, indexes, history_start, validation_start)
    trained = []
    for candidate in generate(base, args.config_count, args.seed):
        metric = run(candidate, snapshots, indexes, history_start, validation_start)
        if metric["trades"] < 45 or metric["return_pct"] <= 0 or metric["max_drawdown_pct"] > 55:
            continue
        if (metric["profit_factor"] or 0) < 1.10:
            continue
        score = metric["return_pct"] + metric["win_rate_pct"] - metric["max_drawdown_pct"]
        trained.append((score, candidate, metric))
    trained.sort(key=lambda row: row[0], reverse=True)

    robust = []
    for _, candidate, train_metric in trained[:args.shortlist]:
        random_result = window_metrics(candidate, windows, snapshots, indexes)
        if (random_result["positive_window_rate_pct"] < 60 or random_result["p10_return_pct"] < -20
                or random_result["worst_drawdown_pct"] > 40 or random_result["median_trades"] < 2):
            continue
        validation = run(candidate, snapshots, indexes, validation_start, confirmation_start)
        if (validation["trades"] < 8 or validation["return_pct"] <= 0
                or (validation["profit_factor"] or 0) < 1.10 or validation["max_drawdown_pct"] > 30):
            continue
        confirmation = run(candidate, snapshots, indexes, confirmation_start, history_end)
        if (confirmation["trades"] < 8 or confirmation["return_pct"] <= 0
                or (confirmation["profit_factor"] or 0) < 1.10 or confirmation["max_drawdown_pct"] > 30):
            continue
        score = (confirmation["return_pct"] + validation["return_pct"]
                 + confirmation["win_rate_pct"] + 0.5 * random_result["p10_return_pct"]
                 - confirmation["max_drawdown_pct"] - validation["max_drawdown_pct"])
        robust.append((score, candidate, train_metric, random_result, validation, confirmation))
    if not robust:
        raise RuntimeError("No full candidate passed walk-forward gates")
    robust.sort(key=lambda row: row[0], reverse=True)
    selected = robust[0][1]
    august_start = datetime(2026, 8, 1, tzinfo=LOCAL_TZ)
    august_end = datetime(2026, 8, 16, tzinfo=LOCAL_TZ)

    def package(candidate):
        return {
            "candidate": candidate_dict(candidate),
            "training": run(candidate, snapshots, indexes, history_start, validation_start),
            "random_7d": window_metrics(candidate, windows, snapshots, indexes),
            "validation": run(candidate, snapshots, indexes, validation_start, confirmation_start),
            "confirmation": run(candidate, snapshots, indexes, confirmation_start, history_end),
            "august_stress": run(candidate, final_snapshots, final_indexes, august_start, august_end),
        }

    result = {
        "method": {
            "generated_candidates": args.config_count,
            "training_eligible": len(trained), "walk_forward_passed": len(robust),
            "august_used_for_numeric_selection": False,
            "initial_capital_usdt": 1000, "fixed_notional_usdt": INITIAL_NOTIONAL,
            "runtime_seconds": time.monotonic() - started,
        },
        "periods": {
            "training": [history_start.isoformat(), validation_start.isoformat()],
            "validation": [validation_start.isoformat(), confirmation_start.isoformat()],
            "confirmation": [confirmation_start.isoformat(), history_end.isoformat()],
            "august_stress": [august_start.isoformat(), august_end.isoformat()],
        },
        "base": package(base), "selected": package(selected),
        "one_factor_training_sweeps": factor_results,
        "top_walk_forward": [
            {"score": score, "candidate": candidate_dict(candidate), "training": train,
             "random_7d": random_result, "validation": validation, "confirmation": confirmation}
            for score, candidate, train, random_result, validation, confirmation in robust[:20]
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in {"one_factor_training_sweeps", "top_walk_forward"}}, ensure_ascii=False, indent=2))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-cache", type=Path, required=True)
    parser.add_argument("--final-cache", type=Path, required=True)
    parser.add_argument("--regime-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config-count", type=int, default=10000)
    parser.add_argument("--shortlist", type=int, default=600)
    parser.add_argument("--seed", type=int, default=2026081604)
    return parser.parse_args()


if __name__ == "__main__":
    main()
