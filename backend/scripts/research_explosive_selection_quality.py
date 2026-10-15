#!/usr/bin/env python3
"""Optimize only the coin-selection layer of explosive momentum.

Exit parameters stay identical to the live baseline.  The final August cache is
never used for parameter selection; it is reported only after a candidate has
passed the historical training and later-validation gates.
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
from optimize_explosive_momentum import BENCHMARKS, Config, simulate_exit


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
ROUND_TRIP_COST = 0.0012
INITIAL_CAPITAL = 1000.0
POSITION_CAP = 1000.0
EXIT_CONFIG = Config(
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


@dataclass(frozen=True)
class Feature:
    symbol: str
    liquidity_rank: int
    ret_1h: float
    ret_4h: float
    ret_24h: float
    pre_3h: float
    vol_ratio: float
    upper_wick: float
    close_location: float


@dataclass(frozen=True)
class Snapshot:
    ts: int
    features: tuple[Feature, ...]
    btc_4h: float = 0.0
    btc_24h: float = 0.0
    breadth_1h: float = 0.0
    breadth_4h: float = 0.0
    market_pump_count: int = 0


@dataclass(frozen=True)
class Selector:
    min_signal: float
    max_signal: float | None
    min_gap: float
    min_vol_ratio: float
    max_vol_ratio: float | None
    max_ret_4h: float | None
    max_ret_24h: float | None
    min_pre_3h: float
    max_upper_wick: float | None
    min_close_location: float
    universe_size: int
    ranking: str
    min_btc_4h: float = -1.0
    max_btc_4h: float | None = None
    min_btc_24h: float = -1.0
    min_breadth_1h: float = 0.0
    min_breadth_4h: float = 0.0
    max_market_pumps: int | None = None


BASELINE = Selector(0.04, None, 0.01, 3.0, None, None, None, -1.0, None, 0.0, 80, "ret_1h")
SPACE: dict[str, list[Any]] = {
    "min_signal": [0.04, 0.05, 0.06, 0.07],
    "max_signal": [0.10, 0.12, 0.15, None],
    "min_gap": [0.0, 0.01, 0.02, 0.03],
    "min_vol_ratio": [2.0, 3.0, 4.0],
    "max_vol_ratio": [8.0, 10.0, 15.0, 20.0, 50.0],
    "max_ret_4h": [0.15, 0.20, 0.30, None],
    "max_ret_24h": [0.30, 0.40, 0.60, None],
    "min_pre_3h": [0.0, 0.01, 0.02, 0.03],
    "max_upper_wick": [0.02, 0.03, 0.04, 0.06, None],
    "min_close_location": [0.65, 0.70, 0.75, 0.80, 0.85],
    "universe_size": [30, 40, 50, 80],
    "ranking": ["ret_1h", "clean_momentum", "continuation"],
}


def build_snapshots(symbols: list[str], candles: dict[str, list[Candle]]):
    indexes = {symbol: {row.ts: row for row in rows} for symbol, rows in candles.items()}
    alt_symbols = [symbol for symbol in symbols if symbol not in BENCHMARKS]
    positions = {symbol: {row.ts: i for i, row in enumerate(candles[symbol])} for symbol in alt_symbols}
    btc_rows = candles["BTC-USDT-SWAP"]
    btc_positions = {row.ts: i for i, row in enumerate(btc_rows)}
    all_ts = sorted({row.ts for symbol in alt_symbols for row in candles[symbol]})
    snapshots: list[Snapshot] = []
    for ts in all_ts:
        btc_pos = btc_positions.get(ts)
        if btc_pos is None or btc_pos < 24 or btc_rows[btc_pos - 24].close <= 0:
            continue
        btc_4h = btc_rows[btc_pos].close / btc_rows[btc_pos - 4].close - 1
        btc_24h = btc_rows[btc_pos].close / btc_rows[btc_pos - 24].close - 1
        raw: list[tuple[float, Feature]] = []
        for symbol in alt_symbols:
            pos = positions[symbol].get(ts)
            rows = candles[symbol]
            if pos is None or pos < 24 or rows[pos - 4].close <= 0:
                continue
            if any(rows[i].ts - rows[i - 1].ts != HOUR_MS for i in range(pos - 23, pos + 1)):
                continue
            current = rows[pos]
            history = rows[pos - 24:pos]
            volumes = [row.quote_volume for row in history if row.quote_volume > 0]
            if len(volumes) < 20:
                continue
            avg_volume = statistics.fmean(volumes)
            candle_range = current.high - current.low
            liquidity = sum(volumes) + max(current.quote_volume, 0.0)
            feature = Feature(
                symbol=symbol,
                liquidity_rank=0,
                ret_1h=current.close / rows[pos - 1].close - 1,
                ret_4h=current.close / rows[pos - 4].close - 1,
                ret_24h=current.close / rows[pos - 24].close - 1,
                pre_3h=rows[pos - 1].close / rows[pos - 4].close - 1,
                vol_ratio=current.quote_volume / avg_volume if avg_volume else 0.0,
                upper_wick=max(0.0, current.high - max(current.open, current.close)) / current.open,
                close_location=(current.close - current.low) / candle_range if candle_range > 0 else 0.5,
            )
            raw.append((liquidity, feature))
        raw.sort(key=lambda pair: pair[0], reverse=True)
        ranked = tuple(Feature(**{**asdict(item), "liquidity_rank": rank}) for rank, (_, item) in enumerate(raw, 1))
        liquid = ranked[:80]
        breadth_1h = sum(item.ret_1h > 0 for item in liquid) / len(liquid) if liquid else 0.0
        breadth_4h = sum(item.ret_4h > 0 for item in liquid) / len(liquid) if liquid else 0.0
        market_pumps = sum(item.ret_1h >= 0.04 and item.vol_ratio >= 3.0 for item in liquid)
        snapshots.append(Snapshot(ts, ranked, btc_4h, btc_24h, breadth_1h, breadth_4h, market_pumps))
    return snapshots, indexes


def rank_value(item: Feature, ranking: str) -> float:
    if ranking == "clean_momentum":
        return item.ret_1h + 0.35 * item.pre_3h - item.upper_wick + 0.015 * item.close_location
    if ranking == "continuation":
        return item.ret_4h - item.upper_wick + 0.01 * item.close_location
    return item.ret_1h


def select(snapshot: Snapshot, selector: Selector) -> Feature | None:
    if not (
        snapshot.btc_4h >= selector.min_btc_4h
        and (selector.max_btc_4h is None or snapshot.btc_4h <= selector.max_btc_4h)
        and snapshot.btc_24h >= selector.min_btc_24h
        and snapshot.breadth_1h >= selector.min_breadth_1h
        and snapshot.breadth_4h >= selector.min_breadth_4h
        and (selector.max_market_pumps is None or snapshot.market_pump_count <= selector.max_market_pumps)
    ):
        return None
    candidates = [
        item for item in snapshot.features[:selector.universe_size]
        if item.ret_1h >= selector.min_signal
        and (selector.max_signal is None or item.ret_1h <= selector.max_signal)
        and item.vol_ratio >= selector.min_vol_ratio
        and (selector.max_vol_ratio is None or item.vol_ratio <= selector.max_vol_ratio)
        and (selector.max_ret_4h is None or item.ret_4h <= selector.max_ret_4h)
        and (selector.max_ret_24h is None or item.ret_24h <= selector.max_ret_24h)
        and item.pre_3h >= selector.min_pre_3h
        and (selector.max_upper_wick is None or item.upper_wick <= selector.max_upper_wick)
        and item.close_location >= selector.min_close_location
    ]
    if not candidates:
        return None
    by_signal = sorted(candidates, key=lambda x: x.ret_1h, reverse=True)
    if len(by_signal) > 1 and by_signal[0].ret_1h - by_signal[1].ret_1h < selector.min_gap:
        return None
    return max(candidates, key=lambda x: rank_value(x, selector.ranking))


def evaluate(
    selector: Selector,
    snapshots,
    indexes,
    start: datetime,
    end: datetime,
    include_trades: bool = False,
    position_cap_usdt: float = POSITION_CAP,
    balance_usage_fraction: float = 0.75,
    exit_config: Config = EXIT_CONFIG,
) -> dict[str, Any]:
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    equity = peak = INITIAL_CAPITAL
    max_dd = 0.0
    next_signal = start_ms
    last_entry: dict[str, int] = {}
    pnls: list[float] = []
    returns: list[float] = []
    trades_detail: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if snapshot.ts < start_ms or snapshot.ts >= end_ms or snapshot.ts < next_signal:
            continue
        top = select(snapshot, selector)
        if top is None:
            continue
        entry_ts = snapshot.ts + HOUR_MS
        if entry_ts - last_entry.get(top.symbol, -10**18) < exit_config.cooldown_hours * HOUR_MS:
            continue
        outcome = simulate_exit(indexes[top.symbol], snapshot.ts, exit_config)
        if outcome is None or outcome["exit_ts"] >= end_ms:
            continue
        net_return = outcome["gross_pct"] - ROUND_TRIP_COST
        notional = min(
            position_cap_usdt,
            max(equity, 0.0) * balance_usage_fraction * exit_config.leverage,
        )
        pnl = notional * net_return
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 1.0)
        pnls.append(pnl)
        returns.append(net_return)
        if include_trades:
            trades_detail.append({
                "signal_ts": snapshot.ts,
                "entry_ts": outcome["entry_ts"],
                "exit_ts": outcome["exit_ts"],
                "symbol": top.symbol,
                "entry_price": outcome["entry"],
                "exit_price": outcome["exit"],
                "exit_reason": outcome["reason"],
                "signal_1h_pct": top.ret_1h * 100,
                "signal_4h_pct": top.ret_4h * 100,
                "signal_24h_pct": top.ret_24h * 100,
                "pre_3h_pct": top.pre_3h * 100,
                "volume_ratio": top.vol_ratio,
                "upper_wick_pct": top.upper_wick * 100,
                "close_location_pct": top.close_location * 100,
                "liquidity_rank": top.liquidity_rank,
                "btc_4h_pct": snapshot.btc_4h * 100,
                "btc_24h_pct": snapshot.btc_24h * 100,
                "market_pump_count": snapshot.market_pump_count,
                "position_notional_usdt": notional,
                "net_return_pct": net_return * 100,
                "pnl_usdt": pnl,
                "equity_after_usdt": equity,
            })
        last_entry[top.symbol] = entry_ts
        next_signal = outcome["exit_ts"]
    gross_profit = sum(x for x in pnls if x > 0)
    gross_loss = -sum(x for x in pnls if x < 0)
    return {
        "return_pct": (equity / INITIAL_CAPITAL - 1) * 100,
        "max_drawdown_pct": max_dd * 100,
        "trades": len(pnls),
        "win_rate_pct": sum(x > 0 for x in pnls) / len(pnls) * 100 if pnls else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "average_trade_pct": statistics.fmean(returns) * 100 if returns else 0.0,
        "trades_detail": trades_detail if include_trades else None,
    }


def percentile(values: list[float], q: float) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    pos = (len(values) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(values) - 1)
    return values[lo] * (hi - pos) + values[hi] * (pos - lo)


def window_summary(selector, windows, snapshots, indexes):
    rows = [evaluate(selector, snapshots, indexes, start, end) for start, end in windows]
    returns = [x["return_pct"] for x in rows]
    return {
        "positive_window_rate_pct": sum(x > 0 for x in returns) / len(rows) * 100,
        "median_return_pct": statistics.median(returns),
        "p10_return_pct": percentile(returns, 0.10),
        "worst_return_pct": min(returns),
        "median_drawdown_pct": statistics.median(x["max_drawdown_pct"] for x in rows),
        "worst_drawdown_pct": max(x["max_drawdown_pct"] for x in rows),
        "median_win_rate_pct": statistics.median(x["win_rate_pct"] for x in rows),
        "median_trades": statistics.median(x["trades"] for x in rows),
    }


def random_windows(start, end, count, days, seed):
    latest = end - timedelta(days=days)
    span = int((latest - start).total_seconds() // 3600)
    rng = random.Random(seed)
    offsets = {0, span}
    while len(offsets) < count:
        offsets.add(rng.randrange(span + 1))
    return [(start + timedelta(hours=x), start + timedelta(hours=x, days=days)) for x in sorted(offsets)]


def generate(count: int, seed: int):
    rng = random.Random(seed)
    result = {BASELINE}
    keys = list(SPACE)
    while len(result) < count:
        result.add(Selector(**{key: rng.choice(SPACE[key]) for key in keys}))
    return list(result)


def main():
    args = parse_args()
    started = time.monotonic()
    train_symbols, train_candles, train_meta = load_cache(args.train_cache)
    final_symbols, final_candles, _ = load_cache(args.final_cache)
    train_snapshots, train_indexes = build_snapshots(train_symbols, train_candles)
    final_snapshots, final_indexes = build_snapshots(final_symbols, final_candles)
    history_start = datetime.fromisoformat(train_meta["analysis_start_utc"])
    history_end = datetime.fromisoformat(train_meta["end_utc"]) + timedelta(hours=1)
    validation_start = history_end - timedelta(days=30)
    final_start = datetime.strptime(args.final_start, "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
    final_end = datetime.strptime(args.final_end, "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
    windows = random_windows(history_start, validation_start, 24, 7, args.seed)

    training = []
    for selector in generate(args.config_count, args.seed):
        metric = evaluate(selector, train_snapshots, train_indexes, history_start, validation_start)
        if metric["trades"] < 35 or (metric["profit_factor"] or 0) < 1.0:
            continue
        # Accuracy matters, but require positive expectancy and penalize drawdown.
        score = metric["return_pct"] + 0.8 * metric["win_rate_pct"] - 0.7 * metric["max_drawdown_pct"]
        training.append((score, selector, metric))
    training.sort(key=lambda x: x[0], reverse=True)

    robust = []
    for _, selector, train_metric in training[:args.shortlist]:
        random_metric = window_summary(selector, windows, train_snapshots, train_indexes)
        if (random_metric["positive_window_rate_pct"] >= 58 and random_metric["p10_return_pct"] >= -18
                and random_metric["worst_drawdown_pct"] <= 35 and random_metric["median_trades"] >= 2):
            validation = evaluate(selector, train_snapshots, train_indexes, validation_start, history_end)
            if (validation["trades"] >= 8 and validation["return_pct"] > 0
                    and (validation["profit_factor"] or 0) >= 1.10 and validation["max_drawdown_pct"] <= 30):
                score = (validation["return_pct"] + validation["win_rate_pct"]
                         + random_metric["median_return_pct"] + 0.5 * random_metric["p10_return_pct"]
                         - validation["max_drawdown_pct"])
                robust.append((score, selector, train_metric, random_metric, validation))
    if not robust:
        raise RuntimeError("No selector passed the robustness gates")
    robust.sort(key=lambda x: x[0], reverse=True)
    _, selected, selected_train, selected_random, selected_validation = robust[0]

    def package(selector):
        return {
            "selector": asdict(selector),
            "training": evaluate(selector, train_snapshots, train_indexes, history_start, validation_start),
            "random_7d": window_summary(selector, windows, train_snapshots, train_indexes),
            "later_validation": evaluate(selector, train_snapshots, train_indexes, validation_start, history_end),
            "final_august_holdout": evaluate(selector, final_snapshots, final_indexes, final_start, final_end),
        }

    result = {
        "method": {
            "selection_only": True,
            "fixed_exit": asdict(EXIT_CONFIG),
            "initial_capital_usdt": INITIAL_CAPITAL,
            "position_cap_usdt": POSITION_CAP,
            "round_trip_cost_pct": ROUND_TRIP_COST * 100,
            "final_holdout_used_for_selection": False,
            "generated_candidates": args.config_count,
            "training_eligible": len(training),
            "validation_passed": len(robust),
            "runtime_seconds": time.monotonic() - started,
        },
        "periods": {
            "training": [history_start.isoformat(), validation_start.isoformat()],
            "later_validation": [validation_start.isoformat(), history_end.isoformat()],
            "final_holdout": [final_start.isoformat(), final_end.isoformat()],
        },
        "baseline": package(BASELINE),
        "selected": package(selected),
        "top_validated": [
            {"score": score, "selector": asdict(sel), "training": tm, "random_7d": rm, "later_validation": vm}
            for score, sel, tm, rm, vm in robust[:20]
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "top_validated"}, ensure_ascii=False, indent=2))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-cache", type=Path, required=True)
    parser.add_argument("--final-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config-count", type=int, default=3000)
    parser.add_argument("--shortlist", type=int, default=300)
    parser.add_argument("--seed", type=int, default=20260816)
    parser.add_argument("--final-start", default="2026-08-01 00:00")
    parser.add_argument("--final-end", default="2026-08-16 00:00")
    return parser.parse_args()


if __name__ == "__main__":
    main()
