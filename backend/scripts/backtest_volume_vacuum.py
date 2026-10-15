#!/usr/bin/env python3
"""Research backtest for volume-profile acceptance and failed-P vacuum setups.

The OKX 1m candle feed does not expose true volume-at-price.  This script uses
each minute candle's typical price as a deterministic approximation, bins quote
volume by price, and computes POC/VAH/VAL from that profile.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from backtest_altcoin_pump_short import HOUR_MS, OKX_API, Candle, load_cache, request_json
from optimize_explosive_momentum import Config, Feature, Snapshot, build_snapshots, evaluate, simulate_exit


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
MINUTE_MS = 60_000
ROUND_TRIP_COST = 0.0012


@dataclass(frozen=True)
class Profile:
    low: float
    high: float
    poc: float
    vah: float
    val: float
    poc_position: float
    bins: int


def parse_local(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)


def local_time(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, LOCAL_TZ).strftime("%Y-%m-%d %H:%M")


def raw_candidates(
    snapshots: list[Snapshot],
    start_ms: int,
    end_ms: int,
    config: Config,
) -> list[dict[str, Any]]:
    result = []
    for snapshot in snapshots:
        if snapshot.ts < start_ms or snapshot.ts >= end_ms:
            continue
        if config.market_filter == "btc_4h_positive" and snapshot.btc_4h_return <= 0:
            continue
        universe = snapshot.liquid_features[: config.universe_size]
        candidates = [
            item for item in universe
            if item.ret_1h >= config.min_signal and item.vol_ratio >= config.min_vol_ratio
        ]
        candidates.sort(key=lambda item: item.ret_1h, reverse=True)
        if not candidates:
            continue
        if len(candidates) > 1 and candidates[0].ret_1h - candidates[1].ret_1h < config.min_gap:
            continue
        top: Feature = candidates[0]
        result.append({
            "signal_ts": snapshot.ts,
            "symbol": top.symbol,
            "signal_pct": top.ret_1h * 100,
            "vol_ratio": top.vol_ratio,
            "btc_4h_pct": snapshot.btc_4h_return * 100,
        })
    return result


async def fetch_1m_window(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, float]]:
    cursor = end_ms + MINUTE_MS
    rows: dict[int, dict[str, float]] = {}
    while cursor > start_ms:
        payload = await request_json(
            client,
            "/market/history-candles",
            {"instId": symbol, "bar": "1m", "limit": "300", "after": str(cursor)},
            semaphore,
        )
        batch = payload.get("data") or []
        if not batch:
            break
        oldest = cursor
        for row in batch:
            ts = int(row[0])
            oldest = min(oldest, ts)
            if start_ms <= ts <= end_ms and str(row[8]) == "1":
                rows[ts] = {
                    "ts": ts,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "quote_volume": float(row[7]),
                }
        if oldest >= cursor or oldest <= start_ms:
            break
        cursor = oldest
    return sorted(rows.values(), key=lambda item: item["ts"])


async def obtain_minute_windows(
    events: list[dict[str, Any]],
    cache_path: Path,
    proxy: str | None,
    concurrency: int,
) -> tuple[dict[str, list[dict[str, float]]], dict[str, str]]:
    cached: dict[str, list[dict[str, float]]] = {}
    if cache_path.exists():
        cached = json.loads(cache_path.read_text()).get("windows", {})
    failures: dict[str, str] = {}
    missing = [event for event in events if f"{event['symbol']}:{event['signal_ts']}" not in cached]
    if not missing:
        return cached, failures

    semaphore = asyncio.Semaphore(concurrency)
    client_kwargs: dict[str, Any] = {
        "base_url": OKX_API,
        "headers": {"User-Agent": "OKK-volume-vacuum-backtest/1.0"},
        "timeout": httpx.Timeout(25.0),
        "trust_env": False,
    }
    if proxy:
        client_kwargs["proxy"] = proxy
    async with httpx.AsyncClient(**client_kwargs) as client:
        async def load(event: dict[str, Any]):
            key = f"{event['symbol']}:{event['signal_ts']}"
            start_ms = event["signal_ts"] - 7 * HOUR_MS
            end_ms = event["signal_ts"] + 10 * HOUR_MS
            try:
                return key, await fetch_1m_window(
                    client, semaphore, event["symbol"], start_ms, end_ms
                ), None
            except Exception as exc:  # research cache records partial failures
                return key, [], str(exc)

        completed = await asyncio.gather(*(load(event) for event in missing))
    for key, rows, error in completed:
        if error:
            failures[key] = error
        elif rows:
            cached[key] = rows
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"windows": cached}, separators=(",", ":")))
    return cached, failures


def volume_profile(rows: list[dict[str, float]], bins: int = 48) -> Profile | None:
    if len(rows) < 360:
        return None
    low = min(row["low"] for row in rows)
    high = max(row["high"] for row in rows)
    if low <= 0 or high <= low:
        return None
    width = (high - low) / bins
    volumes = [0.0] * bins
    for row in rows:
        typical = (row["high"] + row["low"] + row["close"]) / 3
        index = min(bins - 1, max(0, int((typical - low) / width)))
        volumes[index] += max(0.0, row["quote_volume"])
    total = sum(volumes)
    if total <= 0:
        return None
    poc_index = max(range(bins), key=volumes.__getitem__)
    included = {poc_index}
    accumulated = volumes[poc_index]
    left, right = poc_index - 1, poc_index + 1
    while accumulated < total * 0.70 and (left >= 0 or right < bins):
        left_volume = volumes[left] if left >= 0 else -1
        right_volume = volumes[right] if right < bins else -1
        if right_volume > left_volume:
            included.add(right)
            accumulated += max(0.0, right_volume)
            right += 1
        else:
            included.add(left)
            accumulated += max(0.0, left_volume)
            left -= 1
    center = lambda index: low + (index + 0.5) * width
    return Profile(
        low=low,
        high=high,
        poc=center(poc_index),
        vah=low + (max(included) + 1) * width,
        val=low + min(included) * width,
        poc_position=(center(poc_index) - low) / (high - low),
        bins=bins,
    )


def profile_for_event(
    event: dict[str, Any],
    windows: dict[str, list[dict[str, float]]],
) -> tuple[Profile | None, list[dict[str, float]]]:
    key = f"{event['symbol']}:{event['signal_ts']}"
    all_rows = windows.get(key, [])
    signal_end = event["signal_ts"] + HOUR_MS
    profile_rows = [
        row for row in all_rows
        if signal_end - 8 * HOUR_MS <= row["ts"] < signal_end
    ]
    return volume_profile(profile_rows), all_rows


def summarize_trades(trades: list[dict[str, Any]], initial_capital: float = 1000.0) -> dict[str, Any]:
    capital = initial_capital
    peak = initial_capital
    max_drawdown = 0.0
    for trade in trades:
        notional = min(1000.0, max(0.0, capital) * 0.75 * 3)
        pnl = notional * trade["net_return"]
        trade["position_notional_usd"] = notional
        trade["pnl_usdt"] = pnl
        capital += pnl
        peak = max(peak, capital)
        max_drawdown = max(max_drawdown, (peak - capital) / peak if peak else 1.0)
    wins = [trade for trade in trades if trade["net_return"] > 0]
    return {
        "initial_capital": initial_capital,
        "final_capital": capital,
        "total_pnl_usdt": capital - initial_capital,
        "return_pct": (capital / initial_capital - 1) * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "trades": len(trades),
        "win_rate_pct": len(wins) / len(trades) * 100 if trades else 0.0,
        "average_return_pct": statistics.fmean(
            trade["net_return"] for trade in trades
        ) * 100 if trades else 0.0,
    }


def run_acceptance_long(
    events: list[dict[str, Any]],
    windows: dict[str, list[dict[str, float]]],
    indexes: dict[str, dict[int, Candle]],
    config: Config,
    end_ms: int,
    acceptance_level: str = "vah",
    max_high_pullback_pct: float = 0.03,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, int]]:
    trades = []
    rejected = {"missing_profile": 0, "below_profile_level": 0, "high_pullback": 0, "overlap": 0}
    next_signal_ts = 0
    last_entry: dict[str, int] = {}
    for event in events:
        signal_ts = event["signal_ts"]
        entry_ts = signal_ts + HOUR_MS
        if signal_ts < next_signal_ts:
            rejected["overlap"] += 1
            continue
        profile, _ = profile_for_event(event, windows)
        signal_bar = indexes[event["symbol"]].get(signal_ts)
        entry_bar = indexes[event["symbol"]].get(entry_ts)
        if profile is None or signal_bar is None or entry_bar is None:
            rejected["missing_profile"] += 1
            continue
        required_level = profile.vah if acceptance_level == "vah" else profile.poc
        # Match live strategy: profile acceptance is evaluated at scan time
        # with the completed signal candle's current/close price. The order is
        # then modeled at the following hour's open.
        acceptance_price = signal_bar.close
        if acceptance_price < required_level:
            rejected["below_profile_level"] += 1
            continue
        pullback = 1 - acceptance_price / signal_bar.high if signal_bar.high > 0 else 1
        if pullback > max_high_pullback_pct:
            rejected["high_pullback"] += 1
            continue
        if entry_ts - last_entry.get(event["symbol"], -10**18) < config.cooldown_hours * HOUR_MS:
            continue
        exit_info = simulate_exit(indexes[event["symbol"]], signal_ts, config)
        if exit_info is None or exit_info["exit_ts"] >= end_ms:
            continue
        net_return = exit_info["gross_pct"] - ROUND_TRIP_COST
        trades.append({
            **event,
            **exit_info,
            "entry_time": local_time(exit_info["entry_ts"]),
            "exit_time": local_time(exit_info["exit_ts"]),
            "net_return": net_return,
            "profile": asdict(profile),
            "profile_acceptance_price": acceptance_price,
            "pullback_from_high_pct": pullback * 100,
        })
        next_signal_ts = exit_info["exit_ts"]
        last_entry[event["symbol"]] = entry_ts
    return summarize_trades(trades), trades, rejected


def five_minute_bars(rows: list[dict[str, float]], start_ms: int, end_ms: int) -> list[dict[str, float]]:
    groups: dict[int, list[dict[str, float]]] = {}
    for row in rows:
        if start_ms <= row["ts"] < end_ms:
            bucket = row["ts"] // (5 * MINUTE_MS) * (5 * MINUTE_MS)
            groups.setdefault(bucket, []).append(row)
    result = []
    for ts, items in sorted(groups.items()):
        items.sort(key=lambda item: item["ts"])
        if len(items) < 4:
            continue
        result.append({
            "ts": ts,
            "open": items[0]["open"],
            "high": max(item["high"] for item in items),
            "low": min(item["low"] for item in items),
            "close": items[-1]["close"],
        })
    return result


def failed_p_trade(
    event: dict[str, Any],
    profile: Profile,
    rows: list[dict[str, float]],
) -> dict[str, Any] | None:
    if profile.poc_position < 0.60:
        return None
    signal_end = event["signal_ts"] + HOUR_MS
    trigger_bars = five_minute_bars(rows, signal_end, signal_end + 2 * HOUR_MS)
    crossed = False
    entry_bar = None
    for bar in trigger_bars:
        if not crossed and bar["close"] < profile.poc:
            crossed = True
        if crossed and bar["high"] >= profile.poc * 0.998 and bar["close"] < profile.poc:
            entry_bar = bar
            break
    if entry_bar is None:
        return None
    entry = entry_bar["close"]
    stop = profile.poc * 1.002
    target = profile.low + (profile.high - profile.low) / profile.bins
    if not (target < entry < stop):
        return None
    risk = stop - entry
    reward = entry - target
    if risk <= 0 or reward / risk < 2.0:
        return None
    entry_ts = int(entry_bar["ts"] + 5 * MINUTE_MS)
    exit_deadline = entry_ts + 8 * HOUR_MS
    future = [row for row in rows if entry_ts <= row["ts"] <= exit_deadline]
    if not future:
        return None
    exit_price, exit_ts, reason = future[-1]["close"], int(future[-1]["ts"]), "time_exit"
    for row in future:
        if row["high"] >= stop:
            exit_price, exit_ts, reason = stop, int(row["ts"]), "stop_loss"
            break
        if row["low"] <= target:
            exit_price, exit_ts, reason = target, int(row["ts"]), "vacuum_target"
            break
    # USDT-margined linear swap short return on entry notional.
    gross_return = (entry - exit_price) / entry
    return {
        **event,
        "side": "short",
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "entry_time": local_time(entry_ts),
        "exit_time": local_time(exit_ts),
        "entry": entry,
        "exit": exit_price,
        "stop": stop,
        "target": target,
        "planned_rr": reward / risk,
        "reason": reason,
        "net_return": gross_return - ROUND_TRIP_COST,
        "profile": asdict(profile),
    }


def run_failed_p_short(
    events: list[dict[str, Any]],
    windows: dict[str, list[dict[str, float]]],
    end_ms: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, int]]:
    trades = []
    rejected = {"missing_profile": 0, "not_failed_p_or_rr": 0, "overlap": 0}
    next_entry_ts = 0
    for event in events:
        profile, rows = profile_for_event(event, windows)
        if profile is None:
            rejected["missing_profile"] += 1
            continue
        trade = failed_p_trade(event, profile, rows)
        if trade is None:
            rejected["not_failed_p_or_rr"] += 1
            continue
        if trade["entry_ts"] < next_entry_ts or trade["exit_ts"] >= end_ms:
            rejected["overlap"] += 1
            continue
        trades.append(trade)
        next_entry_ts = trade["exit_ts"]
    return summarize_trades(trades), trades, rejected


async def main_async(args: argparse.Namespace) -> None:
    symbols, candles, metadata = load_cache(args.cache)
    snapshots, indexes = build_snapshots(symbols, candles)
    available_start = datetime.fromisoformat(metadata["analysis_start_utc"])
    available_end = datetime.fromisoformat(metadata["end_utc"])
    end = parse_local(args.end) if args.end else available_end
    start = parse_local(args.start) if args.start else end - timedelta(days=args.days)
    start = max(start, available_start)
    end = min(end, available_end)
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    config = Config(
        min_signal=args.min_signal,
        min_gap=args.min_gap,
        min_vol_ratio=args.min_vol_ratio,
        hold_hours=args.hold_hours,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=args.take_profit_pct,
        market_filter=args.market_filter,
        universe_size=args.universe_size,
        leverage=3,
        cooldown_hours=2,
    )
    events = raw_candidates(snapshots, start_ms, end_ms, config)
    windows, failures = await obtain_minute_windows(
        events, args.minute_cache, args.proxy, args.concurrency
    )
    baseline = evaluate(
        config, snapshots, indexes, start_ms, end_ms,
        initial_capital=1000.0, max_position_usd=1000.0, include_trades=True,
    )
    acceptance_metrics, acceptance_trades, acceptance_rejected = run_acceptance_long(
        events,
        windows,
        indexes,
        config,
        end_ms,
        acceptance_level=args.acceptance_level,
        max_high_pullback_pct=args.max_high_pullback_pct / 100,
    )
    vacuum_metrics, vacuum_trades, vacuum_rejected = run_failed_p_short(
        events, windows, end_ms
    )
    result = {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "data": metadata,
        "method": {
            "profile_source": "OKX 1m candles; quote volume assigned to each candle typical price",
            "profile_hours": 8,
            "profile_bins": 48,
            "value_area_pct": 70,
            "round_trip_cost_pct": ROUND_TRIP_COST * 100,
            "raw_candidate_events": len(events),
            "minute_windows": len(windows),
            "minute_fetch_failures": failures,
        },
        "config": asdict(config),
        "baseline_long": {
            "metrics": {key: value for key, value in baseline.items() if key != "trades_detail"},
            "trades": baseline["trades_detail"],
        },
        "profile_acceptance_long": {
            "rules": (
                f"signal close >= {args.acceptance_level.upper()} and pullback from "
                f"signal-hour high <= {args.max_high_pullback_pct}%"
            ),
            "metrics": acceptance_metrics,
            "rejected": acceptance_rejected,
            "trades": acceptance_trades,
        },
        "failed_p_vacuum_short": {
            "rules": "POC in upper 40%; 5m close below POC and failed retest; stop POC+0.2%; target profile low edge; RR>=2",
            "metrics": vacuum_metrics,
            "rejected": vacuum_rejected,
            "trades": vacuum_trades,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    print(json.dumps({
        "output": str(args.output),
        "period": result["period"],
        "raw_candidates": len(events),
        "minute_windows": len(windows),
        "fetch_failures": len(failures),
        "baseline": result["baseline_long"]["metrics"],
        "profile_acceptance": result["profile_acceptance_long"],
        "failed_p_vacuum": result["failed_p_vacuum_short"],
    }, ensure_ascii=False, indent=2, allow_nan=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("backtest_data/explosive_momentum_1h_60d_top80.json"))
    parser.add_argument("--minute-cache", type=Path, default=Path("backtest_data/volume_vacuum_1m_windows.json"))
    parser.add_argument("--output", type=Path, default=Path("backtest_results/volume_vacuum_comparison.json"))
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--days", type=int, default=15)
    parser.add_argument("--min-signal", type=float, default=0.04)
    parser.add_argument("--min-gap", type=float, default=0.01)
    parser.add_argument("--min-vol-ratio", type=float, default=3.0)
    parser.add_argument("--hold-hours", type=int, default=8)
    parser.add_argument("--stop-loss-pct", type=float, default=0.08)
    parser.add_argument("--take-profit-pct", type=float, default=0.10)
    parser.add_argument("--market-filter", default="none")
    parser.add_argument("--universe-size", type=int, default=80)
    parser.add_argument("--acceptance-level", choices=("vah", "poc"), default="vah")
    parser.add_argument("--max-high-pullback-pct", type=float, default=3.0)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main_async(parse_args()))
