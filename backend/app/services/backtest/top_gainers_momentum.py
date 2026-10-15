"""
涨幅榜短线动量分析

实时获取 OKX USDT 永续涨幅榜前三，并用多周期 EMA 动量规则做近 24 小时
快速回测和当前信号评估。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import socket
from typing import Dict, List, Optional

from app.core.config import settings
from app.services.exchange.okx import OKXExchange


EXCLUDED_SYMBOLS = {"BTC-USDT-SWAP", "ETH-USDT-SWAP"}
SUPPORTED_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1H", "4H"}


@dataclass
class Candle:
    ts: int
    high: float
    low: float
    close: float


class TopGainersMomentumAnalyzer:
    """Analyze current top gainers with an aggressive short-term momentum model."""

    def __init__(self, exchange: Optional[OKXExchange] = None):
        self.exchange = exchange or OKXExchange(
            api_key=settings.OKX_API_KEY or "",
            secret_key=settings.OKX_SECRET_KEY or "",
            passphrase=settings.OKX_PASSPHRASE or "",
            simulated=settings.OKX_SIMULATED,
            proxy=self._resolve_proxy(),
        )

    @staticmethod
    def _resolve_proxy() -> Optional[str]:
        if settings.OKX_PROXY:
            return settings.OKX_PROXY
        try:
            with socket.create_connection(("127.0.0.1", 7897), timeout=0.2):
                return "http://127.0.0.1:7897"
        except OSError:
            return None

    async def close(self):
        if self.exchange.session:
            await self.exchange.session.close()

    async def analyze(
        self,
        timeframe: str = "15m",
        top_n: int = 3,
        initial_capital: float = 1000.0,
        lookback_hours: int = 24,
    ) -> Dict:
        timeframe = timeframe if timeframe in SUPPORTED_TIMEFRAMES else "15m"
        top_n = max(1, min(top_n, 10))
        lookback_hours = max(1, min(lookback_hours, 72))

        tickers = await self.exchange.get_tickers("SWAP")
        top_gainers = self._top_usdt_swap_gainers(tickers, top_n)
        if not top_gainers:
            raise ValueError("未获取到 OKX USDT 永续涨幅榜数据")

        raw_by_symbol: Dict[str, List[Candle]] = {}
        for item in top_gainers:
            raw = await self.exchange.get_kline(item["symbol"], timeframe, limit=300)
            raw_by_symbol[item["symbol"]] = self._parse_candles(raw)

        last_ts = min(candles[-1].ts for candles in raw_by_symbol.values() if candles)
        start_ts = last_ts - lookback_hours * 60 * 60 * 1000

        results = []
        for item in top_gainers:
            symbol = item["symbol"]
            candles = raw_by_symbol[symbol]
            backtest = self._simulate(candles, timeframe, initial_capital, start_ts)
            signal = self._signal(candles, timeframe)
            results.append(
                {
                    **item,
                    "backtest": backtest,
                    "signal": signal,
                }
            )

        average_final = sum(r["backtest"]["final_equity"] for r in results) / len(
            results
        )

        return {
            "timeframe": timeframe,
            "top_n": top_n,
            "initial_capital": initial_capital,
            "lookback_hours": lookback_hours,
            "window": {
                "start": start_ts,
                "end": last_ts,
                "start_str": datetime.fromtimestamp(start_ts / 1000).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "end_str": datetime.fromtimestamp(last_ts / 1000).strftime(
                    "%Y-%m-%d %H:%M"
                ),
            },
            "strategy": {
                "name": "top_gainers_ema_momentum",
                "description": "涨幅榜前三 + 多周期 EMA 动量 + ATR 止损止盈",
                "params": self._params(timeframe),
            },
            "results": results,
            "basket": {
                "final_equity": average_final,
                "return_pct": (average_final / initial_capital - 1) * 100,
            },
        }

    def _top_usdt_swap_gainers(self, tickers: List[Dict], top_n: int) -> List[Dict]:
        gainers = []
        for ticker in tickers:
            symbol = str(ticker.get("instId") or "")
            if not symbol.endswith("-USDT-SWAP") or symbol in EXCLUDED_SYMBOLS:
                continue
            last = self._safe_float(ticker.get("last"))
            open_24h = self._safe_float(ticker.get("open24h"))
            if last <= 0 or open_24h <= 0:
                continue
            change_pct = (last - open_24h) / open_24h * 100
            gainers.append(
                {
                    "symbol": symbol,
                    "last": last,
                    "change_24h_pct": change_pct,
                    "volume_24h": self._safe_float(
                        ticker.get("volCcy24h") or ticker.get("vol24h")
                    ),
                }
            )
        gainers.sort(key=lambda item: item["change_24h_pct"], reverse=True)
        return gainers[:top_n]

    @staticmethod
    def _parse_candles(raw: List[Dict]) -> List[Candle]:
        candles = [
            Candle(
                ts=int(item["ts"]),
                high=float(item["h"]),
                low=float(item["l"]),
                close=float(item["c"]),
            )
            for item in raw
            if str(item.get("confirm", "1")) == "1"
        ]
        return sorted(candles, key=lambda candle: candle.ts)

    @staticmethod
    def _params(timeframe: str) -> Dict:
        if timeframe == "1m":
            return {
                "risk_pct": 0.018,
                "max_leverage": 4,
                "stop_atr": 1.6,
                "take_profit_r": 1.5,
                "trailing_atr": 1.4,
                "max_hold_bars": 45,
            }
        if timeframe == "5m":
            return {
                "risk_pct": 0.025,
                "max_leverage": 5,
                "stop_atr": 1.8,
                "take_profit_r": 1.8,
                "trailing_atr": 1.6,
                "max_hold_bars": 36,
            }
        if timeframe == "30m":
            return {
                "risk_pct": 0.03,
                "max_leverage": 5,
                "stop_atr": 2.3,
                "take_profit_r": 2.1,
                "trailing_atr": 1.9,
                "max_hold_bars": 24,
            }
        if timeframe == "1H":
            return {
                "risk_pct": 0.025,
                "max_leverage": 4,
                "stop_atr": 2.5,
                "take_profit_r": 2.2,
                "trailing_atr": 2.0,
                "max_hold_bars": 18,
            }
        if timeframe == "4H":
            return {
                "risk_pct": 0.018,
                "max_leverage": 3,
                "stop_atr": 2.8,
                "take_profit_r": 2.4,
                "trailing_atr": 2.2,
                "max_hold_bars": 12,
            }
        return {
            "risk_pct": 0.035,
            "max_leverage": 7,
            "stop_atr": 2.1,
            "take_profit_r": 2.0,
            "trailing_atr": 1.8,
            "max_hold_bars": 32,
        }

    def _simulate(
        self,
        candles: List[Candle],
        timeframe: str,
        initial_capital: float,
        start_ts: int,
    ) -> Dict:
        if len(candles) < 90:
            return {
                "final_equity": initial_capital,
                "return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "closed_trades": 0,
                "win_rate_pct": 0.0,
                "trades": [],
            }

        high = [c.high for c in candles]
        low = [c.low for c in candles]
        close = [c.close for c in candles]
        ts = [c.ts for c in candles]

        e5 = self._ema(close, 5)
        e9 = self._ema(close, 9)
        e21 = self._ema(close, 21)
        e55 = self._ema(close, 55)
        e144 = self._ema(close, 144 if len(close) > 180 else 89)
        atr = self._atr(high, low, close)
        rsi = self._rsi(close)
        params = self._params(timeframe)

        capital = initial_capital
        position_qty = 0.0
        entry = 0.0
        stop = 0.0
        take = 0.0
        entry_index = 0
        equity_curve: List[float] = []
        trades: List[Dict] = []
        active = False
        warmup = 80 if timeframe == "5m" else 120

        for i in range(min(warmup, len(close) - 1), len(close)):
            if ts[i] >= start_ts and not active:
                active = True
                capital = initial_capital
                position_qty = 0.0
                trades = []
                equity_curve = []
            if not active:
                continue

            price = close[i]
            if position_qty > 0:
                if price - entry > entry - stop:
                    stop = max(stop, price - params["trailing_atr"] * atr[i])
                exit_price = None
                reason = None
                if low[i] <= stop:
                    exit_price = stop
                    reason = "stop"
                elif high[i] >= take:
                    exit_price = take
                    reason = "take"
                elif i - entry_index >= params["max_hold_bars"]:
                    exit_price = price
                    reason = "time"
                if exit_price is not None:
                    pnl = (
                        exit_price - entry
                    ) * position_qty - exit_price * position_qty * 0.0005
                    capital += entry * position_qty / params["max_leverage"] + pnl
                    trades.append(
                        self._trade(ts[i], "exit", reason, exit_price, pnl, capital)
                    )
                    position_qty = 0.0

            equity = capital
            if position_qty > 0:
                equity += (
                    price - entry
                ) * position_qty + entry * position_qty / params["max_leverage"]
            equity_curve.append(equity)

            if position_qty > 0:
                continue

            trend = close[i] > e55[i] and e9[i] > e21[i]
            major = close[i] > e144[i] if len(close) > 160 else True
            cross = e5[i - 1] <= e9[i - 1] and e5[i] > e9[i]
            pullback = low[i] <= e21[i] and close[i] > e9[i]
            momentum = 45 <= rsi[i] <= 74
            atr_ok = 0.002 <= atr[i] / price <= 0.08

            if trend and major and momentum and atr_ok and (cross or pullback):
                entry = price
                stop = entry - params["stop_atr"] * atr[i]
                risk = entry - stop
                if risk <= 0:
                    continue
                qty_by_risk = capital * params["risk_pct"] / risk
                qty_by_leverage = capital * params["max_leverage"] / entry
                qty = min(qty_by_risk, qty_by_leverage)
                fee = entry * qty * 0.0005
                margin = entry * qty / params["max_leverage"]
                if qty > 0 and margin + fee < capital:
                    capital -= margin + fee
                    position_qty = qty
                    take = entry + params["take_profit_r"] * risk
                    entry_index = i
                    trades.append(
                        self._trade(ts[i], "entry", "signal", entry, 0.0, capital)
                    )

        if active and position_qty > 0:
            exit_price = close[-1]
            pnl = (
                exit_price - entry
            ) * position_qty - exit_price * position_qty * 0.0005
            capital += entry * position_qty / params["max_leverage"] + pnl
            trades.append(
                self._trade(ts[-1], "exit", "final", exit_price, pnl, capital)
            )
            equity_curve.append(capital)

        final_equity = equity_curve[-1] if equity_curve else initial_capital
        exits = [trade for trade in trades if trade["side"] == "exit"]
        wins = [trade for trade in exits if trade["pnl"] > 0]

        return {
            "final_equity": final_equity,
            "return_pct": (final_equity / initial_capital - 1) * 100,
            "max_drawdown_pct": self._max_drawdown(equity_curve or [initial_capital]),
            "closed_trades": len(exits),
            "win_rate_pct": len(wins) / len(exits) * 100 if exits else 0.0,
            "trades": trades[-8:],
        }

    def _signal(self, candles: List[Candle], timeframe: str) -> Dict:
        high = [c.high for c in candles]
        low = [c.low for c in candles]
        close = [c.close for c in candles]
        e5 = self._ema(close, 5)
        e9 = self._ema(close, 9)
        e21 = self._ema(close, 21)
        e55 = self._ema(close, 55)
        e144 = self._ema(close, 144 if len(close) > 180 else 89)
        atr = self._atr(high, low, close)
        rsi = self._rsi(close)
        params = self._params(timeframe)
        i = len(close) - 1

        trend = close[i] > e55[i] and e9[i] > e21[i]
        major = close[i] > e144[i] if len(close) > 160 else True
        cross = e5[i - 1] <= e9[i - 1] and e5[i] > e9[i]
        recent_cross = any(
            e5[j - 1] <= e9[j - 1] and e5[j] > e9[j]
            for j in range(max(1, i - 3), i + 1)
        )
        dist_e21_pct = (close[i] - e21[i]) / close[i] * 100
        near_e21_pct = abs(dist_e21_pct)
        overheat = rsi[i] > 74 or dist_e21_pct > 2.5

        if trend and major and cross and 45 <= rsi[i] <= 74:
            status = "当前触发"
            action = "small_entry"
        elif trend and major and recent_cross and 45 <= rsi[i] <= 74:
            status = "刚触发"
            action = "watch_or_small_entry"
        elif trend and major and near_e21_pct < 0.8 and rsi[i] <= 70:
            status = "等回踩/上穿"
            action = "wait"
        elif trend and major and overheat:
            status = "过热等回踩"
            action = "wait_pullback"
        else:
            status = "暂缓"
            action = "skip"

        stop = close[i] - params["stop_atr"] * atr[i]
        take = close[i] + params["take_profit_r"] * (close[i] - stop)
        return {
            "status": status,
            "action": action,
            "last": close[i],
            "rsi": rsi[i],
            "dist_e21_pct": dist_e21_pct,
            "atr_pct": atr[i] / close[i] * 100,
            "stop": stop,
            "take_profit": take,
        }

    @staticmethod
    def _trade(
        ts: int, side: str, reason: str, price: float, pnl: float, equity: float
    ) -> Dict:
        return {
            "timestamp": ts,
            "time": datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M"),
            "side": side,
            "reason": reason,
            "price": price,
            "pnl": pnl,
            "equity": equity,
        }

    @staticmethod
    def _ema(values: List[float], period: int) -> List[float]:
        output = []
        multiplier = 2 / (period + 1)
        previous = None
        for value in values:
            previous = (
                value
                if previous is None
                else previous + (value - previous) * multiplier
            )
            output.append(previous)
        return output

    @classmethod
    def _atr(
        cls,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14,
    ) -> List[float]:
        true_ranges = []
        for i, close in enumerate(closes):
            if i == 0:
                true_ranges.append(highs[i] - lows[i])
            else:
                true_ranges.append(
                    max(
                        highs[i] - lows[i],
                        abs(highs[i] - closes[i - 1]),
                        abs(lows[i] - closes[i - 1]),
                    )
                )
        return cls._ema(true_ranges, period)

    @staticmethod
    def _rsi(closes: List[float], period: int = 14) -> List[float]:
        output = []
        gains = []
        losses = []
        for i, close in enumerate(closes):
            if i == 0:
                output.append(50.0)
                continue
            delta = close - closes[i - 1]
            gains.append(max(delta, 0.0))
            losses.append(max(-delta, 0.0))
            if len(gains) > period:
                gains.pop(0)
                losses.pop(0)
            avg_gain = sum(gains) / len(gains)
            avg_loss = sum(losses) / len(losses)
            output.append(
                100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
            )
        return output

    @staticmethod
    def _max_drawdown(equity_curve: List[float]) -> float:
        peak = equity_curve[0]
        max_drawdown = 0.0
        for equity in equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak)
        return max_drawdown * 100

    @staticmethod
    def _safe_float(value) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
