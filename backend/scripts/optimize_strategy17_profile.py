#!/usr/bin/env python3
"""Walk-forward optimization for strategy 17, followed by a sealed 7-day test."""

from __future__ import annotations

import asyncio
import json
import statistics
from dataclasses import asdict
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any, Optional

from backtest_altcoin_pump_short import load_cache
from backtest_volume_vacuum import obtain_minute_windows, run_acceptance_long
from optimize_explosive_momentum import Config, Feature, Snapshot, build_snapshots


TRAIN_CACHE = Path("backend/backtest_data/explosive_momentum_1h_60d_top80.json")
TRAIN_MINUTES = Path("backend/backtest_data/volume_vacuum_1m_windows.json")
TEST_CACHE = Path("backend/backtest_data/explosive_momentum_1h_latest_7d_top80.json")
TEST_MINUTES = Path("backend/backtest_data/volume_vacuum_latest_7d_windows.json")
OUTPUT = Path("backend/backtest_results/strategy17_walk_forward_optimized.json")
TRAIN_END = datetime.fromisoformat("2026-07-21T08:00:00+00:00")


def candidate_events(
    snapshots: list[Snapshot], start_ms: int, end_ms: int,
    config: Config, max_signal: Optional[float],
) -> list[dict[str, Any]]:
    result = []
    for snapshot in snapshots:
        if not start_ms <= snapshot.ts < end_ms:
            continue
        universe = snapshot.liquid_features[: config.universe_size]
        candidates = [
            item for item in universe
            if item.ret_1h >= config.min_signal
            and item.vol_ratio >= config.min_vol_ratio
            and (max_signal is None or item.ret_1h <= max_signal)
        ]
        candidates.sort(key=lambda item: item.ret_1h, reverse=True)
        if not candidates:
            continue
        if len(candidates) > 1 and candidates[0].ret_1h - candidates[1].ret_1h < config.min_gap:
            continue
        top: Feature = candidates[0]
        result.append({
            "signal_ts": snapshot.ts, "symbol": top.symbol,
            "signal_pct": top.ret_1h * 100, "vol_ratio": top.vol_ratio,
            "btc_4h_pct": snapshot.btc_4h_return * 100,
        })
    return result


def signal_configs():
    for min_signal, min_gap, min_vol_ratio, max_signal in product(
        (0.04, 0.05), (0.01, 0.015, 0.02), (3.0, 4.0, 5.0), (0.06, 0.08, None),
    ):
        yield min_signal, min_gap, min_vol_ratio, max_signal


def trade_configs():
    for hold_hours, stop_loss, take_profit, pullback in product(
        (6, 8), (0.05, 0.08), (0.06, 0.08, 0.10), (0.005, 0.01, 0.015, 0.02),
    ):
        yield hold_hours, stop_loss, take_profit, pullback


def make_config(signal_cfg, trade_cfg) -> Config:
    min_signal, min_gap, min_vol_ratio, _ = signal_cfg
    hold_hours, stop_loss, take_profit, _ = trade_cfg
    return Config(
        min_signal=min_signal, min_gap=min_gap, min_vol_ratio=min_vol_ratio,
        hold_hours=hold_hours, stop_loss_pct=stop_loss, take_profit_pct=take_profit,
        market_filter="none", universe_size=80, leverage=3, cooldown_hours=2,
    )


async def ensure_windows(snapshots, start_ms, end_ms, cache_path: Path) -> dict:
    union: dict[str, dict] = {}
    dummy_trade = (8, 0.08, 0.10, 0.02)
    for signal_cfg in signal_configs():
        config = make_config(signal_cfg, dummy_trade)
        for event in candidate_events(snapshots, start_ms, end_ms, config, signal_cfg[3]):
            union[f"{event['symbol']}:{event['signal_ts']}"] = event
    windows, failures = await obtain_minute_windows(
        list(union.values()), cache_path, proxy=None, concurrency=5,
    )
    if failures:
        raise RuntimeError(f"minute window failures: {failures}")
    return windows


def evaluate_period(snapshots, indexes, windows, start_ms, end_ms, signal_cfg, trade_cfg):
    config = make_config(signal_cfg, trade_cfg)
    events = candidate_events(snapshots, start_ms, end_ms, config, signal_cfg[3])
    metrics, trades, rejected = run_acceptance_long(
        events, windows, indexes, config, end_ms,
        acceptance_level="poc", max_high_pullback_pct=trade_cfg[3],
    )
    return metrics, trades, rejected, len(events)


def params_dict(signal_cfg, trade_cfg):
    return {
        "min_signal": signal_cfg[0], "min_gap": signal_cfg[1],
        "min_vol_ratio": signal_cfg[2], "max_signal": signal_cfg[3],
        "hold_hours": trade_cfg[0], "stop_loss_pct": trade_cfg[1],
        "take_profit_pct": trade_cfg[2], "max_high_pullback_pct": trade_cfg[3],
        "market_filter": "none", "universe_size": 80, "leverage": 3,
        "max_position_usd": 1000, "profile_level": "poc", "profile_hours": 8,
    }


