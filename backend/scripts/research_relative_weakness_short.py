#!/usr/bin/env python3
"""Research regime-filtered relative-weakness short strategies on 1H bars.

This is intentionally independent from pump-fade logic.  Signals require an
altcoin to underperform BTC and then confirm weakness through either a trend
breakdown, a failed rebound, or a compression breakdown.  Entry is always at
the next completed hour's open and exits are volatility-adjusted with ATR.
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
INITIAL_EQUITY = 1000.0
ROUND_TRIP_COST = 0.0012


@dataclass(frozen=True)
class Feature:
    symbol: str
    close: float
    high: float
    ret_1h: float
    ret_3h: float
    ret_6h: float
    ret_24h: float
    relative_24h: float
    volume_ratio: float
    prior_volume_ratio: float
    bearish_body: float
    prior_bearish_body: float
    atr_pct: float
    prior_range_12h: float
    rebound_3h: float
    broke_6h_low: bool
    broke_12h_low: bool
    broke_24h_low: bool
    prior_close: float
    support_6h: float
    support_12h: float
    support_24h: float
    liquidity_24h: float


@dataclass(frozen=True)
class Snapshot:
    ts: int
    btc_ret_6h: float
    btc_ret_24h: float
    btc_below_ema24: bool
    features: tuple[Feature, ...]


@dataclass(frozen=True)
class Config:
    family: str = "trend_breakdown"
    universe_size: int = 50
    btc_ret_24h_max: float = 0.0
    require_btc_below_ema: bool = True
    ret_6h_max: float = -0.02
    ret_24h_max: float = -0.04
    relative_24h_max: float = -0.02
    volume_ratio_min: float = 1.5
    bearish_body_min: float = 0.005
    breakout_hours: int = 12
    compression_range_max: float = 0.08
    rebound_3h_min: float = 0.02
    retest_tolerance: float = 0.005
    retest_bounce_min: float = 0.005
    atr_min: float = 0.01
    atr_max: float = 0.08
    stop_atr: float = 1.5
    target_atr: float = 2.5
    stop_floor: float = 0.02
    stop_cap: float = 0.06
    target_floor: float = 0.03
    target_cap: float = 0.10
    hold_hours: int = 6
    cooldown_hours: int = 12
    position_cap_usdt: float = 1000.0
    equity_allocation_pct: float = 0.75


SPACE: dict[str, list[Any]] = {
    "family": ["trend_breakdown", "failed_rebound", "compression_break", "breakdown_retest"],
    "universe_size": [30, 50, 80],
    "btc_ret_24h_max": [-0.02, -0.01, 0.0, 0.01],
    "require_btc_below_ema": [True, False],
    "ret_6h_max": [-0.01, -0.02, -0.03, -0.05],
    "ret_24h_max": [-0.02, -0.04, -0.06, -0.10],
    "relative_24h_max": [0.0, -0.02, -0.04, -0.06],
    "volume_ratio_min": [1.0, 1.5, 2.0, 3.0],
    "bearish_body_min": [0.002, 0.005, 0.01, 0.02],
    "breakout_hours": [6, 12, 24],
    "compression_range_max": [0.04, 0.06, 0.08, 0.12],
    "rebound_3h_min": [0.01, 0.02, 0.03, 0.05],
    "retest_tolerance": [0.002, 0.005, 0.01, 0.02],
    "retest_bounce_min": [0.0, 0.005, 0.01, 0.02],
    "atr_min": [0.005, 0.01, 0.015],
    "atr_max": [0.04, 0.06, 0.08, 0.12],
    "stop_atr": [1.0, 1.5, 2.0],
    "target_atr": [1.5, 2.0, 2.5, 3.0],
    "hold_hours": [3, 6, 9, 12],
    "cooldown_hours": [8, 12, 24],
}


def ema(values: list[float], period: int) -> float:
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def atr(rows: list[Candle], end: int, period: int = 14) -> float:
    values = []
    for i in range(end - period + 1, end + 1):
        row, previous = rows[i], rows[i - 1]
        values.append(max(row.high - row.low, abs(row.high - previous.close), abs(row.low - previous.close)))
    return statistics.fmean(values)


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
        if bp is None or bp < 48:
            continue
        btc_ret_24h = btc[bp].close / btc[bp - 24].close - 1
        btc_ret_6h = btc[bp].close / btc[bp - 6].close - 1
        btc_ema = ema([row.close for row in btc[bp - 47 : bp + 1]], 24)
        features = []
        for symbol in alt_symbols:
            rows = candles[symbol]
            pos = positions[symbol].get(ts)
            if pos is None or pos < 48:
                continue
            window = rows[pos - 48 : pos + 1]
            if any(window[i].ts - window[i - 1].ts != HOUR_MS for i in range(1, len(window))):
                continue
            current = rows[pos]
            if min(current.open, current.close, rows[pos - 24].close) <= 0:
                continue
            prior_volumes = [row.quote_volume for row in rows[pos - 24 : pos] if row.quote_volume > 0]
            if len(prior_volumes) < 20:
                continue
            avg_volume = statistics.fmean(prior_volumes)
            older_volumes = [row.quote_volume for row in rows[pos - 25 : pos - 1] if row.quote_volume > 0]
            prior_avg_volume = statistics.fmean(older_volumes) if older_volumes else avg_volume
            atr_pct = atr(rows, pos) / current.close
            prior12 = rows[pos - 12 : pos]
            prior_range = (max(row.high for row in prior12) - min(row.low for row in prior12)) / current.close
            ret24 = current.close / rows[pos - 24].close - 1
            features.append(Feature(
                symbol=symbol,
                close=current.close,
                high=current.high,
                ret_1h=current.close / rows[pos - 1].close - 1,
                ret_3h=current.close / rows[pos - 3].close - 1,
                ret_6h=current.close / rows[pos - 6].close - 1,
                ret_24h=ret24,
                relative_24h=ret24 - btc_ret_24h,
                volume_ratio=current.quote_volume / avg_volume if avg_volume else 0.0,
                prior_volume_ratio=rows[pos - 1].quote_volume / prior_avg_volume if prior_avg_volume else 0.0,
                bearish_body=max(0.0, (current.open - current.close) / current.open),
                prior_bearish_body=max(0.0, (rows[pos - 1].open - rows[pos - 1].close) / rows[pos - 1].open),
                atr_pct=atr_pct,
                prior_range_12h=prior_range,
                rebound_3h=rows[pos - 1].close / rows[pos - 4].close - 1,
                broke_6h_low=current.close < min(row.low for row in rows[pos - 6 : pos]),
                broke_12h_low=current.close < min(row.low for row in rows[pos - 12 : pos]),
                broke_24h_low=current.close < min(row.low for row in rows[pos - 24 : pos]),
                prior_close=rows[pos - 1].close,
                support_6h=min(row.low for row in rows[pos - 7 : pos - 1]),
                support_12h=min(row.low for row in rows[pos - 13 : pos - 1]),
                support_24h=min(row.low for row in rows[pos - 25 : pos - 1]),
                liquidity_24h=sum(max(row.quote_volume, 0.0) for row in rows[pos - 23 : pos + 1]),
            ))
        features.sort(key=lambda item: item.liquidity_24h, reverse=True)
        snapshots.append(Snapshot(ts, btc_ret_6h, btc_ret_24h, btc[bp].close < btc_ema, tuple(features)))
    return snapshots, indexes


def family_allowed(config: Config, item: Feature) -> bool:
    if config.family == "breakdown_retest":
        support = {6: item.support_6h, 12: item.support_12h, 24: item.support_24h}[config.breakout_hours]
        return (
            item.prior_close < support
            and item.high >= support * (1 - config.retest_tolerance)
            and item.close < support
            and item.high / item.prior_close - 1 >= config.retest_bounce_min
        )
    broke = {6: item.broke_6h_low, 12: item.broke_12h_low, 24: item.broke_24h_low}[config.breakout_hours]
    if not broke:
        return False
    if config.family == "compression_break":
        return item.prior_range_12h <= config.compression_range_max
    if config.family == "failed_rebound":
        return item.rebound_3h >= config.rebound_3h_min
    return True


def simulate_exit(index: dict[int, Candle], signal_ts: int, atr_pct: float, config: Config):
    entry_ts = signal_ts + HOUR_MS
    entry_bar = index.get(entry_ts)
    if entry_bar is None or entry_bar.open <= 0:
        return None
    entry = entry_bar.open
    stop_pct = min(config.stop_cap, max(config.stop_floor, atr_pct * config.stop_atr))
    target_pct = min(config.target_cap, max(config.target_floor, atr_pct * config.target_atr))
    stop, target = entry * (1 + stop_pct), entry * (1 - target_pct)
    exit_price, exit_ts, reason = entry, entry_ts, "time_exit"
    for offset in range(config.hold_hours):
        ts = entry_ts + offset * HOUR_MS
        bar = index.get(ts)
        if bar is None:
            return None
        if bar.open >= stop:
            exit_price, exit_ts, reason = max(stop, bar.open), ts, "stop_loss"
            break
        if bar.high >= stop:
            exit_price, exit_ts, reason = stop, ts, "stop_loss"
            break
        if bar.low <= target:
            exit_price, exit_ts, reason = target, ts, "take_profit"
            break
        exit_price, exit_ts = bar.close, ts
    return {
        "entry_ts": entry_ts, "exit_ts": exit_ts, "entry": entry, "exit": exit_price,
        "stop_pct": stop_pct, "target_pct": target_pct, "reason": reason,
        "net_position_return": (entry - exit_price) / entry - ROUND_TRIP_COST,
    }


def evaluate(config: Config, snapshots, indexes, start: datetime, end: datetime, include_trades: bool = False):
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    equity = peak = INITIAL_EQUITY
    max_drawdown = 0.0
    next_signal_ts = start_ms
    last_entry_by_symbol: dict[str, int] = {}
    pnls, trades = [], []
    reasons = {"take_profit": 0, "stop_loss": 0, "time_exit": 0}
    for snapshot in snapshots:
        if snapshot.ts < start_ms or snapshot.ts >= end_ms or snapshot.ts < next_signal_ts:
            continue
        if snapshot.btc_ret_24h > config.btc_ret_24h_max:
            continue
        if config.require_btc_below_ema and not snapshot.btc_below_ema24:
            continue
        candidates = []
        for item in snapshot.features[: config.universe_size]:
            if item.ret_6h > config.ret_6h_max or item.ret_24h > config.ret_24h_max:
                continue
            if item.relative_24h > config.relative_24h_max:
                continue
            signal_volume = item.prior_volume_ratio if config.family == "breakdown_retest" else item.volume_ratio
            if signal_volume < config.volume_ratio_min or item.bearish_body < config.bearish_body_min:
                continue
            if not config.atr_min <= item.atr_pct <= config.atr_max:
                continue
            if not family_allowed(config, item):
                continue
            candidates.append(item)
        if not candidates:
            continue
        candidates.sort(key=lambda item: (item.relative_24h, item.ret_24h, -item.volume_ratio))
        selected = candidates[0]
        entry_ts = snapshot.ts + HOUR_MS
        if entry_ts - last_entry_by_symbol.get(selected.symbol, -10**18) < config.cooldown_hours * HOUR_MS:
            continue
        exit_info = simulate_exit(indexes[selected.symbol], snapshot.ts, selected.atr_pct, config)
        if exit_info is None or exit_info["exit_ts"] >= end_ms:
            continue
        notional = min(config.position_cap_usdt, max(equity, 0.0) * config.equity_allocation_pct * 3)
        pnl = notional * exit_info["net_position_return"]
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak if peak else 1.0)
        pnls.append(pnl)
        reasons[exit_info["reason"]] += 1
        last_entry_by_symbol[selected.symbol] = entry_ts
        next_signal_ts = exit_info["exit_ts"]
        if include_trades:
            trades.append({
                "signal_ts": snapshot.ts, "symbol": selected.symbol,
                "ret_6h_pct": selected.ret_6h * 100, "ret_24h_pct": selected.ret_24h * 100,
                "relative_24h_pct": selected.relative_24h * 100,
                "volume_ratio": selected.volume_ratio, "atr_pct": selected.atr_pct * 100,
                "btc_24h_pct": snapshot.btc_ret_24h * 100,
                "position_notional_usdt": notional, "pnl_usdt": pnl, "equity_usdt": equity,
                **exit_info,
            })
    gross_profit = sum(x for x in pnls if x > 0)
    gross_loss = -sum(x for x in pnls if x < 0)
    return {
        "config": asdict(config), "initial_equity": INITIAL_EQUITY, "final_equity": equity,
        "total_pnl_usdt": equity - INITIAL_EQUITY, "return_pct": (equity / INITIAL_EQUITY - 1) * 100,
        "max_drawdown_pct": max_drawdown * 100, "trades": len(pnls),
        "win_rate_pct": sum(x > 0 for x in pnls) / len(pnls) * 100 if pnls else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "exit_reasons": reasons, "ruined": equity <= 0,
        "trades_detail": trades if include_trades else None,
    }


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower, upper = int(position), min(int(position) + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def random_windows(start: datetime, end: datetime, count: int, days: int, seed: int):
    latest = end - timedelta(days=days)
    hours = int((latest - start).total_seconds() // 3600)
    rng = random.Random(seed)
    offsets = {0, hours}
    while len(offsets) < count:
        offsets.add(rng.randrange(hours + 1))
    return [(start + timedelta(hours=x), start + timedelta(hours=x, days=days)) for x in sorted(offsets)]


def robust_metrics(config: Config, windows, snapshots, indexes):
    metrics = [evaluate(config, snapshots, indexes, a, b) for a, b in windows]
    returns = [x["return_pct"] for x in metrics]
    drawdowns = [x["max_drawdown_pct"] for x in metrics]
    trades = [x["trades"] for x in metrics]
    return {
        "positive_window_rate_pct": sum(x > 0 for x in returns) / len(returns) * 100,
        "flat_windows": sum(x == 0 for x in returns),
        "mean_return_pct": statistics.fmean(returns), "median_return_pct": statistics.median(returns),
        "p10_return_pct": percentile(returns, 0.10), "worst_return_pct": min(returns),
        "best_return_pct": max(returns), "median_drawdown_pct": statistics.median(drawdowns),
        "worst_drawdown_pct": max(drawdowns), "total_trades": sum(trades),
        "median_trades": statistics.median(trades), "window_returns_pct": returns,
    }


def generate_configs(count: int, seed: int):
    rng = random.Random(seed)
    fields = list(SPACE)
    configs = {Config(family=family) for family in SPACE["family"]}
    while len(configs) < count:
        base = asdict(Config())
        for field in fields:
            base[field] = rng.choice(SPACE[field])
        configs.add(Config(**base))
    return list(configs)


def compact(metrics: dict[str, Any]):
    return {key: value for key, value in metrics.items() if key != "trades_detail"}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-cache", type=Path, required=True)
    parser.add_argument("--final-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config-count", type=int, default=6000)
    parser.add_argument("--shortlist", type=int, default=300)
    parser.add_argument("--window-count", type=int, default=48)
    parser.add_argument("--seed", type=int, default=20260816)
    return parser.parse_args()


def main():
    args = parse_args()
    started = time.monotonic()
    train_symbols, train_candles, train_meta = load_cache(args.train_cache)
    final_symbols, final_candles, final_meta = load_cache(args.final_cache)
    snapshots, indexes = build_snapshots(train_symbols, train_candles)
    final_snapshots, final_indexes = build_snapshots(final_symbols, final_candles)
    history_start = datetime.fromisoformat(train_meta["analysis_start_utc"]) + timedelta(days=1)
    history_end = datetime.fromisoformat(train_meta["end_utc"]) + timedelta(hours=1)
    validation_start = history_end - timedelta(days=30)
    windows = random_windows(history_start, validation_start, args.window_count, 7, args.seed)
    configs = generate_configs(args.config_count, args.seed)
    aggregate = []
    for config in configs:
        metrics = evaluate(config, snapshots, indexes, history_start, validation_start)
        if metrics["trades"] < 20 or metrics["ruined"]:
            continue
        score = metrics["return_pct"] - metrics["max_drawdown_pct"]
        aggregate.append((score, config, metrics))
    aggregate.sort(key=lambda x: x[0], reverse=True)
    shortlist = []
    per_family = max(1, args.shortlist // len(SPACE["family"]))
    for family in SPACE["family"]:
        family_configs = [x[1] for x in aggregate if x[1].family == family]
        shortlist.extend(family_configs[:per_family])
    robust = []
    for config in shortlist:
        metrics = robust_metrics(config, windows, snapshots, indexes)
        if metrics["total_trades"] < 50 or metrics["positive_window_rate_pct"] < 55:
            continue
        if metrics["p10_return_pct"] < -12 or metrics["worst_drawdown_pct"] > 30:
            continue
        score = metrics["median_return_pct"] + 0.6 * metrics["p10_return_pct"] - 0.4 * metrics["median_drawdown_pct"]
        robust.append((score, config, metrics))
    robust.sort(key=lambda x: x[0], reverse=True)
    validated = []
    for _, config, random_result in robust[:100]:
        result = evaluate(config, snapshots, indexes, validation_start, history_end)
        if result["trades"] < 5 or result["return_pct"] <= 0 or result["max_drawdown_pct"] > 20:
            continue
        if (result["profit_factor"] or 0) < 1.1:
            continue
        score = result["return_pct"] - result["max_drawdown_pct"] + 0.25 * random_result["median_return_pct"]
        validated.append((score, config, random_result, result))
    validated.sort(key=lambda x: x[0], reverse=True)
    if not validated:
        raise RuntimeError("no relative-weakness candidate passed validation")
    selected = validated[0]
    final_start = datetime(2026, 8, 1, tzinfo=LOCAL_TZ)
    final_end = datetime(2026, 8, 16, tzinfo=LOCAL_TZ)
    final_result = evaluate(selected[1], final_snapshots, final_indexes, final_start, final_end, True)
    result = {
        "method": {"strategy": "relative_weakness_short", "generated_configs": len(configs),
                   "selection_uses_august": False, "round_trip_cost_pct": ROUND_TRIP_COST * 100,
                   "same_bar_assumption": "stop_first"},
        "periods": {"history_start": history_start.isoformat(), "training_end": validation_start.isoformat(),
                    "validation_start": validation_start.isoformat(), "validation_end": history_end.isoformat(),
                    "final_start": final_start.isoformat(), "final_end": final_end.isoformat()},
        "selected_config": asdict(selected[1]), "selected_random_7d": selected[2],
        "selected_later_validation": compact(selected[3]), "selected_august": final_result,
        "top_validated": [{"score": score, "config": asdict(config), "random_7d": random_result,
                           "validation": compact(validation)}
                          for score, config, random_result, validation in validated[:20]],
        "family_best": {}, "runtime_seconds": time.monotonic() - started,
        "data": {"training": train_meta, "final": final_meta},
    }
    for family in SPACE["family"]:
        match = next((x for x in validated if x[1].family == family), None)
        if match:
            result["family_best"][family] = {"config": asdict(match[1]), "random_7d": match[2],
                                              "validation": compact(match[3])}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    summary = dict(result)
    summary.pop("top_validated")
    summary["selected_random_7d"] = {k: v for k, v in selected[2].items() if k != "window_returns_pct"}
    summary["selected_august"] = compact(final_result)
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
