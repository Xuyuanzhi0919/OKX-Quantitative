#!/usr/bin/env python3
"""Seven-day dynamic-universe backtest for the altcoin pyramid strategy."""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from backtest_liquid_altcoin_pyramid import Params, ema, max_drawdown


BASE_URL = "https://www.okx.com/api/v5"
MAJOR_SYMBOLS = {
    "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "BNB-USDT-SWAP",
    "XRP-USDT-SWAP", "DOGE-USDT-SWAP", "ADA-USDT-SWAP", "TRX-USDT-SWAP",
    "LTC-USDT-SWAP", "BCH-USDT-SWAP", "LINK-USDT-SWAP", "AVAX-USDT-SWAP",
}


def okx_get(path: str, params: Optional[Dict] = None) -> List:
    url = f"{BASE_URL}/{path}"
    if params:
        url += "?" + urlencode(params)
    raw = subprocess.check_output(
        ["curl", "--noproxy", "*", "-sS", "--max-time", "20", url],
        text=True,
    )
    payload = json.loads(raw)
    if str(payload.get("code")) != "0":
        raise RuntimeError(f"OKX {path}: {payload.get('code')} {payload.get('msg')}")
    return payload.get("data", [])


def load_universe(max_symbols: int = 40) -> List[str]:
    instruments = okx_get("public/instruments", {"instType": "SWAP"})
    crypto = {
        row["instId"] for row in instruments
        if row.get("instId", "").endswith("-USDT-SWAP")
        and str(row.get("state", "live")) == "live"
        # OKX group 5 is crypto USDT derivatives. Groups 6/7 contain
        # commodities and tokenized equities despite sharing category=1.
        and str(row.get("groupId", "")) == "5"
    }
    tickers = okx_get("market/tickers", {"instType": "SWAP"})
    ranked = []
    for row in tickers:
        symbol = row.get("instId", "")
        if symbol not in crypto or symbol in MAJOR_SYMBOLS:
            continue
        try:
            last = float(row.get("last") or 0)
            quote_volume = float(row.get("volCcy24h") or 0) * last
        except (TypeError, ValueError):
            continue
        if last > 0 and quote_volume > 0:
            ranked.append((quote_volume, symbol))
    ranked.sort(reverse=True)
    return [symbol for _, symbol in ranked[:max_symbols]]


def load_candles(symbol: str) -> tuple[str, List[Dict]]:
    rows = okx_get("market/history-candles", {"instId": symbol, "bar": "1H", "limit": "300"})
    candles = []
    for row in rows:
        if str(row[8]) != "1":
            continue
        candles.append({
            "ts": int(row[0]), "open": float(row[1]), "high": float(row[2]),
            "low": float(row[3]), "close": float(row[4]),
            "quote_volume": float(row[7]),
        })
    candles.sort(key=lambda item: item["ts"])
    return symbol, candles


def prepare_series(candles: List[Dict], params: Params) -> Dict:
    closes = [row["close"] for row in candles]
    fast = ema(closes, params.fast_ema)
    slow = ema(closes, params.slow_ema)
    return {
        "candles": candles,
        "by_ts": {row["ts"]: i for i, row in enumerate(candles)},
        "fast": fast,
        "slow": slow,
    }


def signal_at(series: Dict, index: int, params: Params) -> Optional[Dict]:
    if index < max(params.slow_ema, params.breakout_bars, 24):
        return None
    candles = series["candles"]
    close = candles[index]["close"]
    prior = candles[index - params.breakout_bars:index]
    prior_high = max(row["high"] for row in prior)
    prior_low = min(row["low"] for row in prior)
    if close > prior_high and series["fast"][index] > series["slow"][index]:
        return {"side": 1, "score": close / prior_high - 1.0}
    if close < prior_low and series["fast"][index] < series["slow"][index]:
        return {"side": -1, "score": prior_low / close - 1.0}
    return None