async def main() -> None:
    train_symbols, train_candles, train_meta = load_cache(TRAIN_CACHE)
    test_symbols, test_candles, test_meta = load_cache(TEST_CACHE)
    train_snapshots, train_indexes = build_snapshots(train_symbols, train_candles)
    test_snapshots, test_indexes = build_snapshots(test_symbols, test_candles)
    train_start = datetime.fromisoformat(train_meta["analysis_start_utc"])
    test_start = datetime.fromisoformat("2026-07-21T08:00:00+00:00")
    test_end = datetime.fromisoformat(test_meta["end_utc"])
    train_start_ms, train_end_ms = int(train_start.timestamp() * 1000), int(TRAIN_END.timestamp() * 1000)
    test_start_ms, test_end_ms = int(test_start.timestamp() * 1000), int(test_end.timestamp() * 1000)
    train_windows, test_windows = await asyncio.gather(
        ensure_windows(train_snapshots, train_start_ms, train_end_ms, TRAIN_MINUTES),
        ensure_windows(test_snapshots, test_start_ms, test_end_ms, TEST_MINUTES),
    )

    duration = train_end_ms - train_start_ms
    fold_bounds = [train_start_ms + duration * i // 4 for i in range(5)]
    ranked = []
    for signal_cfg in signal_configs():
        for trade_cfg in trade_configs():
            folds = []
            valid = True
            for left, right in zip(fold_bounds, fold_bounds[1:]):
                metrics, _, _, _ = evaluate_period(
                    train_snapshots, train_indexes, train_windows, left, right,
                    signal_cfg, trade_cfg,
                )
                folds.append(metrics)
                if metrics["trades"] < 3:
                    valid = False
            full, _, _, raw_events = evaluate_period(
                train_snapshots, train_indexes, train_windows,
                train_start_ms, train_end_ms, signal_cfg, trade_cfg,
            )
            if not valid or full["trades"] < 20:
                continue
            returns = [item["return_pct"] for item in folds]
            max_dd = max(item["max_drawdown_pct"] for item in folds)
            rank_key = (
                sum(value > 0 for value in returns),
                min(returns),
                statistics.median(returns) - 0.5 * max_dd,
                full["return_pct"],
            )
            ranked.append({
                "rank_key": rank_key, "params": params_dict(signal_cfg, trade_cfg),
                "folds": folds, "train": full, "raw_events": raw_events,
                "signal_cfg": signal_cfg, "trade_cfg": trade_cfg,
            })
    ranked.sort(key=lambda item: item["rank_key"], reverse=True)
    best = ranked[0]
    test_metrics, test_trades, test_rejected, test_raw = evaluate_period(
        test_snapshots, test_indexes, test_windows, test_start_ms, test_end_ms,
        best["signal_cfg"], best["trade_cfg"],
    )

    original_signal = (0.04, 0.01, 3.0, None)
    original_trade = (8, 0.08, 0.10, 0.02)
    original_train, _, _, original_train_raw = evaluate_period(
        train_snapshots, train_indexes, train_windows, train_start_ms, train_end_ms,
        original_signal, original_trade,
    )
    original_test, original_test_trades, original_test_rejected, original_test_raw = evaluate_period(
        test_snapshots, test_indexes, test_windows, test_start_ms, test_end_ms,
        original_signal, original_trade,
    )
    output = {
        "method": {
            "train_period": [train_start.isoformat(), TRAIN_END.isoformat()],
            "sealed_test_period": [test_start.isoformat(), test_end.isoformat()],
            "selection": "4 chronological folds; prioritize all-positive folds, worst fold, then drawdown-adjusted median",
            "round_trip_cost_pct": 0.12,
        },
        "original": {
            "params": params_dict(original_signal, original_trade),
            "train": original_train, "train_raw_events": original_train_raw,
            "sealed_test": original_test, "test_raw_events": original_test_raw,
            "test_rejected": original_test_rejected, "test_trades": original_test_trades,
        },
        "optimized": {
            "params": best["params"], "train": best["train"], "folds": best["folds"],
            "train_raw_events": best["raw_events"], "sealed_test": test_metrics,
            "test_raw_events": test_raw, "test_rejected": test_rejected,
            "test_trades": test_trades,
        },
        "top_candidates": [
            {k: v for k, v in item.items() if k not in {"signal_cfg", "trade_cfg"}}
            for item in ranked[:20]
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))
    print(json.dumps({
        "output": str(OUTPUT), "original": output["original"],
        "optimized": output["optimized"], "evaluated_configs": len(ranked),
    }, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    asyncio.run(main())
