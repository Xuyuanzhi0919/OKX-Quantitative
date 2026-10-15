#!/usr/bin/env python3
"""Risk-adjusted optimizer for the explosive momentum chaser.

The long history is split into a training section and a later validation
section.  Random windows are drawn only from training.  A separate cache is
used as the final holdout and never participates in parameter selection.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backtest_altcoin_pump_short import load_cache
from optimize_explosive_momentum import Config, build_snapshots, evaluate


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
INITIAL_CAPITAL = 1000.0
CURRENT_CONFIG = Config(
    min_signal=0.04,
    max_signal=0.10,
    min_gap=0.03,
    min_vol_ratio=3.0,
    max_vol_ratio=50.0,
    max_ret_4h=0.15,
    max_ret_24h=0.40,
    take_profit_pct=0.10,
    stop_loss_pct=0.05,
    hold_hours=3,
    market_filter="none",
    universe_size=80,
    leverage=3,
    cooldown_hours=2,
)


PARAMETER_SPACE: dict[str, list[Any]] = {
    "min_signal": [0.04, 0.05, 0.06, 0.07],
    "max_signal": [0.08, 0.10, 0.12, None],
    "min_gap": [0.01, 0.02, 0.03, 0.04],
    "min_vol_ratio": [2.5, 3.0, 4.0, 5.0],
    "max_vol_ratio": [10.0, 20.0, 50.0, None],
    "max_ret_4h": [0.10, 0.12, 0.15, 0.20],
    "max_ret_24h": [0.25, 0.40, 0.60],
    "hold_hours": [2, 3, 4, 6],
    "stop_loss_pct": [0.03, 0.04, 0.05, 0.06],
    "take_profit_pct": [0.06, 0.08, 0.10, 0.12],
    "market_filter": ["none", "btc_4h_positive"],
    "universe_size": [30, 50, 80],
    "cooldown_hours": [2, 4, 8],
}
POSITION_CAPS_USDT = [500.0, 750.0, 1000.0, 1250.0, 1500.0, 2000.0, 3000.0]


@dataclass(frozen=True)
class Candidate:
    config: Config
    position_cap_usdt: float


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def signal_returns(config: Config, snapshots, indexes, start_ms: int, end_ms: int):
    result = evaluate(
        config,
        snapshots,
        indexes,
        start_ms,
        end_ms,
        initial_capital=INITIAL_CAPITAL,
        max_position_usd=INITIAL_CAPITAL,
        include_trades=True,
    )
    return result, result["trades_detail"]


def revalue(base: dict[str, Any], trades: list[dict[str, Any]], position_cap_usdt: float) -> dict[str, Any]:
    equity = INITIAL_CAPITAL
    peak = equity
    max_drawdown = 0.0
    pnl_values: list[float] = []
    returns: list[float] = []
    reasons = {"take_profit": 0, "stop_loss": 0, "time_exit": 0}
    detail = []
    for trade in trades:
        position_return = trade["net_position_return_pct"] / 100
        # Match the live strategy's _calc_contract_qty(): the configured cap is
        # nominal position value, while 25% of available balance is reserved.
        notional = min(position_cap_usdt, max(equity, 0.0) * 0.75 * CURRENT_CONFIG.leverage)
        pnl = notional * position_return
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak if peak > 0 else 1.0)
        pnl_values.append(pnl)
        returns.append(position_return)
        reasons[trade["reason"]] += 1
        detail.append({**trade, "position_notional_usd": notional, "pnl_usdt": pnl, "equity_usdt": equity})
    gross_profit = sum(value for value in pnl_values if value > 0)
    gross_loss = -sum(value for value in pnl_values if value < 0)
    return {
        "initial_capital": INITIAL_CAPITAL,
        "final_capital": equity,
        "total_pnl_usdt": equity - INITIAL_CAPITAL,
        "return_pct": (equity / INITIAL_CAPITAL - 1) * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "trades": len(trades),
        "win_rate_pct": sum(value > 0 for value in pnl_values) / len(pnl_values) * 100 if pnl_values else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "average_position_return_pct": statistics.fmean(returns) * 100 if returns else 0.0,
        "worst_position_return_pct": min(returns, default=0.0) * 100,
        "best_position_return_pct": max(returns, default=0.0) * 100,
        "exit_reasons": reasons,
        "ruined": equity <= 0,
        "trades_detail": detail,
        "base_signal_metrics": {key: base[key] for key in ("trades", "win_rate_pct", "exit_reasons")},
    }


def evaluate_candidate(candidate: Candidate, snapshots, indexes, start: datetime, end: datetime):
    base, trades = signal_returns(
        candidate.config,
        snapshots,
        indexes,
        int(start.timestamp() * 1000),
        int(end.timestamp() * 1000),
    )
    return revalue(base, trades, candidate.position_cap_usdt)


def candidate_dict(candidate: Candidate) -> dict[str, Any]:
    return {"config": asdict(candidate.config), "position_cap_usdt": candidate.position_cap_usdt}


def generate_candidates(count: int, seed: int) -> list[Candidate]:
    rng = random.Random(seed)
    fields = list(PARAMETER_SPACE)
    candidates = {
        Candidate(CURRENT_CONFIG, position_cap)
        for position_cap in POSITION_CAPS_USDT
    }
    while len(candidates) < count:
        config = Config(
            **{field: rng.choice(PARAMETER_SPACE[field]) for field in fields},
            leverage=3,
        )
        candidates.add(Candidate(config, rng.choice(POSITION_CAPS_USDT)))
    return list(candidates)


def random_windows(start: datetime, end: datetime, count: int, days: int, seed: int):
    latest = end - timedelta(days=days)
    span_hours = int((latest - start).total_seconds() // 3600)
    rng = random.Random(seed)
    offsets = {0, span_hours}
    while len(offsets) < count:
        offsets.add(rng.randrange(span_hours + 1))
    return [(start + timedelta(hours=offset), start + timedelta(hours=offset, days=days)) for offset in sorted(offsets)]


def random_metrics(candidate: Candidate, windows, snapshots, indexes) -> dict[str, Any]:
    metrics = [evaluate_candidate(candidate, snapshots, indexes, start, end) for start, end in windows]
    returns = [item["return_pct"] for item in metrics]
    drawdowns = [item["max_drawdown_pct"] for item in metrics]
    trades = [item["trades"] for item in metrics]
    return {
        **candidate_dict(candidate),
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
        "window_drawdowns_pct": drawdowns,
    }


def strip_trades(metrics: dict[str, Any]) -> dict[str, Any]:
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

    candidates = generate_candidates(args.config_count, args.seed)
    aggregate = []
    for candidate in candidates:
        metrics = evaluate_candidate(candidate, train_snapshots, train_indexes, history_start, validation_start)
        if metrics["trades"] < args.minimum_train_trades or metrics["ruined"]:
            continue
        score = metrics["return_pct"] - 0.75 * metrics["max_drawdown_pct"]
        aggregate.append((score, candidate, metrics))
    aggregate.sort(key=lambda item: item[0], reverse=True)

    # Keep position-cap groups represented so raw return cannot crowd conservative
    # candidates out before the random-window stage.
    shortlist: list[Candidate] = []
    per_position_cap = max(1, args.shortlist // len(POSITION_CAPS_USDT))
    for position_cap in POSITION_CAPS_USDT:
        position_cap_group = [
            item[1]
            for item in aggregate
            if item[1].position_cap_usdt == position_cap
        ]
        shortlist.extend(position_cap_group[:per_position_cap])
    for position_cap in (1000.0, 3000.0):
        baseline = Candidate(CURRENT_CONFIG, position_cap)
        if baseline not in shortlist:
            shortlist.append(baseline)

    robust = [random_metrics(candidate, windows, train_snapshots, train_indexes) for candidate in shortlist]
    eligible = [
        item for item in robust
        if item["positive_window_rate_pct"] >= args.minimum_positive_window_rate
        and item["p10_return_pct"] >= args.minimum_p10_return
        and item["worst_drawdown_pct"] <= args.maximum_window_drawdown
        and item["median_trades"] >= args.minimum_window_trades
    ]
    eligible.sort(
        key=lambda item: item["median_return_pct"] + 0.5 * item["p10_return_pct"] - 0.5 * item["median_drawdown_pct"],
        reverse=True,
    )

    validated = []
    for item in eligible[: args.validation_candidates]:
        candidate = Candidate(Config(**item["config"]), item["position_cap_usdt"])
        metrics = evaluate_candidate(candidate, train_snapshots, train_indexes, validation_start, history_end)
        if (
            metrics["trades"] >= args.minimum_validation_trades
            and metrics["return_pct"] > 0
            and metrics["max_drawdown_pct"] <= args.maximum_validation_drawdown
            and (metrics["profit_factor"] or 0.0) >= args.minimum_validation_profit_factor
        ):
            validation_score = (
                metrics["return_pct"]
                - 0.75 * metrics["max_drawdown_pct"]
                + 0.25 * item["median_return_pct"]
                + 0.25 * item["p10_return_pct"]
            )
            validated.append((validation_score, candidate, item, metrics))
    if not validated:
        raise RuntimeError("no candidate passed validation and risk thresholds")
    validated.sort(key=lambda item: item[0], reverse=True)
    _, selected, selected_random, selected_validation = validated[0]

    baselines = {
        "current_cap_1000": Candidate(CURRENT_CONFIG, 1000.0),
        "requested_cap_3000": Candidate(CURRENT_CONFIG, 3000.0),
    }
    selected_final = evaluate_candidate(
        selected,
        final_snapshots,
        final_indexes,
        final_start,
        final_end,
    )
    selected_passes_final = (
        selected_final["return_pct"] > 0
        and selected_final["max_drawdown_pct"] <= args.maximum_validation_drawdown
        and (selected_final["profit_factor"] or 0.0) >= args.minimum_validation_profit_factor
    )
    result = {
        "method": {
            "seed": args.seed,
            "generated_candidates": len(candidates),
            "aggregate_eligible": len(aggregate),
            "shortlist": len(shortlist),
            "random_windows": len(windows),
            "window_days": args.window_days,
            "final_holdout_used_for_selection": False,
            "capital_model": "position notional = min(position_cap_usdt, current equity * 0.75 * leverage)",
            "initial_capital_usdt": INITIAL_CAPITAL,
        },
        "periods": {
            "training_start": history_start.isoformat(),
            "training_end": validation_start.isoformat(),
            "validation_start": validation_start.isoformat(),
            "validation_end": history_end.isoformat(),
            "final_holdout_start": final_start.isoformat(),
            "final_holdout_end_exclusive": final_end.isoformat(),
        },
        "thresholds": {
            "minimum_positive_window_rate_pct": args.minimum_positive_window_rate,
            "minimum_p10_return_pct": args.minimum_p10_return,
            "maximum_window_drawdown_pct": args.maximum_window_drawdown,
            "maximum_validation_drawdown_pct": args.maximum_validation_drawdown,
            "minimum_validation_profit_factor": args.minimum_validation_profit_factor,
        },
        "selected": candidate_dict(selected),
        "selected_random_validation": selected_random,
        "selected_later_validation": strip_trades(selected_validation),
        "selected_final_holdout": strip_trades(selected_final),
        "automatic_candidate_decision": "accept" if selected_passes_final else "reject",
        "baselines": {},
        "top_validated": [],
        "runtime_seconds": time.monotonic() - started,
    }
    for name, candidate in baselines.items():
        result["baselines"][name] = {
            "candidate": candidate_dict(candidate),
            "random_validation": random_metrics(candidate, windows, train_snapshots, train_indexes),
            "later_validation": strip_trades(evaluate_candidate(candidate, train_snapshots, train_indexes, validation_start, history_end)),
            "final_holdout": strip_trades(evaluate_candidate(candidate, final_snapshots, final_indexes, final_start, final_end)),
        }
    for score, candidate, random_result, validation_result in validated[:20]:
        result["top_validated"].append({
            "score": score,
            "candidate": candidate_dict(candidate),
            "random_validation": random_result,
            "later_validation": strip_trades(validation_result),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    summary = dict(result)
    summary.pop("top_validated")
    for value in summary["baselines"].values():
        value["random_validation"] = {
            key: item for key, item in value["random_validation"].items()
            if key not in {"window_returns_pct", "window_drawdowns_pct"}
        }
    summary["selected_random_validation"] = {
        key: item for key, item in summary["selected_random_validation"].items()
        if key not in {"window_returns_pct", "window_drawdowns_pct"}
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-cache", type=Path, required=True)
    parser.add_argument("--final-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--final-start", default="2026-08-01 00:00")
    parser.add_argument("--final-end", default="2026-08-16 00:00")
    parser.add_argument("--validation-days", type=int, default=30)
    parser.add_argument("--window-count", type=int, default=24)
    parser.add_argument("--window-days", type=int, default=15)
    parser.add_argument("--config-count", type=int, default=6000)
    parser.add_argument("--shortlist", type=int, default=420)
    parser.add_argument("--validation-candidates", type=int, default=100)
    parser.add_argument("--minimum-train-trades", type=int, default=80)
    parser.add_argument("--minimum-window-trades", type=float, default=8)
    parser.add_argument("--minimum-validation-trades", type=int, default=10)
    parser.add_argument("--minimum-positive-window-rate", type=float, default=65.0)
    parser.add_argument("--minimum-p10-return", type=float, default=-15.0)
    parser.add_argument("--maximum-window-drawdown", type=float, default=35.0)
    parser.add_argument("--maximum-validation-drawdown", type=float, default=25.0)
    parser.add_argument("--minimum-validation-profit-factor", type=float, default=1.10)
    parser.add_argument("--seed", type=int, default=20260817)
    return parser.parse_args()


if __name__ == "__main__":
    main()
