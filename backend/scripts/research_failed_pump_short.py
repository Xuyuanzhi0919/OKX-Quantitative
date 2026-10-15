#!/usr/bin/env python3
"""Research a confirmation-based failed-pump short strategy.

Unlike the old immediate pump short, this model waits for the next completed
hour to reject the pump before entering at the following hour's open.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backtest_altcoin_pump_short import HOUR_MS, Candle, load_cache


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
BENCHMARKS = {"BTC-USDT-SWAP", "ETH-USDT-SWAP"}
ROUND_TRIP_COST = 0.0012
INITIAL_EQUITY = 1000.0


@dataclass(frozen=True)
class Feature:
    symbol: str
    pump_return: float
    pump_volume_ratio: float
    confirmation_drop: float
    confirmation_body: float
    confirmation_upper_wick: float
    ret_4h: float
    ret_24h: float
    liquidity_24h: float


@dataclass(frozen=True)
class Snapshot:
    ts: int
    btc_4h: float
    btc_24h: float
    features: tuple[Feature, ...]


@dataclass(frozen=True)
class Config:
    pump_min: float = 0.05
    pump_max: float | None = 0.20
    volume_ratio_min: float = 3.0
    volume_ratio_max: float | None = 50.0
    confirmation_drop_min: float = 0.01
    confirmation_drop_max: float | None = 0.08
    upper_wick_min: float = 0.0
    max_ret_4h: float | None = 0.25
    max_ret_24h: float | None = 0.40
    btc_filter: str = "btc_4h_negative"
    universe_size: int = 80
    stop_loss_pct: float = 0.04
    take_profit_pct: float = 0.05
    hold_hours: int = 6
    cooldown_hours: int = 8
    position_cap_usdt: float = 500.0
    equity_allocation_pct: float = 0.75


SPACE: dict[str, list[Any]] = {
    "pump_min": [0.04, 0.05, 0.06, 0.08],
    "pump_max": [0.12, 0.20, 0.40, None],
    "volume_ratio_min": [2.0, 3.0, 4.0, 5.0],
    "volume_ratio_max": [10.0, 20.0, 50.0, None],
    "confirmation_drop_min": [0.005, 0.01, 0.015, 0.02, 0.03],
    "confirmation_drop_max": [0.03, 0.05, 0.08, None],
    "upper_wick_min": [0.0, 0.005, 0.01, 0.02],
    "max_ret_4h": [0.15, 0.25, 0.40, None],
    "max_ret_24h": [0.25, 0.40, 0.60, None],
    "btc_filter": ["none", "btc_4h_negative", "btc_24h_negative", "both_negative"],
    "universe_size": [30, 50, 80],
    "stop_loss_pct": [0.03, 0.04, 0.05, 0.06],
    "take_profit_pct": [0.03, 0.04, 0.05, 0.06, 0.08],
    "hold_hours": [3, 4, 6, 8],
    "cooldown_hours": [4, 8, 12, 24],
    "position_cap_usdt": [500.0, 750.0, 1000.0],
    "equity_allocation_pct": [0.50, 0.75, 1.00],
}


def build_snapshots(symbols: list[str], candles: dict[str, list[Candle]]):
    indexes = {symbol: {row.ts: row for row in rows} for symbol, rows in candles.items()}
    positions = {symbol: {row.ts: i for i, row in enumerate(rows)} for symbol, rows in candles.items()}
    btc = candles["BTC-USDT-SWAP"]
    btc_pos = positions["BTC-USDT-SWAP"]
    alt_symbols = [symbol for symbol in symbols if symbol not in BENCHMARKS]
    timestamps = sorted({row.ts for symbol in alt_symbols for row in candles[symbol]})
    snapshots = []
    for ts in timestamps:
        bp = btc_pos.get(ts)
        if bp is None or bp < 24 or btc[bp - 24].close <= 0:
            continue
        features = []
        for symbol in alt_symbols:
            rows = candles[symbol]
            pos = positions[symbol].get(ts)
            if pos is None or pos < 26:
                continue
            window = rows[pos - 26 : pos + 1]
            if any(window[i].ts - window[i - 1].ts != HOUR_MS for i in range(1, len(window))):
                continue
            current = rows[pos]
            pump = rows[pos - 1]
            before = rows[pos - 2]
            if min(current.open, current.close, pump.close, before.close) <= 0:
                continue
            pump_return = pump.close / before.close - 1
            confirmation_drop = current.close / pump.close - 1
            # Pre-filter only impossible research cases; all tunable thresholds
            # remain in evaluate().
            if pump_return < 0.03 or confirmation_drop >= 0 or current.close >= current.open:
                continue
            prior_volumes = [row.quote_volume for row in rows[pos - 25 : pos - 1] if row.quote_volume > 0]
            if len(prior_volumes) < 20:
                continue
            average_volume = statistics.fmean(prior_volumes)
            volume_ratio = pump.quote_volume / average_volume if average_volume > 0 else 0.0
            upper_wick = (current.high - max(current.open, current.close)) / current.open
            liquidity = sum(max(row.quote_volume, 0.0) for row in rows[pos - 23 : pos + 1])
            features.append(Feature(
                symbol=symbol,
                pump_return=pump_return,
                pump_volume_ratio=volume_ratio,
                confirmation_drop=-confirmation_drop,
                confirmation_body=(current.open - current.close) / current.open,
                confirmation_upper_wick=max(0.0, upper_wick),
                ret_4h=current.close / rows[pos - 4].close - 1,
                ret_24h=current.close / rows[pos - 24].close - 1,
                liquidity_24h=liquidity,
            ))
        features.sort(key=lambda item: item.liquidity_24h, reverse=True)
        snapshots.append(Snapshot(
            ts=ts,
            btc_4h=btc[bp].close / btc[bp - 4].close - 1,
            btc_24h=btc[bp].close / btc[bp - 24].close - 1,
            features=tuple(features),
        ))
    return snapshots, indexes


def btc_allowed(config: Config, snapshot: Snapshot) -> bool:
    if config.btc_filter == "btc_4h_negative":
        return snapshot.btc_4h < 0
    if config.btc_filter == "btc_24h_negative":
        return snapshot.btc_24h < 0
    if config.btc_filter == "both_negative":
        return snapshot.btc_4h < 0 and snapshot.btc_24h < 0
    return True


def simulate_exit(index: dict[int, Candle], signal_ts: int, config: Config):
    entry_ts = signal_ts + HOUR_MS
    entry_bar = index.get(entry_ts)
    if entry_bar is None or entry_bar.open <= 0:
        return None
    entry = entry_bar.open
    stop = entry * (1 + config.stop_loss_pct)
    target = entry * (1 - config.take_profit_pct)
    exit_price, exit_ts, reason = entry, entry_ts, "time_exit"
    for offset in range(config.hold_hours):
        ts = entry_ts + offset * HOUR_MS
        bar = index.get(ts)
        if bar is None:
            return None
        if bar.open >= stop:
            exit_price, exit_ts, reason = max(stop, bar.open), ts, "stop_loss"
            break
        # Conservative inside-candle ordering: short stop before target.
        if bar.high >= stop:
            exit_price, exit_ts, reason = stop, ts, "stop_loss"
            break
        if bar.low <= target:
            exit_price, exit_ts, reason = target, ts, "take_profit"
            break
        exit_price, exit_ts = bar.close, ts
    return {
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "entry": entry,
        "exit": exit_price,
        "reason": reason,
        "net_position_return": (entry - exit_price) / entry - ROUND_TRIP_COST,
    }


def evaluate(config: Config, snapshots, indexes, start: datetime, end: datetime, include_trades: bool = False):
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    equity = peak = INITIAL_EQUITY
    max_drawdown = 0.0
    next_signal_ts = start_ms
    last_entry_by_symbol: dict[str, int] = {}
    pnl_values = []
    trades = []
    reasons = {"take_profit": 0, "stop_loss": 0, "time_exit": 0}
    for snapshot in snapshots:
        if snapshot.ts < start_ms or snapshot.ts >= end_ms or snapshot.ts < next_signal_ts:
            continue
        if not btc_allowed(config, snapshot):
            continue
        candidates = []
        for item in snapshot.features[: config.universe_size]:
            if item.pump_return < config.pump_min:
                continue
            if config.pump_max is not None and item.pump_return > config.pump_max:
                continue
            if item.pump_volume_ratio < config.volume_ratio_min:
                continue
            if config.volume_ratio_max is not None and item.pump_volume_ratio > config.volume_ratio_max:
                continue
            if item.confirmation_drop < config.confirmation_drop_min:
                continue
            if config.confirmation_drop_max is not None and item.confirmation_drop > config.confirmation_drop_max:
                continue
            if item.confirmation_upper_wick < config.upper_wick_min:
                continue
            if config.max_ret_4h is not None and item.ret_4h > config.max_ret_4h:
                continue
            if config.max_ret_24h is not None and item.ret_24h > config.max_ret_24h:
                continue
            candidates.append(item)
        if not candidates:
            continue
        candidates.sort(key=lambda item: (item.confirmation_drop, item.pump_return, item.pump_volume_ratio), reverse=True)
        selected = candidates[0]
        entry_ts = snapshot.ts + HOUR_MS
        if entry_ts - last_entry_by_symbol.get(selected.symbol, -10**18) < config.cooldown_hours * HOUR_MS:
            continue
        exit_info = simulate_exit(indexes[selected.symbol], snapshot.ts, config)
        if exit_info is None or exit_info["exit_ts"] >= end_ms:
            continue
        notional = min(
            config.position_cap_usdt,
            max(equity, 0.0) * config.equity_allocation_pct * 3,
        )
        if notional <= 0:
            break
        pnl = notional * exit_info["net_position_return"]
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak if peak > 0 else 1.0)
        pnl_values.append(pnl)
        reasons[exit_info["reason"]] += 1
        last_entry_by_symbol[selected.symbol] = entry_ts
        next_signal_ts = exit_info["exit_ts"]
        if include_trades:
            trades.append({
                "signal_ts": snapshot.ts,
                "symbol": selected.symbol,
                "pump_return_pct": selected.pump_return * 100,
                "pump_volume_ratio": selected.pump_volume_ratio,
                "confirmation_drop_pct": selected.confirmation_drop * 100,
                "btc_4h_pct": snapshot.btc_4h * 100,
                "btc_24h_pct": snapshot.btc_24h * 100,
                "position_notional_usdt": notional,
                "pnl_usdt": pnl,
                "equity_usdt": equity,
                **exit_info,
            })
    gross_profit = sum(value for value in pnl_values if value > 0)
    gross_loss = -sum(value for value in pnl_values if value < 0)
    return {
        "config": asdict(config),
        "initial_equity": INITIAL_EQUITY,
        "final_equity": equity,
        "total_pnl_usdt": equity - INITIAL_EQUITY,
        "return_pct": (equity / INITIAL_EQUITY - 1) * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "trades": len(pnl_values),
        "win_rate_pct": sum(value > 0 for value in pnl_values) / len(pnl_values) * 100 if pnl_values else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "average_pnl_usdt": statistics.fmean(pnl_values) if pnl_values else 0.0,
        "exit_reasons": reasons,
        "ruined": equity <= 0,
        "trades_detail": trades if include_trades else None,
    }


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def random_windows(start: datetime, end: datetime, count: int, days: int, seed: int):
    latest = end - timedelta(days=days)
    span_hours = int((latest - start).total_seconds() // 3600)
    rng = random.Random(seed)
    offsets = {0, span_hours}
    while len(offsets) < count:
        offsets.add(rng.randrange(span_hours + 1))
    return [(start + timedelta(hours=value), start + timedelta(hours=value, days=days)) for value in sorted(offsets)]


def random_metrics(config: Config, windows, snapshots, indexes):
    metrics = [evaluate(config, snapshots, indexes, start, end) for start, end in windows]
    returns = [item["return_pct"] for item in metrics]
    drawdowns = [item["max_drawdown_pct"] for item in metrics]
    trades = [item["trades"] for item in metrics]
    return {
        "config": asdict(config),
        "positive_window_rate_pct": sum(value > 0 for value in returns) / len(returns) * 100,
        "median_return_pct": statistics.median(returns),
        "mean_return_pct": statistics.fmean(returns),
        "p10_return_pct": percentile(returns, 0.10),
        "worst_return_pct": min(returns),
        "best_return_pct": max(returns),
        "median_drawdown_pct": statistics.median(drawdowns),
        "worst_drawdown_pct": max(drawdowns),
        "median_trades": statistics.median(trades),
        "window_returns_pct": returns,
    }


def generate_configs(count: int, seed: int):
    rng = random.Random(seed)
    fields = list(SPACE)
    configs = {Config()}
    while len(configs) < count:
        configs.add(Config(**{field: rng.choice(SPACE[field]) for field in fields}))
    return list(configs)


def compact(metrics: dict[str, Any]):
    return {key: value for key, value in metrics.items() if key != "trades_detail"}


def main() -> None:
    args = parse_args()
    started = time.monotonic()
    train_symbols, train_candles, train_meta = load_cache(args.train_cache)
    final_symbols, final_candles, final_meta = load_cache(args.final_cache)
    train_snapshots, train_indexes = build_snapshots(train_symbols, train_candles)
    final_snapshots, final_indexes = build_snapshots(final_symbols, final_candles)
    history_start = datetime.fromisoformat(train_meta["analysis_start_utc"])
    history_end = datetime.fromisoformat(train_meta["end_utc"]) + timedelta(hours=1)
    validation_start = history_end - timedelta(days=args.validation_days)
    final_start = datetime.strptime(args.final_start, "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
    final_end = datetime.strptime(args.final_end, "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
    windows = random_windows(history_start, validation_start, args.window_count, args.window_days, args.seed)

    aggregate = []
    for config in generate_configs(args.config_count, args.seed):
        metrics = evaluate(config, train_snapshots, train_indexes, history_start, validation_start)
        if metrics["trades"] >= args.minimum_train_trades and not metrics["ruined"]:
            score = metrics["return_pct"] - 0.75 * metrics["max_drawdown_pct"]
            aggregate.append((score, config, metrics))
    aggregate.sort(key=lambda item: item[0], reverse=True)

    shortlist = []
    per_filter = max(1, args.shortlist // len(SPACE["btc_filter"]))
    for btc_filter in SPACE["btc_filter"]:
        shortlist.extend([item[1] for item in aggregate if item[1].btc_filter == btc_filter][:per_filter])
    robust = [random_metrics(config, windows, train_snapshots, train_indexes) for config in shortlist]
    eligible = [item for item in robust if (
        item["positive_window_rate_pct"] >= args.minimum_positive_window_rate
        and item["p10_return_pct"] >= args.minimum_p10_return
        and item["worst_drawdown_pct"] <= args.maximum_window_drawdown
        and item["median_trades"] >= args.minimum_window_trades
    )]
    eligible.sort(key=lambda item: item["median_return_pct"] + 0.5 * item["p10_return_pct"] - 0.5 * item["median_drawdown_pct"], reverse=True)

    validated = []
    for item in eligible[: args.validation_candidates]:
        config = Config(**item["config"])
        metrics = evaluate(config, train_snapshots, train_indexes, validation_start, history_end)
        if (
            metrics["trades"] >= args.minimum_validation_trades
            and metrics["return_pct"] > 0
            and metrics["max_drawdown_pct"] <= args.maximum_validation_drawdown
            and (metrics["profit_factor"] or 0) >= args.minimum_validation_profit_factor
        ):
            score = metrics["return_pct"] - metrics["max_drawdown_pct"] + 0.25 * item["median_return_pct"]
            validated.append((score, config, item, metrics))
    if not validated:
        raise RuntimeError("no failed-pump short candidate passed validation")
    validated.sort(key=lambda item: item[0], reverse=True)
    _, selected, selected_random, selected_validation = validated[0]
    final_metrics = evaluate(selected, final_snapshots, final_indexes, final_start, final_end, include_trades=True)
    decision = "accept" if (
        final_metrics["return_pct"] > 0
        and final_metrics["max_drawdown_pct"] <= args.maximum_validation_drawdown
        and (final_metrics["profit_factor"] or 0) >= args.minimum_validation_profit_factor
    ) else "reject"
    result = {
        "method": {
            "strategy": "confirmed_failed_pump_short",
            "signal": "pump candle, then bearish confirmation, short next 1H open",
            "generated_configs": args.config_count,
            "aggregate_eligible": len(aggregate),
            "shortlist": len(shortlist),
            "random_windows": len(windows),
            "final_holdout_used_for_selection": False,
            "round_trip_cost_pct": ROUND_TRIP_COST * 100,
            "same_bar_assumption": "stop_first",
        },
        "periods": {
            "training_start": history_start.isoformat(),
            "training_end": validation_start.isoformat(),
            "validation_start": validation_start.isoformat(),
            "validation_end": history_end.isoformat(),
            "final_start": final_start.isoformat(),
            "final_end_exclusive": final_end.isoformat(),
        },
        "selected_config": asdict(selected),
        "selected_random_validation": selected_random,
        "selected_later_validation": compact(selected_validation),
        "selected_final_holdout": final_metrics,
        "decision": decision,
        "top_validated": [
            {"score": score, "config": asdict(config), "random": random_result, "validation": compact(validation)}
            for score, config, random_result, validation in validated[:20]
        ],
        "runtime_seconds": time.monotonic() - started,
        "data": {"training": train_meta, "final": final_meta},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    summary = dict(result)
    summary.pop("top_validated")
    summary["selected_random_validation"] = {
        key: value for key, value in selected_random.items() if key != "window_returns_pct"
    }
    summary["selected_final_holdout"] = compact(final_metrics)
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-cache", type=Path, required=True)
    parser.add_argument("--final-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--final-start", default="2026-08-01 00:00")
    parser.add_argument("--final-end", default="2026-08-16 00:00")
    parser.add_argument("--validation-days", type=int, default=30)
    parser.add_argument("--config-count", type=int, default=6000)
    parser.add_argument("--shortlist", type=int, default=400)
    parser.add_argument("--validation-candidates", type=int, default=100)
    parser.add_argument("--window-count", type=int, default=24)
    parser.add_argument("--window-days", type=int, default=15)
    parser.add_argument("--minimum-train-trades", type=int, default=30)
    parser.add_argument("--minimum-window-trades", type=float, default=3)
    parser.add_argument("--minimum-validation-trades", type=int, default=5)
    parser.add_argument("--minimum-positive-window-rate", type=float, default=60)
    parser.add_argument("--minimum-p10-return", type=float, default=-15)
    parser.add_argument("--maximum-window-drawdown", type=float, default=35)
    parser.add_argument("--maximum-validation-drawdown", type=float, default=25)
    parser.add_argument("--minimum-validation-profit-factor", type=float, default=1.10)
    parser.add_argument("--seed", type=int, default=20260817)
    return parser.parse_args()


if __name__ == "__main__":
    main()
