#!/usr/bin/env python3
"""Validate baseline and optimized selectors over many time windows."""

from __future__ import annotations

import argparse
import json
import random
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backtest_altcoin_pump_short import load_cache
from research_explosive_selection_quality import BASELINE, Selector, build_snapshots, evaluate, percentile


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [row["return_pct"] for row in rows]
    return {
        "windows": len(rows),
        "positive_window_rate_pct": sum(value > 0 for value in returns) / len(rows) * 100,
        "mean_return_pct": statistics.fmean(returns),
        "median_return_pct": statistics.median(returns),
        "p10_return_pct": percentile(returns, 0.10),
        "worst_return_pct": min(returns),
        "best_return_pct": max(returns),
        "median_win_rate_pct": statistics.median(row["win_rate_pct"] for row in rows),
        "median_drawdown_pct": statistics.median(row["max_drawdown_pct"] for row in rows),
        "worst_drawdown_pct": max(row["max_drawdown_pct"] for row in rows),
        "median_trades": statistics.median(row["trades"] for row in rows),
    }


def compare(windows, snapshots, indexes, baseline, selected, position_cap_usdt=1000.0, balance_usage_fraction=0.75):
    details = []
    for start, end in windows:
        old = evaluate(
            baseline, snapshots, indexes, start, end,
            position_cap_usdt=position_cap_usdt,
            balance_usage_fraction=balance_usage_fraction,
        )
        new = evaluate(
            selected, snapshots, indexes, start, end,
            position_cap_usdt=position_cap_usdt,
            balance_usage_fraction=balance_usage_fraction,
        )
        details.append({
            "start": start.isoformat(),
            "end": end.isoformat(),
            "baseline": old,
            "selected": new,
            "return_improvement_pct_points": new["return_pct"] - old["return_pct"],
        })
    return {
        "baseline": summarize([row["baseline"] for row in details]),
        "selected": summarize([row["selected"] for row in details]),
        "selected_higher_return_window_rate_pct": sum(
            row["selected"]["return_pct"] > row["baseline"]["return_pct"] for row in details
        ) / len(details) * 100,
        "details": details,
    }


def random_windows(start, end, days: int, count: int, seed: int):
    last = end - timedelta(days=days)
    hours = int((last - start).total_seconds() // 3600)
    rng = random.Random(seed)
    offsets: set[int] = set()
    while len(offsets) < min(count, hours + 1):
        offsets.add(rng.randrange(hours + 1))
    return [(start + timedelta(hours=x), start + timedelta(hours=x, days=days)) for x in sorted(offsets)]


def rolling_windows(start, end, days: int):
    windows = []
    cursor = start
    while cursor + timedelta(days=days) <= end:
        windows.append((cursor, cursor + timedelta(days=days)))
        cursor += timedelta(days=1)
    return windows


def main():
    args = parse_args()
    optimization = json.loads(args.optimization_result.read_text(encoding="utf-8"))
    selected_package = (
        optimization.get("selected")
        or optimization.get("selected_regime")
        or optimization.get("conservative_combination")
    )
    if selected_package is None:
        raise ValueError("optimization result has neither selected nor selected_regime")
    selector_payload = selected_package.get("selector") or selected_package["candidate"]["selector"]
    selected = Selector(**selector_payload)
    train_symbols, train_candles, train_meta = load_cache(args.train_cache)
    final_symbols, final_candles, _ = load_cache(args.final_cache)
    train_snapshots, train_indexes = build_snapshots(train_symbols, train_candles)
    final_snapshots, final_indexes = build_snapshots(final_symbols, final_candles)
    history_start = datetime.fromisoformat(train_meta["analysis_start_utc"])
    history_end = datetime.fromisoformat(train_meta["end_utc"]) + timedelta(hours=1)
    final_start = datetime(2026, 8, 1, tzinfo=LOCAL_TZ)
    final_end = datetime(2026, 8, 16, tzinfo=LOCAL_TZ)

    result = {
        "method": {
            "historical_random_windows_per_length": args.window_count,
            "historical_windows_are_post_selection_stress_checks_not_new_holdouts": True,
            "august_windows_are_rolling_slices_of_the_untouched_holdout": True,
            "seed": args.seed,
            "position_cap_usdt": args.position_cap_usdt,
            "balance_usage_fraction": args.balance_usage_fraction,
        },
        "selectors": {"baseline": BASELINE.__dict__, "selected": selected.__dict__},
        "historical_random": {},
        "august_holdout_rolling": {},
    }
    for days in (3, 7, 14, 30):
        windows = random_windows(history_start, history_end, days, args.window_count, args.seed + days)
        result["historical_random"][f"{days}d"] = compare(
            windows, train_snapshots, train_indexes, BASELINE, selected,
            args.position_cap_usdt, args.balance_usage_fraction,
        )
    for days in (3, 5, 7):
        windows = rolling_windows(final_start, final_end, days)
        result["august_holdout_rolling"][f"{days}d"] = compare(
            windows, final_snapshots, final_indexes, BASELINE, selected,
            args.position_cap_usdt, args.balance_usage_fraction,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = json.loads(json.dumps(result))
    for group in ("historical_random", "august_holdout_rolling"):
        for value in compact[group].values():
            value.pop("details")
    print(json.dumps(compact, ensure_ascii=False, indent=2))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-cache", type=Path, required=True)
    parser.add_argument("--final-cache", type=Path, required=True)
    parser.add_argument("--optimization-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--window-count", type=int, default=60)
    parser.add_argument("--seed", type=int, default=2026081602)
    parser.add_argument("--position-cap-usdt", type=float, default=1000.0)
    parser.add_argument("--balance-usage-fraction", type=float, default=0.75)
    return parser.parse_args()


if __name__ == "__main__":
    main()