def run_dynamic(data: Dict[str, List[Dict]], params: Params, initial_equity: float = 1000.0) -> Dict:
    series = {symbol: prepare_series(rows, params) for symbol, rows in data.items() if len(rows) >= 240}
    all_ts = sorted({row["ts"] for item in series.values() for row in item["candles"]})
    analysis_ts = all_ts[-168:]
    equity = initial_equity
    curve = [equity]
    trades = []
    position = None

    for ts in analysis_ts:
        if position is not None:
            item = series[position["symbol"]]
            index = item["by_ts"].get(ts)
            if index is None:
                continue
            row = item["candles"][index]
            close, high, low = row["close"], row["high"], row["low"]
            side = position["side"]
            avg_entry = position["cost"] / position["qty"]
            stop_px = avg_entry * (1.0 - params.stop_loss_pct * side)
            target_px = avg_entry * (1.0 + params.take_profit_pct * side)
            reason, exit_px = None, close
            if (side == 1 and low <= stop_px) or (side == -1 and high >= stop_px):
                reason, exit_px = "stop", stop_px
            elif (side == 1 and high >= target_px) or (side == -1 and low <= target_px):
                reason, exit_px = "take_profit", target_px
            elif position["bars"] >= params.max_hold_bars:
                reason = "timeout"
            elif (side == 1 and item["fast"][index] < item["slow"][index]) or (side == -1 and item["fast"][index] > item["slow"][index]):
                reason = "trend_flip"

            if reason:
                gross = side * position["qty"] * (exit_px - avg_entry)
                exit_fee = position["qty"] * exit_px * params.fee_rate
                pnl = gross - position["fees"] - exit_fee
                equity += pnl
                trades.append({
                    "symbol": position["symbol"], "side": "long" if side == 1 else "short",
                    "entry_ts": position["entry_ts"], "exit_ts": ts, "legs": position["legs"],
                    "reason": reason, "pnl": pnl,
                })
                curve.append(equity)
                position = None
            else:
                if position["legs"] < params.max_legs:
                    trigger = position["last_add"] * (1.0 + params.add_step_pct * side)
                    reached = close >= trigger if side == 1 else close <= trigger
                    if reached:
                        notional = position["leg_notional"]
                        qty = notional / close
                        position["qty"] += qty
                        position["cost"] += qty * close
                        position["fees"] += notional * params.fee_rate
                        position["legs"] += 1
                        position["last_add"] = close
                position["bars"] += 1
                avg_entry = position["cost"] / position["qty"]
                unrealized = side * position["qty"] * (close - avg_entry)
                curve.append(equity + unrealized - position["fees"])
                continue

        # Rank by rolling 24-hour quote volume using only information available at this timestamp.
        liquid = []
        for symbol, item in series.items():
            index = item["by_ts"].get(ts)
            if index is None or index < 24:
                continue
            rolling_volume = sum(row["quote_volume"] for row in item["candles"][index - 23:index + 1])
            liquid.append((rolling_volume, symbol, index))
        liquid.sort(reverse=True)
        candidates = []
        for rolling_volume, symbol, index in liquid[:20]:
            signal = signal_at(series[symbol], index, params)
            if signal:
                candidates.append((signal["score"], rolling_volume, symbol, index, signal["side"]))
        if not candidates:
            continue
        candidates.sort(reverse=True)
        _, _, symbol, index, side = candidates[0]
        close = series[symbol]["candles"][index]["close"]
        leg_notional = equity * params.leverage / params.max_legs
        qty = leg_notional / close
        entry_fee = leg_notional * params.fee_rate
        position = {
            "symbol": symbol, "side": side, "qty": qty, "cost": qty * close,
            "fees": entry_fee, "legs": 1, "last_add": close, "entry_ts": ts,
            "leg_notional": leg_notional, "bars": 0,
        }
        curve.append(equity - entry_fee)

    open_position = None
    if position is not None:
        item = series[position["symbol"]]
        index = item["by_ts"].get(analysis_ts[-1])
        if index is not None:
            close = item["candles"][index]["close"]
            avg_entry = position["cost"] / position["qty"]
            gross = position["side"] * position["qty"] * (close - avg_entry)
            estimated_exit_fee = position["qty"] * close * params.fee_rate
            net_unrealized = gross - position["fees"] - estimated_exit_fee
            open_position = {
                "symbol": position["symbol"], "side": "long" if position["side"] == 1 else "short",
                "entry_ts": position["entry_ts"], "legs": position["legs"], "net_unrealized": net_unrealized,
            }

    realized = equity - initial_equity
    unrealized = open_position["net_unrealized"] if open_position else 0.0
    total_pnl = realized + unrealized
    closed_wins = sum(trade["pnl"] > 0 for trade in trades)
    return {
        "start_ts": analysis_ts[0], "end_ts": analysis_ts[-1],
        "initial_equity": initial_equity, "realized_pnl": realized,
        "unrealized_pnl": unrealized, "total_pnl": total_pnl,
        "return_pct": total_pnl / initial_equity * 100,
        "max_drawdown_pct": max_drawdown(curve) * 100,
        "closed_trades": len(trades), "wins": closed_wins,
        "win_rate_pct": closed_wins / len(trades) * 100 if trades else 0.0,
        "open_position": open_position, "trades": trades,
    }


def main() -> None:
    params = Params(add_step_pct=0.015, take_profit_pct=0.025, stop_loss_pct=0.025, max_legs=5, leverage=3.0, fee_rate=0.0005)
    universe = load_universe(40)
    data = {}
    failures = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(load_candles, symbol): symbol for symbol in universe}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                loaded_symbol, candles = future.result()
                data[loaded_symbol] = candles
            except Exception as exc:
                failures[symbol] = str(exc)
    result = run_dynamic(data, params)
    local_tz = ZoneInfo("Asia/Shanghai")
    for key in ("start_ts", "end_ts"):
        result[key.replace("_ts", "_time")] = datetime.fromtimestamp(result[key] / 1000, local_tz).isoformat()
    for trade in result["trades"]:
        trade["entry_time"] = datetime.fromtimestamp(trade["entry_ts"] / 1000, local_tz).isoformat()
        trade["exit_time"] = datetime.fromtimestamp(trade["exit_ts"] / 1000, local_tz).isoformat()
    if result["open_position"]:
        result["open_position"]["entry_time"] = datetime.fromtimestamp(result["open_position"]["entry_ts"] / 1000, local_tz).isoformat()
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selection": "major coins excluded; dynamic rolling-24h quote-volume top 20; strongest valid breakout",
        "excluded_symbols": sorted(MAJOR_SYMBOLS), "downloaded_symbols": sorted(data),
        "failures": failures, "parameters": params.__dict__, "result": result,
    }
    target = Path("backend/backtest_results/dynamic_altcoin_pyramid_latest_7d.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
