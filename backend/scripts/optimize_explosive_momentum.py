#!/usr/bin/env python3
"""Walk-forward optimizer for the explosive momentum chaser strategy.

Downloads a crypto-only OKX USDT swap universe, builds historical hourly
liquidity rankings from quote volume, tunes on the first part of the sample,
and evaluates the chosen parameters on an untouched final holdout period.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from itertools import product
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from backtest_altcoin_pump_short import (
    HOUR_MS,
    OKX_API,
    Candle,
    fetch_symbol_candles,
    load_cache,
    request_json,
    select_universe,
    write_cache,
)


ROUND_TRIP_COST_PCT = 0.0012
BENCHMARKS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP")


@dataclass(frozen=True)
class Config:
    min_signal: float = 0.06
    min_gap: float = 0.01
    min_vol_ratio: float = 1.2
    hold_hours: int = 4
    stop_loss_pct: float = 0.04
    take_profit_pct: float | None = 0.10
    market_filter: str = "btc_4h_positive"
    universe_size: int = 50
    leverage: int = 3
    cooldown_hours: int = 4
    max_signal: float | None = None
    max_ret_4h: float | None = None
    max_ret_24h: float | None = None
    max_vol_ratio: float | None = None


@dataclass(frozen=True)
class Feature:
    symbol: str
    ret_1h: float
    ret_4h: float
    ret_24h: float
    vol_ratio: float
    liquidity_24h: float


@dataclass(frozen=True)
class Snapshot:
    ts: int
    btc_4h_return: float
    liquid_features: tuple[Feature, ...]


def build_snapshots(
    symbols: list[str],
    candles: dict[str, list[Candle]],
) -> tuple[list[Snapshot], dict[str, dict[int, Candle]]]:
    indexes = {symbol: {row.ts: row for row in rows} for symbol, rows in candles.items()}
    alt_symbols = [symbol for symbol in symbols if symbol not in BENCHMARKS]
    btc = candles["BTC-USDT-SWAP"]
    btc_pos = {row.ts: index for index, row in enumerate(btc)}
    alt_pos = {
        symbol: {row.ts: index for index, row in enumerate(candles[symbol])}
        for symbol in alt_symbols
    }
    all_ts = sorted({row.ts for symbol in alt_symbols for row in candles[symbol]})
    snapshots: list[Snapshot] = []
    for ts in all_ts:
        bpos = btc_pos.get(ts)
        if bpos is None or bpos < 4 or btc[bpos - 4].close <= 0:
            continue
        btc_ret = btc[bpos].close / btc[bpos - 4].close - 1
        features: list[Feature] = []
        for symbol in alt_symbols:
            pos = alt_pos[symbol].get(ts)
            rows = candles[symbol]
            if pos is None or pos < 24 or rows[pos - 1].close <= 0:
                continue
            current = rows[pos]
            if current.ts - rows[pos - 1].ts != HOUR_MS:
                continue
            history = rows[pos - 24 : pos]
            if any(history[i].ts - history[i - 1].ts != HOUR_MS for i in range(1, len(history))):
                continue
            volumes = [row.quote_volume for row in history if row.quote_volume > 0]
            if len(volumes) < 20:
                continue
            avg_volume = statistics.fmean(volumes)
            vol_ratio = current.quote_volume / avg_volume if avg_volume > 0 else 0.0
            liquidity = sum(volumes) + max(current.quote_volume, 0.0)
            features.append(
                Feature(
                    symbol=symbol,
                    ret_1h=current.close / rows[pos - 1].close - 1,
                    ret_4h=current.close / rows[pos - 4].close - 1,
                    ret_24h=current.close / rows[pos - 24].close - 1,
                    vol_ratio=vol_ratio,
                    liquidity_24h=liquidity,
                )
            )
        features.sort(key=lambda item: item.liquidity_24h, reverse=True)
        snapshots.append(Snapshot(ts=ts, btc_4h_return=btc_ret, liquid_features=tuple(features)))
    return snapshots, indexes


def simulate_exit(
    index: dict[int, Candle],
    signal_ts: int,
    config: Config,
) -> dict[str, Any] | None:
    entry_ts = signal_ts + HOUR_MS
    entry_bar = index.get(entry_ts)
    if entry_bar is None or entry_bar.open <= 0:
        return None
    entry = entry_bar.open
    stop = entry * (1 - config.stop_loss_pct)
    take_profit = (
        entry * (1 + config.take_profit_pct)
        if config.take_profit_pct is not None
        else None
    )
    exit_price = entry
    exit_ts = entry_ts
    reason = "missing"
    for offset in range(config.hold_hours):
        ts = entry_ts + offset * HOUR_MS
        bar = index.get(ts)
        if bar is None:
            return None
        stop_hit = bar.low <= stop
        tp_hit = take_profit is not None and bar.high >= take_profit
        # The path inside a 1H candle is unknown. Use stop-first when both are
        # touched so optimization cannot benefit from optimistic ordering.
        if bar.open <= stop:
            exit_price, exit_ts, reason = min(stop, bar.open), ts, "stop_loss"
            break
        if stop_hit:
            exit_price, exit_ts, reason = stop, ts, "stop_loss"
            break
        if tp_hit:
            assert take_profit is not None
            exit_price, exit_ts, reason = take_profit, ts, "take_profit"
            break
        exit_price, exit_ts, reason = bar.close, ts, "time_exit"
    return {
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "entry": entry,
        "exit": exit_price,
        "reason": reason,
        "gross_pct": exit_price / entry - 1,
    }


def evaluate(
    config: Config,
    snapshots: list[Snapshot],
    indexes: dict[str, dict[int, Candle]],
    start_ms: int,
    end_ms: int,
    initial_capital: float = 1000.0,
    max_position_usd: float = 1000.0,
    include_trades: bool = False,
) -> dict[str, Any]:
    capital = initial_capital
    peak = initial_capital
    max_drawdown = 0.0
    next_signal_ts = start_ms
    last_entry_by_symbol: dict[str, int] = {}
    trades: list[dict[str, Any]] = []
    position_returns: list[float] = []
    pnl_values: list[float] = []
    reasons: dict[str, int] = {"take_profit": 0, "stop_loss": 0, "time_exit": 0}
    for snapshot in snapshots:
        if snapshot.ts < start_ms or snapshot.ts >= end_ms or snapshot.ts < next_signal_ts:
            continue
        if config.market_filter == "btc_4h_positive" and snapshot.btc_4h_return <= 0:
            continue
        universe = snapshot.liquid_features[: config.universe_size]
        candidates = [
            item
            for item in universe
            if item.ret_1h >= config.min_signal and item.vol_ratio >= config.min_vol_ratio
            and (config.max_signal is None or item.ret_1h <= config.max_signal)
            and (config.max_ret_4h is None or item.ret_4h <= config.max_ret_4h)
            and (config.max_ret_24h is None or item.ret_24h <= config.max_ret_24h)
            and (config.max_vol_ratio is None or item.vol_ratio <= config.max_vol_ratio)
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda item: item.ret_1h, reverse=True)
        top = candidates[0]
        if len(candidates) > 1 and top.ret_1h - candidates[1].ret_1h < config.min_gap:
            continue
        entry_ts = snapshot.ts + HOUR_MS
        if entry_ts - last_entry_by_symbol.get(top.symbol, -10**18) < config.cooldown_hours * HOUR_MS:
            continue
        exit_info = simulate_exit(indexes[top.symbol], snapshot.ts, config)
        if exit_info is None or exit_info["exit_ts"] >= end_ms:
            continue
        net_position_return = exit_info["gross_pct"] - ROUND_TRIP_COST_PCT
        # Match live sizing: max_position_usd is notional, while leverage only
        # changes required margin. If equity falls, live code caps notional at
        # roughly 75% of available balance times leverage.
        position_notional = min(max_position_usd, max(0.0, capital) * 0.75 * config.leverage)
        if position_notional <= 0:
            break
        pnl = position_notional * net_position_return
        capital += pnl
        peak = max(peak, capital)
        drawdown = (peak - capital) / peak if peak > 0 else 1.0
        max_drawdown = max(max_drawdown, drawdown)
        position_returns.append(net_position_return)
        pnl_values.append(pnl)
        reasons[exit_info["reason"]] += 1
        last_entry_by_symbol[top.symbol] = entry_ts
        if include_trades:
            trades.append(
                {
                    "signal_ts": snapshot.ts,
                    "symbol": top.symbol,
                    "signal_pct": top.ret_1h * 100,
                    "vol_ratio": top.vol_ratio,
                    "btc_4h_pct": snapshot.btc_4h_return * 100,
                    "position_notional_usd": position_notional,
                    "margin_used_usd": position_notional / config.leverage,
                    "net_position_return_pct": net_position_return * 100,
                    "pnl_usdt": pnl,
                    **exit_info,
                }
            )
        next_signal_ts = exit_info["exit_ts"]
    wins = sum(value > 0 for value in pnl_values)
    return {
        "config": asdict(config),
        "initial_capital": initial_capital,
        "final_capital": capital,
        "total_pnl_usdt": capital - initial_capital,
        "return_pct": (capital / initial_capital - 1) * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "trades": len(position_returns),
        "win_rate_pct": wins / len(position_returns) * 100 if position_returns else 0.0,
        "average_position_return_pct": statistics.fmean(position_returns) * 100 if position_returns else 0.0,
        "average_pnl_usdt": statistics.fmean(pnl_values) if pnl_values else 0.0,
        "worst_position_return_pct": min(position_returns, default=0.0) * 100,
        "best_position_return_pct": max(position_returns, default=0.0) * 100,
        "exit_reasons": reasons,
        "trades_detail": trades if include_trades else None,
    }


SEARCH_SPACE: dict[str, list[Any]] = {
    "min_signal": [0.04, 0.05, 0.06, 0.07, 0.08, 0.10],
    "min_gap": [0.0, 0.005, 0.01, 0.02],
    "min_vol_ratio": [1.0, 1.2, 1.5, 2.0, 3.0],
    "hold_hours": [2, 3, 4, 6, 8],
    "stop_loss_pct": [0.03, 0.04, 0.05, 0.06, 0.08],
    "take_profit_pct": [0.04, 0.06, 0.08, 0.10, 0.12, 0.15],
    "market_filter": ["btc_4h_positive", "none"],
    "universe_size": [30, 50, 80],
    "leverage": [2, 3, 5],
    "cooldown_hours": [2, 4, 8],
}


def optimize(
    baseline: Config,
    snapshots: list[Snapshot],
    indexes: dict[str, dict[int, Candle]],
    start_ms: int,
    end_ms: int,
    rounds: int,
) -> tuple[Config, list[dict[str, Any]]]:
    current = baseline
    trials: dict[Config, dict[str, Any]] = {}

    def run(config: Config) -> dict[str, Any]:
        if config not in trials:
            trials[config] = evaluate(config, snapshots, indexes, start_ms, end_ms)
        return trials[config]

    run(current)
    for _ in range(rounds):
        changed = False
        for field, values in SEARCH_SPACE.items():
            candidates = [replace(current, **{field: value}) for value in values]
            eligible = [config for config in candidates if run(config)["trades"] >= 8]
            if not eligible:
                continue
            best = max(eligible, key=lambda config: run(config)["return_pct"])
            if run(best)["return_pct"] > run(current)["return_pct"] + 1e-9:
                current = best
                changed = True
        if not changed:
            break

    ranked = sorted(trials.values(), key=lambda item: item["return_pct"], reverse=True)
    return current, ranked


def targeted_volume_grid(
    snapshots: list[Snapshot],
    indexes: dict[str, dict[int, Candle]],
    start_ms: int,
    end_ms: int,
) -> list[dict[str, Any]]:
    """Joint search around the high-volume regime missed by coordinate descent."""
    trials = []
    for values in product(
        [0.04, 0.05, 0.06],
        [0.01, 0.02],
        [2.0, 3.0],
        [3, 4, 6, 8],
        [0.06, 0.08],
        [0.08, 0.10, 0.12],
        [50, 80],
        [2, 4, 8],
    ):
        config = Config(
            min_signal=values[0],
            min_gap=values[1],
            min_vol_ratio=values[2],
            hold_hours=values[3],
            stop_loss_pct=values[4],
            take_profit_pct=values[5],
            market_filter="btc_4h_positive",
            universe_size=values[6],
            leverage=3,
            cooldown_hours=values[7],
        )
        metrics = evaluate(config, snapshots, indexes, start_ms, end_ms)
        if metrics["trades"] >= 8:
            trials.append(metrics)
    return trials


def select_robust_config(
    ranked_trials: list[dict[str, Any]],
    snapshots: list[Snapshot],
    indexes: dict[str, dict[int, Candle]],
    train_start: datetime,
    train_end: datetime,
    folds: int = 4,
) -> tuple[Config, list[dict[str, Any]]]:
    fold_span = (train_end - train_start) / folds
    scored: list[dict[str, Any]] = []
    for trial in ranked_trials:
        config = Config(**trial["config"])
        fold_metrics = []
        for fold_index in range(folds):
            fold_start = train_start + fold_span * fold_index
            fold_end = train_start + fold_span * (fold_index + 1)
            fold_metrics.append(
                evaluate(
                    config,
                    snapshots,
                    indexes,
                    int(fold_start.timestamp() * 1000),
                    int(fold_end.timestamp() * 1000),
                )
            )
        if sum(item["trades"] for item in fold_metrics) < 12:
            continue
        returns = [item["return_pct"] for item in fold_metrics]
        drawdowns = [item["max_drawdown_pct"] for item in fold_metrics]
        # Return remains the primary objective. The worst training fold is used
        # instead of the aggregate peak, with a modest drawdown penalty to
        # reject configurations whose result depends on one explosive regime.
        robust_score = min(returns) - 0.25 * max(drawdowns)
        scored.append(
            {
                "config": asdict(config),
                "robust_score": robust_score,
                "fold_returns_pct": returns,
                "fold_drawdowns_pct": drawdowns,
                "fold_trades": [item["trades"] for item in fold_metrics],
                "aggregate_train_return_pct": trial["return_pct"],
            }
        )
    if not scored:
        raise RuntimeError("no robust configuration had enough trades")
    scored.sort(key=lambda item: item["robust_score"], reverse=True)
    return Config(**scored[0]["config"]), scored


async def obtain_data(args: argparse.Namespace) -> tuple[list[str], dict[str, list[Candle]], dict[str, Any]]:
    if args.cache.exists() and not args.refresh:
        return load_cache(args.cache)
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    start = end - timedelta(days=args.days, hours=36)
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(
        base_url=OKX_API,
        headers={"User-Agent": "OKK-explosive-momentum-optimizer/1.0"},
        timeout=httpx.Timeout(20.0),
        trust_env=False,
    ) as client:
        alts = await select_universe(client, semaphore, args.top_symbols)
        symbols = alts + list(BENCHMARKS)
        completed = await asyncio.gather(
            *(fetch_symbol_candles(client, semaphore, symbol, start_ms, end_ms) for symbol in symbols),
            return_exceptions=True,
        )
    candles: dict[str, list[Candle]] = {}
    failures: dict[str, str] = {}
    for symbol, result in zip(symbols, completed):
        if isinstance(result, Exception):
            failures[symbol] = str(result)
        else:
            _, rows = result
            candles[symbol] = rows
    if failures or any(symbol not in candles for symbol in BENCHMARKS):
        raise RuntimeError(f"candle download incomplete: {failures}")
    metadata = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "start_utc": start.isoformat(),
        "analysis_start_utc": (end - timedelta(days=args.days)).isoformat(),
        "end_utc": end.isoformat(),
        "universe_method": "current top crypto-category USDT swaps; historical hourly ranking by rolling quote volume",
        "loaded_symbols": len(symbols),
        "failures": failures,
    }
    write_cache(args.cache, symbols, candles, metadata)
    return symbols, candles, metadata


async def main_async(args: argparse.Namespace) -> None:
    started = time.monotonic()
    symbols, candles, metadata = await obtain_data(args)
    snapshots, indexes = build_snapshots(symbols, candles)
    analysis_start = datetime.fromisoformat(metadata["analysis_start_utc"])
    analysis_end = datetime.fromisoformat(metadata["end_utc"])
    holdout_start = analysis_end - timedelta(days=args.holdout_days)
    train_start_ms = int(analysis_start.timestamp() * 1000)
    holdout_start_ms = int(holdout_start.timestamp() * 1000)
    end_ms = int(analysis_end.timestamp() * 1000)

    baseline = Config()
    aggregate_best, ranked = optimize(
        baseline,
        snapshots,
        indexes,
        train_start_ms,
        holdout_start_ms,
        args.rounds,
    )
    targeted = targeted_volume_grid(
        snapshots,
        indexes,
        train_start_ms,
        holdout_start_ms,
    )
    by_config = {
        Config(**item["config"]): item
        for item in [*ranked, *targeted]
    }
    ranked = sorted(by_config.values(), key=lambda item: item["return_pct"], reverse=True)
    aggregate_best = Config(**ranked[0]["config"])
    best, robust_ranked = select_robust_config(
        ranked,
        snapshots,
        indexes,
        analysis_start,
        holdout_start,
    )
    result = {
        "data": metadata,
        "split": {
            "train_start": analysis_start.isoformat(),
            "train_end": holdout_start.isoformat(),
            "holdout_start": holdout_start.isoformat(),
            "holdout_end": analysis_end.isoformat(),
        },
        "baseline_train": evaluate(baseline, snapshots, indexes, train_start_ms, holdout_start_ms),
        "baseline_holdout": evaluate(baseline, snapshots, indexes, holdout_start_ms, end_ms, include_trades=True),
        "aggregate_train_best_config": asdict(aggregate_best),
        "optimized_config": asdict(best),
        "optimized_train": evaluate(best, snapshots, indexes, train_start_ms, holdout_start_ms),
        "optimized_holdout": evaluate(best, snapshots, indexes, holdout_start_ms, end_ms, include_trades=True),
        "top_train_trials": ranked[:30],
        "top_robust_train_trials": robust_ranked[:30],
        "trial_count": len(ranked),
        "runtime_seconds": time.monotonic() - started,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    summary = {
        key: value
        for key, value in result.items()
        if key not in {"top_train_trials", "top_robust_train_trials"}
    }
    for key in ("baseline_holdout", "optimized_holdout"):
        summary[key] = {k: v for k, v in result[key].items() if k != "trades_detail"}
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--holdout-days", type=int, default=20)
    parser.add_argument("--top-symbols", type=int, default=80)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--cache", type=Path, default=Path("backtest_data/explosive_momentum_1h.json"))
    parser.add_argument("--output", type=Path, default=Path("backtest_results/explosive_momentum_optimized.json"))
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if args.days <= args.holdout_days or args.holdout_days <= 0:
        parser.error("days must be greater than a positive holdout-days")
    return args


if __name__ == "__main__":
    asyncio.run(main_async(parse_args()))
