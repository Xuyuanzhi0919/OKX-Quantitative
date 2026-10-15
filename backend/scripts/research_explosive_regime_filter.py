#!/usr/bin/env python3
"""Tune market-regime gates around the already selected coin-quality rules."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path
from zoneinfo import ZoneInfo

from backtest_altcoin_pump_short import load_cache
from research_explosive_selection_quality import (
    Selector,
    build_snapshots,
    evaluate,
    percentile,
    random_windows,
    window_summary,
)


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
REGIME_SPACE = {
    "min_btc_4h": [-1.0, -0.03, -0.015, 0.0, 0.01],
    "max_btc_4h": [0.03, 0.06, None],
    "min_btc_24h": [-1.0, -0.08, -0.03, 0.0],
    "min_breadth_1h": [0.0, 0.35, 0.45, 0.55, 0.65],
    "min_breadth_4h": [0.0, 0.35, 0.45, 0.55, 0.65],
    "max_market_pumps": [1, 2, 3, 5, None],
}


def main():
    args = parse_args()
    started = time.monotonic()
    previous = json.loads(args.selection_result.read_text(encoding="utf-8"))
    base = Selector(**previous["selected"]["selector"])
    train_symbols, train_candles, train_meta = load_cache(args.train_cache)
    final_symbols, final_candles, _ = load_cache(args.final_cache)
    train_snapshots, train_indexes = build_snapshots(train_symbols, train_candles)
    final_snapshots, final_indexes = build_snapshots(final_symbols, final_candles)
    history_start = datetime.fromisoformat(train_meta["analysis_start_utc"])
    history_end = datetime.fromisoformat(train_meta["end_utc"]) + timedelta(hours=1)
    validation_start = history_end - timedelta(days=30)
    windows = random_windows(history_start, validation_start, 36, 7, args.seed)
    final_start = datetime(2026, 8, 1, tzinfo=LOCAL_TZ)
    final_end = datetime(2026, 8, 16, tzinfo=LOCAL_TZ)

    keys = list(REGIME_SPACE)
    candidates = []
    for values in product(*(REGIME_SPACE[key] for key in keys)):
        candidate = replace(base, **dict(zip(keys, values)))
        if candidate.max_btc_4h is not None and candidate.min_btc_4h > candidate.max_btc_4h:
            continue
        metric = evaluate(candidate, train_snapshots, train_indexes, history_start, validation_start)
        if metric["trades"] < 60 or metric["return_pct"] <= 0 or (metric["profit_factor"] or 0) < 1.10:
            continue
        score = metric["return_pct"] + metric["win_rate_pct"] - 0.8 * metric["max_drawdown_pct"]
        candidates.append((score, candidate, metric))
    candidates.sort(key=lambda row: row[0], reverse=True)

    passed = []
    for _, candidate, train_metric in candidates[:args.shortlist]:
        random_metric = window_summary(candidate, windows, train_snapshots, train_indexes)
        if (random_metric["positive_window_rate_pct"] < 60
                or random_metric["p10_return_pct"] < -15
                or random_metric["worst_drawdown_pct"] > 32
                or random_metric["median_trades"] < 2):
            continue
        validation = evaluate(candidate, train_snapshots, train_indexes, validation_start, history_end)
        if (validation["trades"] < 8 or validation["return_pct"] <= 0
                or (validation["profit_factor"] or 0) < 1.15
                or validation["max_drawdown_pct"] > 25):
            continue
        score = (validation["return_pct"] + validation["win_rate_pct"]
                 + random_metric["median_return_pct"] + 0.5 * random_metric["p10_return_pct"]
                 - validation["max_drawdown_pct"])
        passed.append((score, candidate, train_metric, random_metric, validation))
    if not passed:
        raise RuntimeError("No market regime candidate passed")
    passed.sort(key=lambda row: row[0], reverse=True)
    selected = passed[0][1]

    def package(selector):
        return {
            "selector": asdict(selector),
            "training": evaluate(selector, train_snapshots, train_indexes, history_start, validation_start),
            "random_7d": window_summary(selector, windows, train_snapshots, train_indexes),
            "later_validation": evaluate(selector, train_snapshots, train_indexes, validation_start, history_end),
            "august_test": evaluate(selector, final_snapshots, final_indexes, final_start, final_end),
        }

    result = {
        "method": {
            "selection_rules_fixed_before_regime_search": True,
            "august_used_for_selection": False,
            "candidate_count": len(list(product(*(REGIME_SPACE[key] for key in keys)))),
            "training_eligible": len(candidates),
            "validation_passed": len(passed),
            "runtime_seconds": time.monotonic() - started,
        },
        "previous_selection": package(base),
        "selected_regime": package(selected),
        "top_validated": [
            {"score": score, "selector": asdict(selector), "training": train,
             "random_7d": random_result, "later_validation": validation}
            for score, selector, train, random_result, validation in passed[:20]
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {key: value for key, value in result.items() if key != "top_validated"}
    print(json.dumps(compact, ensure_ascii=False, indent=2))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-cache", type=Path, required=True)
    parser.add_argument("--final-cache", type=Path, required=True)
    parser.add_argument("--selection-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shortlist", type=int, default=500)
    parser.add_argument("--seed", type=int, default=2026081603)
    return parser.parse_args()


if __name__ == "__main__":
    main()
