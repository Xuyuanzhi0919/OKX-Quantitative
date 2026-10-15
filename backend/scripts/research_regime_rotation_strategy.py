#!/usr/bin/env python3
"""Backtest a bidirectional BTC-regime altcoin rotation system.

The strategy is a complete trading system rather than a single long/short
trigger: it classifies the BTC regime, ranks liquid altcoins cross-sectionally,
opens in the regime direction, adds only to profitable positions, and manages
the aggregate position with ATR stops, targets, time exits, and a drawdown
cool-off.  All entries use the next 1H open.
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
ONE_WAY_COST = 0.0006


@dataclass(frozen=True)
class Feature:
    symbol: str
    close: float
    high: float
    low: float
    ret_1h: float
    ret_6h: float
    ret_24h: float
    relative_24h: float
    volume_ratio: float
    atr_pct: float
    bullish_body: float
    bearish_body: float
    above_ema12: bool
    above_ema36: bool
    pullback_long: bool
    pullback_short: bool
    broke_high_6h: bool
    broke_high_12h: bool
    broke_high_24h: bool
    broke_low_6h: bool
    broke_low_12h: bool
    broke_low_24h: bool
    liquidity_24h: float


@dataclass(frozen=True)
class Snapshot:
    ts: int
    btc_ret_24h: float
    btc_close: float
    btc_ema_fast: float
    btc_ema_slow: float
    features: tuple[Feature, ...]


@dataclass(frozen=True)
class Config:
    universe_size: int = 50
    entry_style: str = "pullback"
    regime_momentum_min: float = 0.005
    regime_ema_spread_min: float = 0.002
    regime_confirm_hours: int = 6
    ret_6h_min: float = 0.02
    relative_24h_min: float = 0.02
    volume_ratio_min: float = 1.5
    candle_body_min: float = 0.005
    breakout_hours: int = 12
    atr_min: float = 0.005
    atr_max: float = 0.08
    stop_atr: float = 1.5
    target_atr: float = 3.0
    add_1_atr: float = 0.75
    add_2_atr: float = 1.5
    hold_hours: int = 9
    cooldown_hours: int = 12
    drawdown_pause_pct: float = 0.10
    drawdown_pause_hours: int = 24
    position_cap_usdt: float = 1000.0
    equity_allocation_pct: float = 0.75
    initial_fraction: float = 0.40
    add_fraction: float = 0.30


SPACE: dict[str, list[Any]] = {
    "universe_size": [30, 50, 80],
    "entry_style": ["breakout", "pullback"],
    "regime_momentum_min": [0.0, 0.005, 0.01, 0.015],
    "regime_ema_spread_min": [0.0, 0.002, 0.005, 0.01],
    "regime_confirm_hours": [3, 6, 12, 18],
    "ret_6h_min": [0.01, 0.02, 0.03, 0.05],
    "relative_24h_min": [0.0, 0.01, 0.02, 0.04],
    "volume_ratio_min": [1.0, 1.5, 2.0, 3.0],
    "candle_body_min": [0.002, 0.005, 0.01, 0.02],
    "breakout_hours": [6, 12, 24],
    "atr_min": [0.005, 0.01, 0.015],
    "atr_max": [0.04, 0.06, 0.08, 0.12],
    "stop_atr": [1.0, 1.5, 2.0],
    "target_atr": [2.0, 2.5, 3.0, 4.0],
    "add_1_atr": [0.5, 0.75, 1.0],
    "add_2_atr": [1.0, 1.5, 2.0],
    "hold_hours": [6, 9, 12],
    "cooldown_hours": [8, 12, 24],
    "drawdown_pause_pct": [0.08, 0.10, 0.15],
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
        if bp is None or bp < 96:
            continue
        btc_closes = [row.close for row in btc[bp - 95 : bp + 1]]
        btc_ret = btc[bp].close / btc[bp - 24].close - 1
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
            closes = [row.close for row in rows[pos - 47 : pos + 1]]
            if min(current.open, current.close, rows[pos - 24].close) <= 0:
                continue
            volumes = [row.quote_volume for row in rows[pos - 24 : pos] if row.quote_volume > 0]
            if len(volumes) < 20:
                continue
            avg_volume = statistics.fmean(volumes)
            ret24 = current.close / rows[pos - 24].close - 1
            prior6, prior12, prior24 = rows[pos - 6 : pos], rows[pos - 12 : pos], rows[pos - 24 : pos]
            ema12_value, ema36_value = ema(closes, 12), ema(closes, 36)
            features.append(Feature(
                symbol=symbol, close=current.close, high=current.high, low=current.low,
                ret_1h=current.close / rows[pos - 1].close - 1,
                ret_6h=current.close / rows[pos - 6].close - 1,
                ret_24h=ret24, relative_24h=ret24 - btc_ret,
                volume_ratio=current.quote_volume / avg_volume if avg_volume else 0.0,
                atr_pct=atr(rows, pos) / current.close,
                bullish_body=max(0.0, (current.close - current.open) / current.open),
                bearish_body=max(0.0, (current.open - current.close) / current.open),
                above_ema12=current.close > ema12_value,
                above_ema36=current.close > ema36_value,
                pullback_long=current.low <= ema12_value * 1.005 and current.close > ema12_value,
                pullback_short=current.high >= ema12_value * 0.995 and current.close < ema12_value,
                broke_high_6h=current.close > max(row.high for row in prior6),
                broke_high_12h=current.close > max(row.high for row in prior12),
                broke_high_24h=current.close > max(row.high for row in prior24),
                broke_low_6h=current.close < min(row.low for row in prior6),
                broke_low_12h=current.close < min(row.low for row in prior12),
                broke_low_24h=current.close < min(row.low for row in prior24),
                liquidity_24h=sum(max(row.quote_volume, 0.0) for row in rows[pos - 23 : pos + 1]),
            ))
        features.sort(key=lambda item: item.liquidity_24h, reverse=True)
        snapshots.append(Snapshot(
            ts=ts, btc_ret_24h=btc_ret, btc_close=btc[bp].close,
            btc_ema_fast=ema(btc_closes, 24), btc_ema_slow=ema(btc_closes, 72),
            features=tuple(features),
        ))
    return snapshots, indexes


def market_regime(snapshot: Snapshot, config: Config) -> str:
    ema_spread = snapshot.btc_ema_fast / snapshot.btc_ema_slow - 1
    if (
        snapshot.btc_close > snapshot.btc_ema_fast > snapshot.btc_ema_slow
        and snapshot.btc_ret_24h >= config.regime_momentum_min
        and ema_spread >= config.regime_ema_spread_min
    ):
        return "long"
    if (
        snapshot.btc_close < snapshot.btc_ema_fast < snapshot.btc_ema_slow
        and snapshot.btc_ret_24h <= -config.regime_momentum_min
        and ema_spread <= -config.regime_ema_spread_min
    ):
        return "short"
    return "flat"


def broke_level(item: Feature, direction: str, hours: int) -> bool:
    if direction == "long":
        return {6: item.broke_high_6h, 12: item.broke_high_12h, 24: item.broke_high_24h}[hours]
    return {6: item.broke_low_6h, 12: item.broke_low_12h, 24: item.broke_low_24h}[hours]


def select_candidate(snapshot: Snapshot, config: Config, direction: str):
    candidates = []
    for item in snapshot.features[: config.universe_size]:
        if not config.atr_min <= item.atr_pct <= config.atr_max:
            continue
        entry_pattern = (
            broke_level(item, direction, config.breakout_hours)
            if config.entry_style == "breakout"
            else (item.pullback_long if direction == "long" else item.pullback_short)
        )
        if item.volume_ratio < config.volume_ratio_min or not entry_pattern:
            continue
        if direction == "long":
            if item.ret_6h < config.ret_6h_min or item.relative_24h < config.relative_24h_min:
                continue
            if item.bullish_body < config.candle_body_min or not (item.above_ema12 and item.above_ema36):
                continue
            score = item.relative_24h + 0.5 * item.ret_6h + 0.01 * min(item.volume_ratio, 10)
        else:
            if item.ret_6h > -config.ret_6h_min or item.relative_24h > -config.relative_24h_min:
                continue
            if item.bearish_body < config.candle_body_min or item.above_ema12 or item.above_ema36:
                continue
            score = -item.relative_24h - 0.5 * item.ret_6h + 0.01 * min(item.volume_ratio, 10)
        candidates.append((score, item))
    return max(candidates, default=(None, None), key=lambda pair: pair[0])[1]


def simulate_position(index: dict[int, Candle], signal_ts: int, direction: str, atr_pct: float,
                      max_notional: float, config: Config):
    entry_ts = signal_ts + HOUR_MS
    first_bar = index.get(entry_ts)
    if first_bar is None or first_bar.open <= 0:
        return None
    sign = 1 if direction == "long" else -1
    initial_price = first_bar.open
    atr_abs = initial_price * atr_pct
    fractions = [config.initial_fraction, config.add_fraction, config.add_fraction]
    notionals = [max_notional * fractions[0]]
    prices = [initial_price]
    entry_fees = notionals[0] * ONE_WAY_COST
    add_levels = [initial_price + sign * config.add_1_atr * atr_abs,
                  initial_price + sign * config.add_2_atr * atr_abs]
    hard_stop = initial_price - sign * config.stop_atr * atr_abs
    target = initial_price + sign * config.target_atr * atr_abs
    next_add = 0
    exit_price, exit_ts, reason = initial_price, entry_ts, "time_exit"
    for offset in range(config.hold_hours):
        ts = entry_ts + offset * HOUR_MS
        bar = index.get(ts)
        if bar is None:
            return None
        stop_hit = bar.low <= hard_stop if direction == "long" else bar.high >= hard_stop
        if stop_hit:
            if direction == "long":
                exit_price = min(hard_stop, bar.open) if bar.open <= hard_stop else hard_stop
            else:
                exit_price = max(hard_stop, bar.open) if bar.open >= hard_stop else hard_stop
            exit_ts, reason = ts, "stop_loss"
            break
        while next_add < 2:
            level = add_levels[next_add]
            hit = bar.high >= level if direction == "long" else bar.low <= level
            if not hit:
                break
            add_notional = max_notional * fractions[next_add + 1]
            notionals.append(add_notional)
            prices.append(level)
            entry_fees += add_notional * ONE_WAY_COST
            next_add += 1
            if next_add == 1:
                hard_stop = initial_price
            else:
                hard_stop = initial_price + sign * 0.5 * atr_abs
        target_hit = bar.high >= target if direction == "long" else bar.low <= target
        if target_hit:
            exit_price, exit_ts, reason = target, ts, "take_profit"
            break
        exit_price, exit_ts = bar.close, ts
    total_notional = sum(notionals)
    gross_pnl = sum(notional * sign * (exit_price - price) / price for notional, price in zip(notionals, prices))
    fees = entry_fees + total_notional * ONE_WAY_COST
    return {
        "direction": direction, "entry_ts": entry_ts, "exit_ts": exit_ts,
        "initial_entry": initial_price, "average_entry": sum(n * p for n, p in zip(notionals, prices)) / total_notional,
        "exit": exit_price, "reason": reason, "adds": len(notionals) - 1,
        "position_notional_usdt": total_notional, "gross_pnl_usdt": gross_pnl,
        "fees_usdt": fees, "pnl_usdt": gross_pnl - fees,
    }


def evaluate(config: Config, snapshots, indexes, start: datetime, end: datetime, include_trades: bool = False):
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    equity = peak = INITIAL_EQUITY
    max_drawdown = 0.0
    next_signal_ts = pause_until = start_ms
    last_regime = "flat"
    regime_streak = 0
    pnls, trades = [], []
    direction_counts = {"long": 0, "short": 0}
    reasons = {"take_profit": 0, "stop_loss": 0, "time_exit": 0}
    for snapshot in snapshots:
        if snapshot.ts < start_ms or snapshot.ts >= end_ms:
            continue
        direction = market_regime(snapshot, config)
        if direction != "flat" and direction == last_regime:
            regime_streak += 1
        elif direction != "flat":
            last_regime, regime_streak = direction, 1
        else:
            last_regime, regime_streak = "flat", 0
        if snapshot.ts < max(next_signal_ts, pause_until):
            continue
        if direction == "flat" or regime_streak < config.regime_confirm_hours:
            continue
        selected = select_candidate(snapshot, config, direction)
        if selected is None:
            continue
        max_notional = min(config.position_cap_usdt, max(equity, 0.0) * config.equity_allocation_pct * 3)
        result = simulate_position(indexes[selected.symbol], snapshot.ts, direction, selected.atr_pct,
                                   max_notional, config)
        if result is None or result["exit_ts"] >= end_ms:
            continue
        equity += result["pnl_usdt"]
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak if peak else 1.0
        max_drawdown = max(max_drawdown, drawdown)
        if drawdown >= config.drawdown_pause_pct:
            pause_until = result["exit_ts"] + config.drawdown_pause_hours * HOUR_MS
        pnls.append(result["pnl_usdt"])
        direction_counts[direction] += 1
        reasons[result["reason"]] += 1
        next_signal_ts = result["exit_ts"] + config.cooldown_hours * HOUR_MS
        if include_trades:
            trades.append({
                "signal_ts": snapshot.ts, "symbol": selected.symbol,
                "btc_24h_pct": snapshot.btc_ret_24h * 100,
                "ret_6h_pct": selected.ret_6h * 100, "ret_24h_pct": selected.ret_24h * 100,
                "relative_24h_pct": selected.relative_24h * 100,
                "volume_ratio": selected.volume_ratio, "atr_pct": selected.atr_pct * 100,
                "equity_usdt": equity, **result,
            })
    gross_profit = sum(x for x in pnls if x > 0)
    gross_loss = -sum(x for x in pnls if x < 0)
    return {
        "config": asdict(config), "initial_equity": INITIAL_EQUITY, "final_equity": equity,
        "total_pnl_usdt": equity - INITIAL_EQUITY, "return_pct": (equity / INITIAL_EQUITY - 1) * 100,
        "max_drawdown_pct": max_drawdown * 100, "trades": len(pnls),
        "win_rate_pct": sum(x > 0 for x in pnls) / len(pnls) * 100 if pnls else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "direction_counts": direction_counts, "exit_reasons": reasons,
        "ruined": equity <= 0, "trades_detail": trades if include_trades else None,
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
        "flat_windows": sum(x == 0 for x in returns), "mean_return_pct": statistics.fmean(returns),
        "median_return_pct": statistics.median(returns), "p10_return_pct": percentile(returns, 0.10),
        "worst_return_pct": min(returns), "best_return_pct": max(returns),
        "median_drawdown_pct": statistics.median(drawdowns), "worst_drawdown_pct": max(drawdowns),
        "total_trades": sum(trades), "median_trades": statistics.median(trades),
        "window_returns_pct": returns,
    }


def generate_configs(count: int, seed: int):
    rng = random.Random(seed)
    configs = {Config()}
    fields = list(SPACE)
    while len(configs) < count:
        base = asdict(Config())
        for field in fields:
            base[field] = rng.choice(SPACE[field])
        if base["add_2_atr"] <= base["add_1_atr"]:
            continue
        configs.add(Config(**base))
    return list(configs)


def compact(metrics: dict[str, Any]):
    return {k: v for k, v in metrics.items() if k != "trades_detail"}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-cache", type=Path, required=True)
    parser.add_argument("--final-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config-count", type=int, default=5000)
    parser.add_argument("--shortlist", type=int, default=300)
    parser.add_argument("--window-count", type=int, default=48)
    parser.add_argument("--seed", type=int, default=20260816)
    return parser.parse_args()


def main():
    args = parse_args()
    started = time.monotonic()
    ts, tc, tm = load_cache(args.train_cache)
    fs, fc, fm = load_cache(args.final_cache)
    snapshots, indexes = build_snapshots(ts, tc)
    final_snapshots, final_indexes = build_snapshots(fs, fc)
    history_start = datetime.fromisoformat(tm["analysis_start_utc"]) + timedelta(days=3)
    history_end = datetime.fromisoformat(tm["end_utc"]) + timedelta(hours=1)
    validation_start = history_end - timedelta(days=30)
    windows = random_windows(history_start, validation_start, args.window_count, 7, args.seed)
    aggregate = []
    for config in generate_configs(args.config_count, args.seed):
        metrics = evaluate(config, snapshots, indexes, history_start, validation_start)
        if metrics["trades"] < 20 or metrics["ruined"]:
            continue
        score = metrics["return_pct"] - metrics["max_drawdown_pct"]
        aggregate.append((score, config, metrics))
    aggregate.sort(key=lambda x: x[0], reverse=True)
    shortlist_configs = []
    per_style = max(1, args.shortlist // len(SPACE["entry_style"]))
    for style in SPACE["entry_style"]:
        style_configs = [x[1] for x in aggregate if x[1].entry_style == style]
        shortlist_configs.extend(style_configs[:per_style])
    robust = []
    for config in shortlist_configs:
        metrics = robust_metrics(config, windows, snapshots, indexes)
        if metrics["total_trades"] < 40 or metrics["positive_window_rate_pct"] < 52:
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
        raise RuntimeError("no regime-rotation candidate passed validation")
    selected = validated[0]
    final_start, final_end = datetime(2026, 8, 1, tzinfo=LOCAL_TZ), datetime(2026, 8, 16, tzinfo=LOCAL_TZ)
    final_result = evaluate(selected[1], final_snapshots, final_indexes, final_start, final_end, True)
    result = {
        "method": {"strategy": "bidirectional_regime_rotation", "generated_configs": args.config_count,
                   "selection_uses_august": False, "one_way_cost_pct": ONE_WAY_COST * 100,
                   "same_bar_assumption": "stop_before_add_before_target"},
        "periods": {"history_start": history_start.isoformat(), "training_end": validation_start.isoformat(),
                    "validation_start": validation_start.isoformat(), "validation_end": history_end.isoformat(),
                    "final_start": final_start.isoformat(), "final_end": final_end.isoformat()},
        "selected_config": asdict(selected[1]), "selected_random_7d": selected[2],
        "selected_later_validation": compact(selected[3]), "selected_august": final_result,
        "top_validated": [{"score": score, "config": asdict(config), "random_7d": random_result,
                           "validation": compact(validation)}
                          for score, config, random_result, validation in validated[:20]],
        "runtime_seconds": time.monotonic() - started, "data": {"training": tm, "final": fm},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    summary = dict(result)
    summary.pop("top_validated")
    summary["selected_random_7d"] = {k: v for k, v in selected[2].items() if k != "window_returns_pct"}
    summary["selected_august"] = compact(final_result)
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
