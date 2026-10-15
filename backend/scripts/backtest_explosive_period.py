#!/usr/bin/env python3
"""Backtest one explosive-momentum configuration over an exact local period."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from backtest_altcoin_pump_short import HOUR_MS
from optimize_explosive_momentum import (
    Config,
    build_snapshots,
    evaluate,
    obtain_data,
)


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def parse_local(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)


def local_time(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, LOCAL_TZ).strftime("%Y-%m-%d %H:%M")


def write_trades(path: Path, trades: list[dict]) -> None:
    fields = [
        "signal_time",
        "entry_time",
        "exit_time",
        "symbol",
        "signal_pct",
        "vol_ratio",
        "btc_4h_pct",
        "entry",
        "exit",
        "reason",
        "position_notional_usd",
        "margin_used_usd",
        "net_position_return_pct",
        "pnl_usdt",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for trade in trades:
            row = dict(trade)
            row["signal_time"] = local_time(trade["signal_ts"])
            row["entry_time"] = local_time(trade["entry_ts"])
            row["exit_time"] = local_time(trade["exit_ts"])
            writer.writerow({field: row.get(field) for field in fields})


async def main_async(args: argparse.Namespace) -> None:
    data_args = SimpleNamespace(
        cache=args.cache,
        refresh=args.refresh,
        days=args.days,
        concurrency=args.concurrency,
        top_symbols=args.top_symbols,
    )
    symbols, candles, metadata = await obtain_data(data_args)
    snapshots, indexes = build_snapshots(symbols, candles)

    start = parse_local(args.start)
    fetched_last_candle = datetime.fromisoformat(metadata["end_utc"])
    latest_complete_end = fetched_last_candle + timedelta(hours=1)
    requested_end = parse_local(args.end) if args.end else latest_complete_end
    end = min(requested_end, latest_complete_end)
    if end <= start:
        raise ValueError("end must be after start")

    config = Config(
        min_signal=args.min_signal,
        min_gap=args.min_gap,
        min_vol_ratio=args.min_vol_ratio,
        hold_hours=args.hold_hours,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=None if args.no_take_profit else args.take_profit_pct,
        market_filter=args.market_filter,
        universe_size=args.universe_size,
        leverage=args.leverage,
        cooldown_hours=args.cooldown_hours,
        max_signal=args.max_signal,
        max_ret_4h=args.max_ret_4h,
        max_ret_24h=args.max_ret_24h,
        max_vol_ratio=args.max_vol_ratio,
    )
    metrics = evaluate(
        config,
        snapshots,
        indexes,
        int(start.timestamp() * 1000),
        int(end.timestamp() * 1000),
        initial_capital=args.initial_capital,
        max_position_usd=args.max_position_usd,
        include_trades=True,
    )
    trades = metrics.pop("trades_detail") or []
    result = {
        "period": {
            "start": start.isoformat(),
            "end": end.astimezone(LOCAL_TZ).isoformat(),
            "timezone": "Asia/Shanghai",
            "end_is_latest_complete_hour": args.end is None or requested_end > latest_complete_end,
        },
        "data": metadata,
        "config": asdict(config),
        "execution_model": {
            "entry": "next 1H candle open",
            "round_trip_cost_pct": 0.12,
            "same_bar_tp_sl": "stop_first",
            "max_position_usd_is_notional": True,
        },
        "metrics": metrics,
        "trades": [
            {
                **trade,
                "signal_time": local_time(trade["signal_ts"]),
                "entry_time": local_time(trade["entry_ts"]),
                "exit_time": local_time(trade["exit_ts"]),
            }
            for trade in trades
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = args.output.with_suffix(".trades.csv")
    write_trades(csv_path, trades)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "csv": str(csv_path),
                "period": result["period"],
                "config": result["config"],
                "metrics": metrics,
                "trades": result["trades"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end")
    parser.add_argument("--initial-capital", type=float, default=1000.0)
    parser.add_argument("--max-position-usd", type=float, default=1000.0)
    parser.add_argument("--min-signal", type=float, default=0.04)
    parser.add_argument("--min-gap", type=float, default=0.01)
    parser.add_argument("--min-vol-ratio", type=float, default=3.0)
    parser.add_argument("--hold-hours", type=int, default=8)
    parser.add_argument("--stop-loss-pct", type=float, default=0.08)
    parser.add_argument("--take-profit-pct", type=float, default=0.10)
    parser.add_argument("--no-take-profit", action="store_true")
    parser.add_argument("--market-filter", default="none")
    parser.add_argument("--universe-size", type=int, default=80)
    parser.add_argument("--leverage", type=int, default=3)
    parser.add_argument("--cooldown-hours", type=int, default=2)
    parser.add_argument("--max-signal", type=float)
    parser.add_argument("--max-ret-4h", type=float)
    parser.add_argument("--max-ret-24h", type=float)
    parser.add_argument("--max-vol-ratio", type=float)
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--top-symbols", type=int, default=80)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("backtest_data/explosive_momentum_1h_latest_top80.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backtest_results/explosive_momentum_20260723_20260725.json"),
    )
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main_async(parse_args()))
