#!/usr/bin/env python3
"""Walk-forward backtest for a single liquid-altcoin trend pyramiding strategy.

The symbol is selected only by recent quote volume (BTC/ETH excluded), so the
backtest does not pick the best-performing coin after seeing its returns.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


@dataclass(frozen=True)
class Params:
    fast_ema: int = 20
    slow_ema: int = 60
    breakout_bars: int = 20
    add_step_pct: float = 0.015
    take_profit_pct: float = 0.04
    stop_loss_pct: float = 0.03
    max_legs: int = 5
    max_hold_bars: int = 72
    leverage: float = 3.0
    fee_rate: float = 0.0005


def ema(values: Sequence[float], period: int) -> List[float]:
    alpha = 2.0 / (period + 1.0)
    out: List[float] = []
    current = float(values[0])
    for value in values:
        current = alpha * float(value) + (1.0 - alpha) * current
        out.append(current)
    return out


def select_liquid_altcoin(data: Dict, lookback_bars: int = 720) -> Tuple[str, List[Dict]]:
    excluded = {"BTC-USDT-SWAP", "ETH-USDT-SWAP"}
    ranked = []
    for symbol, candles in data["candles"].items():
        if symbol in excluded or len(candles) < 1000:
            continue
        sample = candles[-lookback_bars:]
        avg_quote_volume = sum(float(row.get("quote_volume") or 0) for row in sample) / len(sample)
        ranked.append((avg_quote_volume, symbol))
    if not ranked:
        raise RuntimeError("No eligible altcoin candle series")
    ranked.sort(reverse=True)
    return ranked[0][1], [{"symbol": s, "avg_quote_volume_per_hour": v} for v, s in ranked[:10]]


def max_drawdown(equity_curve: Iterable[float]) -> float:
    peak = 0.0
    drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            drawdown = max(drawdown, (peak - equity) / peak)
    return drawdown


def run_backtest(candles: Sequence[Dict], params: Params, initial_equity: float = 1000.0) -> Dict:
    if len(candles) <= params.slow_ema + params.breakout_bars:
        raise ValueError("Not enough candles")
    closes = [float(row["close"]) for row in candles]
    fast = ema(closes, params.fast_ema)
    slow = ema(closes, params.slow_ema)
    equity = initial_equity
    curve = [equity]
    trades: List[Dict] = []
    position = None
    start = max(params.slow_ema, params.breakout_bars)

    for i in range(start, len(candles)):
        row = candles[i]
        close, high, low = float(row["close"]), float(row["high"]), float(row["low"])

        if position is None:
            prior = candles[i - params.breakout_bars : i]
            prior_high = max(float(item["high"]) for item in prior)
            prior_low = min(float(item["low"]) for item in prior)
            side = 1 if close > prior_high and fast[i] > slow[i] else -1 if close < prior_low and fast[i] < slow[i] else 0
            if side:
                total_notional = equity * params.leverage
                leg_notional = total_notional / params.max_legs
                qty = leg_notional / close
                entry_fee = leg_notional * params.fee_rate
                position = {
                    "side": side,
                    "qty": qty,
                    "cost": qty * close,
                    "fees": entry_fee,
                    "legs": 1,
                    "last_add": close,
                    "entry_i": i,
                    "entry_ts": int(row["ts"]),
                    "entry_equity": equity,
                    "leg_notional": leg_notional,
                }
                curve.append(equity - entry_fee)
            continue

        side = position["side"]
        avg_entry = position["cost"] / position["qty"]
        stop_px = avg_entry * (1.0 - params.stop_loss_pct * side)
        target_px = avg_entry * (1.0 + params.take_profit_pct * side)
        reason = None
        exit_px = close

        # Conservative same-bar ordering: stop is evaluated before target.
        if (side == 1 and low <= stop_px) or (side == -1 and high >= stop_px):
            reason, exit_px = "stop", stop_px
        elif (side == 1 and high >= target_px) or (side == -1 and low <= target_px):
            reason, exit_px = "take_profit", target_px
        elif i - position["entry_i"] >= params.max_hold_bars:
            reason = "timeout"
        elif (side == 1 and fast[i] < slow[i]) or (side == -1 and fast[i] > slow[i]):
            reason = "trend_flip"

        if reason:
            gross = side * position["qty"] * (exit_px - avg_entry)
            exit_fee = position["qty"] * exit_px * params.fee_rate
            pnl = gross - position["fees"] - exit_fee
            equity += pnl
            trades.append({
                "side": "long" if side == 1 else "short",
                "entry_ts": position["entry_ts"],
                "exit_ts": int(row["ts"]),
                "avg_entry": avg_entry,
                "exit_price": exit_px,
                "legs": position["legs"],
                "reason": reason,
                "pnl": pnl,
                "return_on_entry_equity": pnl / position["entry_equity"],
            })
            curve.append(equity)
            position = None
            if equity <= 0:
                break
            continue

        if position["legs"] < params.max_legs:
            add_trigger = position["last_add"] * (1.0 + params.add_step_pct * side)
            reached = close >= add_trigger if side == 1 else close <= add_trigger
            if reached:
                notional = position["leg_notional"]
                qty = notional / close
                position["qty"] += qty
                position["cost"] += qty * close
                position["fees"] += notional * params.fee_rate
                position["legs"] += 1
                position["last_add"] = close

        avg_entry = position["cost"] / position["qty"]
        unrealized = position["side"] * position["qty"] * (close - avg_entry)
        curve.append(equity + unrealized - position["fees"])

    if position is not None:
        row = candles[-1]
        exit_px = float(row["close"])
        avg_entry = position["cost"] / position["qty"]
        gross = position["side"] * position["qty"] * (exit_px - avg_entry)
        exit_fee = position["qty"] * exit_px * params.fee_rate
        pnl = gross - position["fees"] - exit_fee
        equity += pnl
        trades.append({
            "side": "long" if position["side"] == 1 else "short",
            "entry_ts": position["entry_ts"],
            "exit_ts": int(row["ts"]),
            "avg_entry": avg_entry,
            "exit_price": exit_px,
            "legs": position["legs"],
            "reason": "end_of_data",
            "pnl": pnl,
            "return_on_entry_equity": pnl / position["entry_equity"],
        })
        curve.append(equity)

    wins = [trade for trade in trades if trade["pnl"] > 0]
    gross_profit = sum(max(trade["pnl"], 0) for trade in trades)
    gross_loss = -sum(min(trade["pnl"], 0) for trade in trades)
    return {
        "initial_equity": initial_equity,
        "final_equity": equity,
        "net_profit": equity - initial_equity,
        "return_pct": (equity / initial_equity - 1.0) * 100.0,
        "max_drawdown_pct": max_drawdown(curve) * 100.0,
        "trades": len(trades),
        "wins": len(wins),
        "win_rate_pct": (len(wins) / len(trades) * 100.0) if trades else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else math.inf,
        "long_trades": sum(trade["side"] == "long" for trade in trades),
        "short_trades": sum(trade["side"] == "short" for trade in trades),
        "average_legs": sum(trade["legs"] for trade in trades) / len(trades) if trades else 0.0,
        "max_legs_used": max((trade["legs"] for trade in trades), default=0),
        "exit_reasons": {reason: sum(t["reason"] == reason for t in trades) for reason in ("take_profit", "stop", "timeout", "trend_flip", "end_of_data")},
        "trade_log": trades,
    }


def parameter_grid() -> Iterable[Params]:
    for add_step in (0.01, 0.015, 0.02):
        for take_profit in (0.025, 0.035, 0.045):
            for stop_loss in (0.025, 0.035, 0.05):
                yield Params(add_step_pct=add_step, take_profit_pct=take_profit, stop_loss_pct=stop_loss)


def score(result: Dict) -> float:
    return result["return_pct"] - 1.5 * result["max_drawdown_pct"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="backend/backtest_data/explosive_momentum_1h_180d_top80.json")
    parser.add_argument("--output", default="backend/backtest_results/liquid_altcoin_pyramid_180d.json")
    args = parser.parse_args()
    data = json.loads(Path(args.data).read_text())
    symbol, liquidity_ranking = select_liquid_altcoin(data)
    candles = data["candles"][symbol]
    split = int(len(candles) * 2 / 3)
    train, test = candles[:split], candles[split:]

    sweep = []
    for params in parameter_grid():
        result = run_backtest(train, params)
        sweep.append((score(result), params, result))
    sweep.sort(key=lambda item: item[0], reverse=True)
    _, best_params, train_result = sweep[0]
    test_result = run_backtest(test, best_params)
    full_result = run_backtest(candles, best_params)
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_metadata": data.get("metadata", {}),
        "selection_rule": "highest trailing-30d average hourly quote volume; BTC/ETH excluded",
        "selected_symbol": symbol,
        "liquidity_ranking": liquidity_ranking,
        "parameters": asdict(best_params),
        "capital_model": "1000 USDT equity, 3x maximum notional, five equal 600 USDT legs",
        "train": train_result,
        "out_of_sample": test_result,
        "full_period": full_result,
        "top_train_variants": [
            {"score": item[0], "parameters": asdict(item[1]), "result": {k: v for k, v in item[2].items() if k != "trade_log"}}
            for item in sweep[:10]
        ],
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2))
    compact = {k: v for k, v in output.items() if k not in {"train", "out_of_sample", "full_period", "top_train_variants"}}
    compact["train"] = {k: v for k, v in train_result.items() if k != "trade_log"}
    compact["out_of_sample"] = {k: v for k, v in test_result.items() if k != "trade_log"}
    compact["full_period"] = {k: v for k, v in full_result.items() if k != "trade_log"}
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
