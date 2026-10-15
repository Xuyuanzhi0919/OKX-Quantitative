#!/usr/bin/env python3
"""Backtest shorting altcoin pumps on OKX USDT perpetual swaps.

Signal and execution convention:
* A completed 1H candle closes more than ``signal_pct`` above the previous
  completed candle's close.
* Open a short at the next 1H candle's open (no look-ahead entry).
* Take profit when price falls ``take_profit_pct`` from the entry.
* If TP is not reached, close at the selected horizon's final candle close.

The script reports both TP hit rate and actual profitable-trade rate after
fees/slippage.  It also models an approximate liquidation barrier because a
5x short with no stop can otherwise make the result dangerously optimistic.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx


OKX_API = "https://www.okx.com/api/v5"
SHANGHAI = ZoneInfo("Asia/Shanghai")
HOUR_MS = 60 * 60 * 1000
EXCLUDED_BASES = {
    "BTC",
    "ETH",
    "USDC",
    "USDT",
    "DAI",
    "FDUSD",
    "TUSD",
    "USDE",
}


@dataclass(frozen=True)
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    confirmed: bool
    volume: float = 0.0
    quote_volume: float = 0.0


@dataclass(frozen=True)
class Signal:
    symbol: str
    signal_ts: int
    signal_return: float
    entry_ts: int
    entry_price: float
    entry_index: int


def local_time(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, SHANGHAI).strftime("%Y-%m-%d %H:%M")


async def request_json(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            async with semaphore:
                response = await client.get(path, params=params)
                # Public history-candles is rate limited. Keeping the slot for
                # a short cooldown prevents a burst from parallel symbols.
                if path.endswith("/market/history-candles"):
                    await asyncio.sleep(0.5)
            if response.status_code == 429:
                last_error = RuntimeError("HTTP 429 rate limited")
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != "0":
                raise RuntimeError(f"OKX error {payload.get('code')}: {payload.get('msg')}")
            return payload
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            last_error = exc
            await asyncio.sleep(min(0.4 * 2**attempt, 5.0))
    raise RuntimeError(f"OKX request failed after retries: {path} {params}: {last_error}")


async def select_universe(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    top_symbols: int,
) -> list[str]:
    tickers_payload, instruments_payload = await asyncio.gather(
        request_json(client, "/market/tickers", {"instType": "SWAP"}, semaphore),
        request_json(client, "/public/instruments", {"instType": "SWAP"}, semaphore),
    )
    # instCategory=1 is crypto. OKX also exposes tokenized equities/ETFs as
    # USDT swaps (instCategory=3), which must not leak into an altcoin test.
    crypto_symbols = {
        str(item.get("instId") or "")
        for item in instruments_payload["data"]
        if str(item.get("instCategory") or "1") == "1"
    }
    ranked: list[tuple[float, str]] = []
    for ticker in tickers_payload["data"]:
        symbol = str(ticker.get("instId") or "")
        if not symbol.endswith("-USDT-SWAP") or symbol not in crypto_symbols:
            continue
        base = symbol.split("-", 1)[0]
        if base in EXCLUDED_BASES:
            continue
        try:
            # volCcy24h is base-currency volume for linear swaps. Multiplying
            # by last price makes liquidity rankings comparable across coins.
            quote_volume = float(ticker.get("volCcy24h") or 0) * float(ticker.get("last") or 0)
        except (TypeError, ValueError):
            continue
        if quote_volume > 0:
            ranked.append((quote_volume, symbol))
    ranked.sort(reverse=True)
    return [symbol for _, symbol in ranked[:top_symbols]]


async def fetch_symbol_candles(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> tuple[str, list[Candle]]:
    cursor = end_ms
    rows: dict[int, Candle] = {}
    while cursor >= start_ms:
        payload = await request_json(
            client,
            "/market/history-candles",
            {"instId": symbol, "bar": "1H", "limit": "300", "after": str(cursor)},
            semaphore,
        )
        batch = payload.get("data") or []
        if not batch:
            break
        oldest = cursor
        for row in batch:
            ts = int(row[0])
            oldest = min(oldest, ts)
            if start_ms <= ts <= end_ms:
                rows[ts] = Candle(
                    ts=ts,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    confirmed=str(row[8]) == "1",
                    volume=float(row[5]),
                    quote_volume=float(row[7]),
                )
        if oldest >= cursor or oldest < start_ms:
            break
        cursor = oldest
        await asyncio.sleep(0.04)
    return symbol, sorted(rows.values(), key=lambda candle: candle.ts)


def load_cache(path: Path) -> tuple[list[str], dict[str, list[Candle]], dict[str, Any]]:
    payload = json.loads(path.read_text())
    candles = {
        symbol: [Candle(**row) for row in rows]
        for symbol, rows in payload["candles"].items()
    }
    return list(payload["symbols"]), candles, dict(payload.get("metadata") or {})


def write_cache(
    path: Path,
    symbols: list[str],
    candles: dict[str, list[Candle]],
    metadata: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": metadata,
        "symbols": symbols,
        "candles": {
            symbol: [asdict(candle) for candle in rows]
            for symbol, rows in candles.items()
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def find_signals(
    candles: dict[str, list[Candle]],
    signal_pct: float,
    analysis_start_ms: int | None = None,
) -> list[Signal]:
    signals: list[Signal] = []
    for symbol, rows in candles.items():
        for index in range(1, len(rows) - 1):
            previous, current, entry = rows[index - 1], rows[index], rows[index + 1]
            if analysis_start_ms is not None and current.ts < analysis_start_ms:
                continue
            if not previous.confirmed or not current.confirmed or previous.close <= 0:
                continue
            # Reject gaps: the next array item really must be the next hour.
            if current.ts - previous.ts != HOUR_MS or entry.ts - current.ts != HOUR_MS:
                continue
            one_hour_return = current.close / previous.close - 1
            if one_hour_return > signal_pct:
                signals.append(
                    Signal(
                        symbol=symbol,
                        signal_ts=current.ts,
                        signal_return=one_hour_return,
                        entry_ts=entry.ts,
                        entry_price=entry.open,
                        entry_index=index + 1,
                    )
                )
    return sorted(signals, key=lambda item: (item.entry_ts, item.symbol))


def evaluate_horizon(
    signals: list[Signal],
    candles: dict[str, list[Candle]],
    horizon_hours: int,
    take_profit_pct: float,
    stop_loss_pct: float | None,
    leverage: float,
    fee_per_side: float,
    slippage_per_side: float,
    liquidation_adverse_pct: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    tp_count = 0
    stop_count = 0
    liquidation_count = 0
    overlap_skips = 0
    next_allowed_entry: dict[str, int] = {}
    cost_pct = 2 * (fee_per_side + slippage_per_side)

    for signal in signals:
        if signal.entry_ts < next_allowed_entry.get(signal.symbol, 0):
            overlap_skips += 1
            continue
        rows = candles[signal.symbol]
        future = rows[signal.entry_index : signal.entry_index + horizon_hours]
        if len(future) < horizon_hours:
            continue
        if any(b.ts != signal.entry_ts + offset * HOUR_MS for offset, b in enumerate(future)):
            continue

        tp_price = signal.entry_price * (1 - take_profit_pct)
        stop_price = signal.entry_price * (1 + stop_loss_pct) if stop_loss_pct else None
        liquidation_price = signal.entry_price * (1 + liquidation_adverse_pct)
        exit_price = future[-1].close
        exit_ts = future[-1].ts
        reason = "time_exit"
        max_adverse_pct = 0.0

        for candle in future:
            max_adverse_pct = max(max_adverse_pct, candle.high / signal.entry_price - 1)
            liquidation_hit = candle.high >= liquidation_price
            stop_hit = stop_price is not None and candle.high >= stop_price
            tp_hit = candle.low <= tp_price
            # OHLC data cannot reveal which boundary happened first inside one
            # hour. A configured stop below liquidation must be crossed first
            # unless the bar opens beyond liquidation. For a TP/SL same-bar
            # collision, resolve pessimistically in favor of the stop.
            if candle.open >= liquidation_price:
                exit_price = liquidation_price
                exit_ts = candle.ts
                reason = "liquidation"
                liquidation_count += 1
                break
            if stop_hit:
                # A gap above the stop receives the worse opening price.
                exit_price = max(stop_price, candle.open)
                exit_ts = candle.ts
                reason = "stop_loss"
                stop_count += 1
                break
            if liquidation_hit:
                exit_price = liquidation_price
                exit_ts = candle.ts
                reason = "liquidation"
                liquidation_count += 1
                break
            if tp_hit:
                exit_price = tp_price
                exit_ts = candle.ts
                reason = "take_profit"
                tp_count += 1
                break

        price_return = (signal.entry_price - exit_price) / signal.entry_price
        net_roe = leverage * (price_return - cost_pct)
        results.append(
            {
                "symbol": signal.symbol,
                "signal_time": local_time(signal.signal_ts),
                "entry_time": local_time(signal.entry_ts),
                "exit_time": local_time(exit_ts),
                "signal_return_pct": signal.signal_return * 100,
                "entry_price": signal.entry_price,
                "exit_price": exit_price,
                "exit_reason": reason,
                "price_return_pct": price_return * 100,
                "net_roe_pct": net_roe * 100,
                "max_adverse_pct": max_adverse_pct * 100,
            }
        )
        # Do not count a fresh signal while this symbol's previous short is
        # still open. Re-entry is allowed from the hour after its exit.
        next_allowed_entry[signal.symbol] = exit_ts + HOUR_MS

    net_returns = [row["net_roe_pct"] for row in results]
    wins = [value for value in net_returns if value > 0]
    losses = [value for value in net_returns if value <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    metrics = {
        "stop_loss_pct": stop_loss_pct,
        "horizon_hours": horizon_hours,
        "trades": len(results),
        "same_symbol_overlap_skips": overlap_skips,
        "tp_hits": tp_count,
        "tp_hit_rate_pct": 100 * tp_count / len(results) if results else 0.0,
        "stop_hits": stop_count,
        "stop_hit_rate_pct": 100 * stop_count / len(results) if results else 0.0,
        "profitable_trades": len(wins),
        "profitable_trade_rate_pct": 100 * len(wins) / len(results) if results else 0.0,
        "approx_liquidations": liquidation_count,
        "approx_liquidation_rate_pct": 100 * liquidation_count / len(results) if results else 0.0,
        "average_net_roe_pct": statistics.fmean(net_returns) if net_returns else 0.0,
        "median_net_roe_pct": statistics.median(net_returns) if net_returns else 0.0,
        "best_net_roe_pct": max(net_returns, default=0.0),
        "worst_net_roe_pct": min(net_returns, default=0.0),
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
    }
    return metrics, results


def symbol_breakdown(rows: list[dict[str, Any]], minimum_trades: int = 3) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["symbol"], []).append(row)
    output = []
    for symbol, items in grouped.items():
        if len(items) < minimum_trades:
            continue
        tp_hits = sum(item["exit_reason"] == "take_profit" for item in items)
        output.append(
            {
                "symbol": symbol,
                "trades": len(items),
                "tp_hit_rate_pct": 100 * tp_hits / len(items),
                "average_net_roe_pct": statistics.fmean(item["net_roe_pct"] for item in items),
            }
        )
    return sorted(output, key=lambda item: (item["average_net_roe_pct"], item["trades"]), reverse=True)


async def obtain_data(args: argparse.Namespace) -> tuple[list[str], dict[str, list[Candle]], dict[str, Any]]:
    if args.cache.exists() and not args.refresh:
        return load_cache(args.cache)

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = now - timedelta(hours=1)  # last certainly completed 1H candle
    start = end - timedelta(days=args.days, hours=max(args.horizons) + 2)
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    semaphore = asyncio.Semaphore(args.concurrency)
    headers = {"User-Agent": "OKK-altcoin-pump-short-backtest/1.0"}
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(base_url=OKX_API, headers=headers, timeout=timeout, trust_env=False) as client:
        symbols = await select_universe(client, semaphore, args.top_symbols)
        tasks = [fetch_symbol_candles(client, semaphore, symbol, start_ms, end_ms) for symbol in symbols]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

    candles: dict[str, list[Candle]] = {}
    failures: dict[str, str] = {}
    for symbol, result in zip(symbols, completed):
        if isinstance(result, Exception):
            failures[symbol] = str(result)
        else:
            _, rows = result
            if rows:
                candles[symbol] = rows
    symbols = [symbol for symbol in symbols if symbol in candles]
    metadata = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "analysis_start_utc": (end - timedelta(days=args.days)).isoformat(),
        "universe_method": "current top crypto-category USDT perpetual swaps by approximate 24h quote volume; BTC/ETH/stablecoins excluded",
        "requested_symbols": args.top_symbols,
        "loaded_symbols": len(symbols),
        "failures": failures,
    }
    write_cache(args.cache, symbols, candles, metadata)
    return symbols, candles, metadata


def write_trades_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


async def main_async(args: argparse.Namespace) -> None:
    started = time.monotonic()
    symbols, candles, metadata = await obtain_data(args)
    analysis_start = metadata.get("analysis_start_utc") or metadata["start_utc"]
    analysis_start_ms = int(datetime.fromisoformat(analysis_start).timestamp() * 1000)
    signals = find_signals(candles, args.signal_pct, analysis_start_ms)
    horizon_metrics: list[dict[str, Any]] = []
    horizon_trades: dict[str, list[dict[str, Any]]] = {}
    for stop_loss_pct in args.stop_loss_pcts:
        normalized_stop = stop_loss_pct or None
        for horizon in args.horizons:
            metrics, rows = evaluate_horizon(
                signals=signals,
                candles=candles,
                horizon_hours=horizon,
                take_profit_pct=args.take_profit_pct,
                stop_loss_pct=normalized_stop,
                leverage=args.leverage,
                fee_per_side=args.fee_per_side,
                slippage_per_side=args.slippage_per_side,
                liquidation_adverse_pct=args.liquidation_adverse_pct,
            )
            key = f"sl{stop_loss_pct:g}_h{horizon}"
            horizon_metrics.append(metrics)
            horizon_trades[key] = rows

    best_metrics = max(horizon_metrics, key=lambda item: item["average_net_roe_pct"])
    best_stop = best_metrics["stop_loss_pct"] or 0.0
    best_key = f"sl{best_stop:g}_h{best_metrics['horizon_hours']}"
    primary_rows = horizon_trades[best_key]
    result = {
        "parameters": {
            "signal_pct": args.signal_pct,
            "take_profit_pct": args.take_profit_pct,
            "stop_loss_pcts": args.stop_loss_pcts,
            "leverage": args.leverage,
            "horizons": args.horizons,
            "fee_per_side": args.fee_per_side,
            "slippage_per_side": args.slippage_per_side,
            "liquidation_adverse_pct": args.liquidation_adverse_pct,
            "entry_rule": "next 1H candle open after signal candle closes",
            "same_bar_exit_priority": "liquidation, stop-loss, take-profit (pessimistic)",
        },
        "data": metadata,
        "symbols": symbols,
        "raw_signal_count": len(signals),
        "metrics": horizon_metrics,
        "best_by_average_net_roe": best_metrics,
        "best_trade_key": best_key,
        "symbol_breakdown": symbol_breakdown(primary_rows),
        "trades": horizon_trades,
        "runtime_seconds": time.monotonic() - started,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    csv_path = args.output.with_suffix(f".{best_key}.trades.csv")
    write_trades_csv(csv_path, primary_rows)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "trades_csv": str(csv_path),
                "loaded_symbols": len(symbols),
                "raw_signals": len(signals),
                "metrics": horizon_metrics,
                "runtime_seconds": round(result["runtime_seconds"], 2),
            },
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=60, help="history window when downloading data")
    parser.add_argument("--top-symbols", type=int, default=80, help="current top-liquidity altcoin swaps")
    parser.add_argument("--signal-pct", type=float, default=0.04)
    parser.add_argument("--take-profit-pct", type=float, default=0.02)
    parser.add_argument(
        "--stop-loss-pcts",
        type=float,
        nargs="+",
        default=[0.0, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08],
        help="price stop-loss fractions to sweep; 0 means no stop",
    )
    parser.add_argument("--leverage", type=float, default=5.0)
    parser.add_argument("--horizons", type=int, nargs="+", default=[4, 12, 24])
    parser.add_argument("--fee-per-side", type=float, default=0.0005, help="taker fee as fraction of notional")
    parser.add_argument("--slippage-per-side", type=float, default=0.0002)
    parser.add_argument("--liquidation-adverse-pct", type=float, default=0.18, help="approximate 5x short liquidation move")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--cache", type=Path, default=Path("backtest_data/altcoin_pump_short_1h.json"))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("backtest_results/altcoin_pump_short.json"))
    args = parser.parse_args()
    if args.days <= 0 or args.top_symbols <= 0 or not args.horizons or min(args.horizons) <= 0:
        parser.error("days, top-symbols, and horizons must be positive")
    for name in ("signal_pct", "take_profit_pct", "fee_per_side", "slippage_per_side"):
        if getattr(args, name) < 0:
            parser.error(f"{name} cannot be negative")
    if args.leverage <= 0 or not math.isfinite(args.leverage):
        parser.error("leverage must be a positive finite number")
    args.horizons = sorted(set(args.horizons))
    if any(value < 0 or value >= args.liquidation_adverse_pct for value in args.stop_loss_pcts):
        parser.error("each stop loss must be >= 0 and below liquidation-adverse-pct")
    args.stop_loss_pcts = sorted(set(args.stop_loss_pcts))
    return args


if __name__ == "__main__":
    asyncio.run(main_async(parse_args()))
