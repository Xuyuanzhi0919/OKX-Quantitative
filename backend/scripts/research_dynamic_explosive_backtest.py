#!/usr/bin/env python3
"""Dynamic-universe research backtest for explosive momentum chaser.

This script intentionally lives under scripts/research style usage: it reads
cached OKX 1H candles, scans the whole cached universe at each historical hour,
selects the strongest valid symbol, and writes detailed scan/trade logs.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any


FEE_PCT_ROUND_TRIP = 0.0012
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class BacktestParams:
    min_signal: float = 0.06
    min_gap: float = 0.01
    min_vol_ratio: float = 1.2
    hold_hours: int = 4
    stop_loss_pct: float = 0.04
    take_profit_pct: float | None = None
    market_filter: str = "btc_4h_positive"
    top_n: int = 1


def parse_dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)


def dt_str(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, LOCAL_TZ).strftime("%Y-%m-%d %H:%M")


def load_cache(path: Path) -> dict[str, list[dict[str, float]]]:
    raw = json.loads(path.read_text())
    data = raw["data"]
    parsed: dict[str, list[dict[str, float]]] = {}
    for symbol, rows in data.items():
        clean = []
        for row in rows:
            if not row:
                continue
            clean.append(
                {
                    "ts": int(row["ts"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0.0)),
                }
            )
        if clean:
            parsed[symbol] = sorted(clean, key=lambda item: item["ts"])
    return parsed


def index_candles(data: dict[str, list[dict[str, float]]]) -> dict[str, dict[int, dict[str, float]]]:
    return {symbol: {int(c["ts"]): c for c in candles} for symbol, candles in data.items()}


def candle_at(index: dict[str, dict[int, dict[str, float]]], symbol: str, ts: int) -> dict[str, float] | None:
    return index.get(symbol, {}).get(ts)


def previous_candles(
    candles: list[dict[str, float]],
    current_pos: int,
    count: int,
) -> list[dict[str, float]]:
    start = current_pos - count
    if start < 0:
        return []
    return candles[start:current_pos]


def calc_candidate(
    symbol: str,
    candles: list[dict[str, float]],
    pos: int,
    params: BacktestParams,
) -> dict[str, Any] | None:
    if pos < 24 or pos < 1:
        return None
    current = candles[pos]
    previous = candles[pos - 1]
    if previous["close"] <= 0:
        return None
    ret_1h = current["close"] / previous["close"] - 1.0
    vols = [item["volume"] for item in previous_candles(candles, pos, 24) if item["volume"] > 0]
    if not vols:
        return None
    avg_vol = sum(vols) / len(vols)
    vol_ratio = current["volume"] / avg_vol if avg_vol > 0 else 0.0
    if ret_1h < params.min_signal or vol_ratio < params.min_vol_ratio:
        return None
    return {
        "symbol": symbol,
        "ret_1h": ret_1h,
        "signal_pct": ret_1h * 100,
        "vol_ratio": vol_ratio,
        "close": current["close"],
        "volume": current["volume"],
    }


def btc_filter_pass(
    data: dict[str, list[dict[str, float]]],
    by_ts: dict[str, dict[int, dict[str, float]]],
    ts: int,
    params: BacktestParams,
) -> tuple[bool, str, float | None]:
    if params.market_filter in {"none", "", None}:  # type: ignore[comparison-overlap]
        return True, "market_filter=none", None
    if params.market_filter != "btc_4h_positive":
        return False, f"unsupported market_filter={params.market_filter}", None
    btc = data.get("BTC-USDT-SWAP")
    if not btc:
        return False, "BTC-USDT-SWAP missing", None
    pos_map = {int(c["ts"]): i for i, c in enumerate(btc)}
    pos = pos_map.get(ts)
    if pos is None or pos < 4:
        return False, "BTC warmup insufficient", None
    base = btc[pos - 4]["close"]
    current = btc[pos]["close"]
    if base <= 0:
        return False, "BTC base close invalid", None
    ret_4h = current / base - 1
    return ret_4h > 0, f"BTC 4h return {ret_4h * 100:.2f}%", ret_4h


def simulate_exit(
    by_ts: dict[str, dict[int, dict[str, float]]],
    symbol: str,
    signal_ts: int,
    params: BacktestParams,
) -> tuple[dict[str, Any] | None, str | None]:
    hour_ms = 60 * 60 * 1000
    entry_ts = signal_ts + hour_ms
    entry_candle = candle_at(by_ts, symbol, entry_ts)
    if not entry_candle:
        return None, "missing entry candle"
    entry = entry_candle["open"]
    stop = entry * (1 - params.stop_loss_pct)
    take_profit = entry * (1 + params.take_profit_pct) if params.take_profit_pct else None
    exit_ts = signal_ts + params.hold_hours * hour_ms
    exit_reason = "time_exit"
    exit_price: float | None = None
    entry_bar_close_breached_stop = False
    take_profit_hit: tuple[int, float] | None = None
    for check_ts in range(entry_ts, exit_ts + 1, hour_ms):
        candle = candle_at(by_ts, symbol, check_ts)
        if not candle:
            return None, f"missing hold candle {dt_str(check_ts)}"
        if take_profit is not None and take_profit_hit is None and candle["high"] >= take_profit:
            take_profit_hit = (check_ts, take_profit)
        # The legacy research result this script is meant to compare against
        # treated the stop as an entry-bar close confirmation, not an intrabar
        # low trigger. It also recorded the planned hold exit time for stopped
        # trades. Keeping that convention makes this reproduction comparable.
        if check_ts == entry_ts and candle["close"] <= stop:
            entry_bar_close_breached_stop = True
    if entry_bar_close_breached_stop:
        exit_price = stop
        exit_reason = "stop_loss"
    elif take_profit_hit is not None:
        exit_ts, exit_price = take_profit_hit
        exit_reason = "take_profit"
    if exit_price is None:
        exit_candle = candle_at(by_ts, symbol, exit_ts)
        if not exit_candle:
            return None, "missing exit candle"
        exit_price = exit_candle["close"]
    gross_pct = exit_price / entry - 1
    return {
        "entry_time": dt_str(entry_ts),
        "exit_time": dt_str(exit_ts),
        "entry": entry,
        "exit": exit_price,
        "stop": stop,
        "take_profit": take_profit,
        "exit_reason": exit_reason,
        "gross_pct": gross_pct,
    }, None


def run_backtest(
    data: dict[str, list[dict[str, float]]],
    start: datetime,
    end: datetime,
    params: BacktestParams,
    initial_capital: float,
    leverages: list[int],
) -> dict[str, Any]:
    by_ts = index_candles(data)
    pos_maps = {symbol: {int(c["ts"]): i for i, c in enumerate(candles)} for symbol, candles in data.items()}
    all_ts = sorted({int(c["ts"]) for candles in data.values() for c in candles})
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    scan_ts = [ts for ts in all_ts if start_ms <= ts < end_ms]
    excluded = {"BTC-USDT-SWAP", "ETH-USDT-SWAP"}

    scan_logs: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    next_allowed_signal_ts = start_ms

    for ts in scan_ts:
        ts_text = dt_str(ts)
        market_ok, market_reason, btc_ret_4h = btc_filter_pass(data, by_ts, ts, params)
        if not market_ok:
            scan_logs.append(
                {
                    "time": ts_text,
                    "action": "skip",
                    "reason": market_reason,
                    "market_ok": False,
                    "candidate_count": 0,
                }
            )
            continue
        if ts < next_allowed_signal_ts:
            scan_logs.append(
                {
                    "time": ts_text,
                    "action": "skip",
                    "reason": f"position overlap lock until {dt_str(next_allowed_signal_ts)}",
                    "market_ok": True,
                    "btc_ret_4h_pct": btc_ret_4h * 100 if btc_ret_4h is not None else None,
                    "candidate_count": 0,
                }
            )
            continue

        candidates = []
        for symbol, candles in data.items():
            if symbol in excluded:
                continue
            pos = pos_maps[symbol].get(ts)
            if pos is None:
                continue
            candidate = calc_candidate(symbol, candles, pos, params)
            if candidate:
                candidates.append(candidate)
        candidates.sort(key=lambda item: item["ret_1h"], reverse=True)
        top = candidates[0] if candidates else None
        second = candidates[1] if len(candidates) > 1 else None
        gap = (top["ret_1h"] - second["ret_1h"]) if top and second else None

        base_log = {
            "time": ts_text,
            "market_ok": True,
            "btc_ret_4h_pct": btc_ret_4h * 100 if btc_ret_4h is not None else None,
            "candidate_count": len(candidates),
            "top": top,
            "second": second,
            "gap_pct": gap * 100 if gap is not None else None,
        }
        if not top:
            scan_logs.append({**base_log, "action": "skip", "reason": "no candidates"})
            continue
        if second is not None and gap is not None and gap < params.min_gap:
            scan_logs.append(
                {
                    **base_log,
                    "action": "skip",
                    "reason": f"gap {gap * 100:.2f}% < {params.min_gap * 100:.2f}%",
                }
            )
            continue

        exit_info, missing_reason = simulate_exit(by_ts, top["symbol"], ts, params)
        if missing_reason:
            scan_logs.append({**base_log, "action": "skip", "reason": missing_reason})
            continue

        assert exit_info is not None
        trade = {
            "signal_time": ts_text,
            "symbol": top["symbol"],
            "signal_pct": top["signal_pct"],
            "vol_ratio": top["vol_ratio"],
            "btc_ret_4h_pct": btc_ret_4h * 100 if btc_ret_4h is not None else None,
            "candidate_count": len(candidates),
            "rank2_symbol": second["symbol"] if second else None,
            "rank2_signal_pct": second["signal_pct"] if second else None,
            "gap_pct": gap * 100 if gap is not None else None,
            **exit_info,
        }
        for lev in leverages:
            trade[f"net{lev}x_pct"] = (trade["gross_pct"] - FEE_PCT_ROUND_TRIP) * lev * 100
        trades.append(trade)
        scan_logs.append({**base_log, "action": "buy", "reason": "signal accepted", "trade": trade})
        next_allowed_signal_ts = int(parse_dt(trade["exit_time"]).timestamp() * 1000)

    metrics = {}
    for lev in leverages:
        capital = initial_capital
        peak = initial_capital
        max_dd = 0.0
        percs = []
        equity_curve = []
        for trade in trades:
            pct = trade[f"net{lev}x_pct"] / 100
            percs.append(pct)
            capital *= 1 + pct
            peak = max(peak, capital)
            dd = (peak - capital) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
            equity_curve.append(
                {
                    "time": trade["exit_time"],
                    "capital": capital,
                    "drawdown_pct": dd * 100,
                }
            )
        wins = [p for p in percs if p > 0]
        metrics[f"{lev}x"] = {
            "initial_capital": initial_capital,
            "final_capital": capital,
            "profit": capital - initial_capital,
            "return_pct": (capital / initial_capital - 1) * 100,
            "max_drawdown_pct": max_dd * 100,
            "trades": len(trades),
            "win_rate_pct": (len(wins) / len(trades) * 100) if trades else 0.0,
            "worst_trade_pct": min((p * 100 for p in percs), default=0.0),
            "best_trade_pct": max((p * 100 for p in percs), default=0.0),
            "equity_curve": equity_curve,
        }

    return {
        "params": params.__dict__,
        "period": {"start": start.strftime("%Y-%m-%d %H:%M"), "end": end.strftime("%Y-%m-%d %H:%M"), "timezone": "Asia/Shanghai"},
        "universe": {
            "symbols": len(data),
            "swap_symbols": len([s for s in data if s.endswith("-SWAP")]),
            "source_note": "dynamic scan over symbols present in the input cache, not guaranteed full historical OKX universe",
        },
        "metrics": metrics,
        "trades": trades,
        "scan_logs": scan_logs,
    }


def write_csv(path: Path, trades: list[dict[str, Any]]) -> None:
    fields = [
        "signal_time",
        "entry_time",
        "exit_time",
        "symbol",
        "signal_pct",
        "vol_ratio",
        "btc_ret_4h_pct",
        "candidate_count",
        "rank2_symbol",
        "rank2_signal_pct",
        "gap_pct",
        "entry",
        "exit",
        "stop",
        "exit_reason",
        "gross_pct",
        "net1x_pct",
        "net3x_pct",
        "net5x_pct",
    ]
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for trade in trades:
            writer.writerow({key: trade.get(key) for key in fields})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--start", default="2026-07-01 05:00")
    parser.add_argument("--end", default="2026-07-16 05:00")
    parser.add_argument("--initial-capital", type=float, default=1000)
    parser.add_argument("--min-signal", type=float, default=0.06)
    parser.add_argument("--min-gap", type=float, default=0.01)
    parser.add_argument("--min-vol-ratio", type=float, default=1.2)
    parser.add_argument("--hold-hours", type=int, default=4)
    parser.add_argument("--stop-loss-pct", type=float, default=0.04)
    parser.add_argument("--take-profit-pct", type=float, default=None)
    parser.add_argument("--market-filter", default="btc_4h_positive")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    params = BacktestParams(
        min_signal=args.min_signal,
        min_gap=args.min_gap,
        min_vol_ratio=args.min_vol_ratio,
        hold_hours=args.hold_hours,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=args.take_profit_pct,
        market_filter=args.market_filter,
    )
    data = load_cache(args.cache)
    result = run_backtest(
        data=data,
        start=parse_dt(args.start),
        end=parse_dt(args.end),
        params=params,
        initial_capital=args.initial_capital,
        leverages=[1, 3, 5],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    write_csv(args.output.with_suffix(".trades.csv"), result["trades"])
    print(json.dumps({"output": str(args.output), "csv": str(args.output.with_suffix(".trades.csv")), "metrics": result["metrics"], "trades": len(result["trades"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
