"""
山寨币短线异动监控。

定期扫描 OKX USDT 永续行情：
- ticker 级别短窗口涨幅
- 5m K线级别涨幅 + 成交量突增
"""

import asyncio
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Set

from loguru import logger

from app.core.config import settings
from app.services.exchange.okx import OKXExchange
from app.services.notification.notification_service import (
    NotificationLevel,
    notification_service,
)


MAJOR_AND_STABLE_COINS = {
    "BTC",
    "ETH",
    "USDT",
    "USDC",
    "DAI",
    "FDUSD",
    "TUSD",
    "USDD",
    "USD",
}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def base_ccy_from_inst_id(inst_id: str) -> str:
    return inst_id.split("-")[0].upper() if inst_id else ""


class AltcoinMomentumMonitor:
    """1分钟山寨币涨幅监控器。"""

    def __init__(self):
        self.enabled = False
        self.interval_seconds = 15
        self.window_seconds = 60
        self.threshold_pct = 5.0
        self.windows = [{"window_seconds": 60, "threshold_pct": 5.0}]
        self.cooldown_seconds = 600
        self.inst_type = "SWAP"
        self.quote_ccy = "USDT"
        self.min_volume_usdt = 1000000
        self.exclude_majors = True
        self.user_id = 1
        self.kline_monitor_enabled = True
        self.kline_timeframe = "5m"
        self.kline_scan_interval_seconds = 60
        self.kline_change_threshold_pct = 3.0
        self.kline_volume_spike_multiple = 3.0
        self.kline_volume_lookback = 20
        self.kline_min_volume_usdt = 200000
        self.kline_max_symbols_per_scan = 80
        self._task: Optional[asyncio.Task] = None
        self._exchange: Optional[OKXExchange] = None
        self._price_history: Dict[str, Deque[tuple[float, float]]] = defaultdict(deque)
        self._last_alert_at: Dict[str, float] = {}
        self._last_kline_alert_at: Dict[str, float] = {}
        self._last_kline_scan_at = 0.0
        self._recent_signals: Deque[Dict[str, Any]] = deque(maxlen=100)
        self._seen_symbols: Set[str] = set()

    def configure(self, config: Dict[str, Any]):
        self.enabled = bool(config.get("enabled", False))
        self.interval_seconds = int(
            config.get("interval_seconds", self.interval_seconds)
        )
        self.window_seconds = int(config.get("window_seconds", self.window_seconds))
        self.threshold_pct = float(config.get("threshold_pct", self.threshold_pct))
        configured_windows = config.get("windows")
        if isinstance(configured_windows, list) and configured_windows:
            self.windows = []
            for item in configured_windows:
                if not isinstance(item, dict):
                    continue
                window_seconds = int(item.get("window_seconds", self.window_seconds))
                threshold_pct = float(item.get("threshold_pct", self.threshold_pct))
                if window_seconds > 0 and threshold_pct > 0:
                    self.windows.append(
                        {
                            "window_seconds": window_seconds,
                            "threshold_pct": threshold_pct,
                        }
                    )
            if not self.windows:
                self.windows = [
                    {
                        "window_seconds": self.window_seconds,
                        "threshold_pct": self.threshold_pct,
                    }
                ]
        else:
            self.windows = [
                {
                    "window_seconds": self.window_seconds,
                    "threshold_pct": self.threshold_pct,
                }
            ]
        self.cooldown_seconds = int(
            config.get("cooldown_seconds", self.cooldown_seconds)
        )
        self.inst_type = str(config.get("inst_type", self.inst_type)).upper()
        self.quote_ccy = str(config.get("quote_ccy", self.quote_ccy)).upper()
        self.min_volume_usdt = float(
            config.get("min_volume_usdt", self.min_volume_usdt)
        )
        self.exclude_majors = bool(config.get("exclude_majors", self.exclude_majors))
        self.user_id = int(config.get("user_id", self.user_id))
        self.kline_monitor_enabled = bool(
            config.get("kline_monitor_enabled", self.kline_monitor_enabled)
        )
        self.kline_timeframe = str(config.get("kline_timeframe", self.kline_timeframe))
        if self.kline_timeframe not in {"1m", "3m", "5m", "15m"}:
            self.kline_timeframe = "5m"
        self.kline_scan_interval_seconds = int(
            config.get(
                "kline_scan_interval_seconds",
                self.kline_scan_interval_seconds,
            )
        )
        self.kline_change_threshold_pct = float(
            config.get(
                "kline_change_threshold_pct",
                self.kline_change_threshold_pct,
            )
        )
        self.kline_volume_spike_multiple = float(
            config.get(
                "kline_volume_spike_multiple",
                self.kline_volume_spike_multiple,
            )
        )
        self.kline_volume_lookback = int(
            config.get("kline_volume_lookback", self.kline_volume_lookback)
        )
        self.kline_min_volume_usdt = float(
            config.get("kline_min_volume_usdt", self.kline_min_volume_usdt)
        )
        self.kline_max_symbols_per_scan = int(
            config.get(
                "kline_max_symbols_per_scan",
                self.kline_max_symbols_per_scan,
            )
        )

    async def start(self):
        if not self.enabled:
            logger.info("山寨币短线异动监控未启用")
            return
        bark = notification_service.channels.get("bark")
        if not bark or not bark.is_enabled():
            logger.warning("Bark渠道未启用，山寨币短线异动监控不启动")
            return
        if self._task and not self._task.done():
            logger.warning("山寨币短线异动监控已在运行")
            return

        self._exchange = OKXExchange(
            api_key="",
            secret_key="",
            passphrase="",
            simulated=False,
            proxy=settings.OKX_PROXY,
        )
        self._task = asyncio.create_task(self._monitor_loop())
        windows_text = ", ".join(
            f"{item['window_seconds']}s>={item['threshold_pct']}%"
            for item in self.windows
        )
        logger.info(
            f"山寨币短线异动监控已启动: windows=[{windows_text}], "
            f"interval={self.interval_seconds}s, "
            f"kline={self.kline_timeframe if self.kline_monitor_enabled else 'disabled'}"
        )

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._exchange:
            try:
                await self._exchange.close()
            except Exception:
                pass
            self._exchange = None

        logger.info("山寨币短线异动监控已停止")

    async def _monitor_loop(self):
        while True:
            try:
                await self._scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"山寨币短线异动监控出错: {exc}")

            await asyncio.sleep(self.interval_seconds)

    async def _scan_once(self):
        if not self._exchange:
            return

        now = time.time()
        tickers = await self._exchange.get_tickers(self.inst_type)
        supported_tickers = [
            ticker
            for ticker in tickers
            if self._is_supported_symbol(str(ticker.get("instId") or ""))
        ]

        if (
            self.kline_monitor_enabled
            and now - self._last_kline_scan_at >= self.kline_scan_interval_seconds
        ):
            self._last_kline_scan_at = now
            await self._scan_kline_spikes(supported_tickers, now)

        for ticker in supported_tickers:
            symbol = str(ticker.get("instId") or "")
            last = safe_float(ticker.get("last"))
            if last <= 0:
                continue

            volume_usdt = self._volume_usdt(ticker)
            if volume_usdt < self.min_volume_usdt:
                continue

            history = self._price_history[symbol]
            history.append((now, last))
            max_window_seconds = max(item["window_seconds"] for item in self.windows)
            while history and now - history[0][0] > max_window_seconds * 2:
                history.popleft()

            for window in self.windows:
                window_seconds = window["window_seconds"]
                threshold_pct = window["threshold_pct"]
                baseline = self._find_baseline(history, now, window_seconds)
                if not baseline:
                    continue

                baseline_ts, baseline_price = baseline
                if baseline_price <= 0 or now - baseline_ts < window_seconds * 0.8:
                    continue

                change_pct = (last - baseline_price) / baseline_price * 100
                if change_pct >= threshold_pct:
                    await self._maybe_alert(
                        symbol,
                        last,
                        baseline_price,
                        change_pct,
                        volume_usdt,
                        now,
                        window_seconds,
                        threshold_pct,
                    )

    def _is_supported_symbol(self, symbol: str) -> bool:
        if self.inst_type == "SWAP":
            suffix = f"-{self.quote_ccy}-SWAP"
        else:
            suffix = f"-{self.quote_ccy}"

        if not symbol.endswith(suffix):
            return False

        base_ccy = base_ccy_from_inst_id(symbol)
        if self.exclude_majors and base_ccy in MAJOR_AND_STABLE_COINS:
            return False

        return True

    def _volume_usdt(self, ticker: Dict[str, Any]) -> float:
        volume_ccy = safe_float(ticker.get("volCcy24h"))
        last = safe_float(ticker.get("last"))
        return max(
            volume_ccy,
            volume_ccy * last,
            safe_float(ticker.get("vol24h")) * last,
        )

    async def _scan_kline_spikes(self, tickers: List[Dict[str, Any]], now: float):
        if not self._exchange:
            return

        candidates = []
        for ticker in tickers:
            symbol = str(ticker.get("instId") or "")
            volume_usdt = self._volume_usdt(ticker)
            if volume_usdt < self.min_volume_usdt:
                continue
            candidates.append((symbol, volume_usdt))

        candidates.sort(key=lambda item: item[1], reverse=True)
        candidates = candidates[: max(1, self.kline_max_symbols_per_scan)]

        limit = max(10, min(100, self.kline_volume_lookback + 3))
        for symbol, volume_24h_usdt in candidates:
            try:
                raw = await self._exchange.get_kline(
                    symbol, self.kline_timeframe, limit=limit
                )
                signal = self._build_kline_signal(symbol, raw, volume_24h_usdt, now)
                if signal:
                    await self._maybe_alert_kline_spike(signal)
            except Exception as exc:
                logger.debug(f"5m山寨币异动扫描失败: {symbol} {exc}")
            await asyncio.sleep(0.03)

    def _build_kline_signal(
        self,
        symbol: str,
        raw_klines: List[Dict[str, Any]],
        volume_24h_usdt: float,
        now: float,
    ) -> Optional[Dict[str, Any]]:
        confirmed = [
            item for item in raw_klines if str(item.get("confirm", "1")) == "1"
        ]
        if len(confirmed) < self.kline_volume_lookback + 2:
            return None

        candles = sorted(confirmed, key=lambda item: int(item["ts"]))
        latest = candles[-1]
        previous = candles[-2]
        lookback = candles[-self.kline_volume_lookback - 1 : -1]

        latest_close = safe_float(latest.get("c"))
        previous_close = safe_float(previous.get("c"))
        if latest_close <= 0 or previous_close <= 0:
            return None

        change_pct = (latest_close - previous_close) / previous_close * 100
        latest_volume_usdt = self._kline_quote_volume(latest)
        avg_volume_usdt = sum(
            self._kline_quote_volume(item) for item in lookback
        ) / len(lookback)
        if avg_volume_usdt <= 0:
            return None

        volume_multiple = latest_volume_usdt / avg_volume_usdt
        if (
            change_pct < self.kline_change_threshold_pct
            or volume_multiple < self.kline_volume_spike_multiple
            or latest_volume_usdt < self.kline_min_volume_usdt
        ):
            return None

        return {
            "type": "kline_volume_spike",
            "symbol": symbol,
            "timeframe": self.kline_timeframe,
            "timestamp": int(latest["ts"]),
            "time": datetime.fromtimestamp(int(latest["ts"]) / 1000).strftime(
                "%Y-%m-%d %H:%M"
            ),
            "open": safe_float(latest.get("o")),
            "high": safe_float(latest.get("h")),
            "low": safe_float(latest.get("l")),
            "close": latest_close,
            "previous_close": previous_close,
            "change_pct": change_pct,
            "latest_volume_usdt": latest_volume_usdt,
            "avg_volume_usdt": avg_volume_usdt,
            "volume_multiple": volume_multiple,
            "volume_24h_usdt": volume_24h_usdt,
            "detected_at": now,
        }

    @staticmethod
    def _kline_quote_volume(kline: Dict[str, Any]) -> float:
        quote_volume = safe_float(kline.get("volCcyQuote"))
        if quote_volume > 0:
            return quote_volume

        close = safe_float(kline.get("c"))
        volume_ccy = safe_float(kline.get("volCcy"))
        if close > 0 and volume_ccy > 0:
            return close * volume_ccy
        return 0.0

    def _find_baseline(
        self,
        history: Deque[tuple[float, float]],
        now: float,
        window_seconds: int,
    ) -> Optional[tuple[float, float]]:
        target_ts = now - window_seconds
        baseline = None
        for item in history:
            if item[0] <= target_ts:
                baseline = item
            else:
                break
        return baseline

    async def _maybe_alert(
        self,
        symbol: str,
        last: float,
        baseline_price: float,
        change_pct: float,
        volume_usdt: float,
        now: float,
        window_seconds: int,
        threshold_pct: float,
    ):
        alert_key = f"{symbol}:{window_seconds}"
        last_alert_at = self._last_alert_at.get(alert_key, 0)
        if now - last_alert_at < self.cooldown_seconds:
            return

        self._last_alert_at[alert_key] = now
        self._seen_symbols.add(symbol)

        window_label = (
            "1分钟" if window_seconds == 60 else f"{round(window_seconds / 60)}分钟"
        )
        title = f"山寨币{window_label}急涨: {symbol}"
        content = f"{symbol} 约{window_label}上涨 {change_pct:.2f}%"
        data = {
            "交易对": symbol,
            f"{window_label}前价格": f"{baseline_price:.8g}",
            "当前价格": f"{last:.8g}",
            f"{window_label}涨幅": f"{change_pct:.2f}%",
            "24h成交额估算": f"{volume_usdt:,.0f} USDT",
            "阈值": f"{threshold_pct:.2f}%",
            "冷却": f"{self.cooldown_seconds}秒",
        }

        sent = await notification_service.send_bark_notification(
            title=title,
            message=content,
            level=NotificationLevel.WARNING,
            data=data,
        )
        if sent:
            logger.warning(
                f"山寨币急涨Bark提醒已发送: {symbol} {window_label} {change_pct:.2f}%"
            )

    async def _maybe_alert_kline_spike(self, signal: Dict[str, Any]):
        symbol = signal["symbol"]
        timestamp = signal["timestamp"]
        alert_key = f"{symbol}:{self.kline_timeframe}:{timestamp}"
        last_alert_at = self._last_kline_alert_at.get(symbol, 0)
        now = float(signal["detected_at"])
        if now - last_alert_at < self.cooldown_seconds:
            return

        self._last_kline_alert_at[symbol] = now
        self._recent_signals.appendleft(signal)
        self._seen_symbols.add(symbol)

        title = f"山寨币5m量价异动: {symbol}"
        content = (
            f"{symbol} {signal['time']} {self.kline_timeframe}涨 "
            f"{signal['change_pct']:.2f}%，成交量放大 {signal['volume_multiple']:.1f}x"
        )
        data = {
            "交易对": symbol,
            "周期": self.kline_timeframe,
            "K线时间": signal["time"],
            "前收": f"{signal['previous_close']:.8g}",
            "收盘": f"{signal['close']:.8g}",
            "涨幅": f"{signal['change_pct']:.2f}%",
            "本根成交额": f"{signal['latest_volume_usdt']:,.0f} USDT",
            f"过去{self.kline_volume_lookback}根均额": f"{signal['avg_volume_usdt']:,.0f} USDT",
            "放大倍数": f"{signal['volume_multiple']:.2f}x",
            "24h成交额估算": f"{signal['volume_24h_usdt']:,.0f} USDT",
        }

        sent = await notification_service.send_bark_notification(
            title=title,
            message=content,
            level=NotificationLevel.WARNING,
            data=data,
        )
        if sent:
            logger.warning(
                f"山寨币5m量价异动Bark提醒已发送: {symbol} "
                f"{signal['change_pct']:.2f}% volume={signal['volume_multiple']:.2f}x"
            )

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": bool(self._task and not self._task.done()),
            "inst_type": self.inst_type,
            "quote_ccy": self.quote_ccy,
            "ticker_windows": self.windows,
            "interval_seconds": self.interval_seconds,
            "cooldown_seconds": self.cooldown_seconds,
            "min_volume_usdt": self.min_volume_usdt,
            "exclude_majors": self.exclude_majors,
            "kline_monitor_enabled": self.kline_monitor_enabled,
            "kline_timeframe": self.kline_timeframe,
            "kline_scan_interval_seconds": self.kline_scan_interval_seconds,
            "kline_change_threshold_pct": self.kline_change_threshold_pct,
            "kline_volume_spike_multiple": self.kline_volume_spike_multiple,
            "kline_volume_lookback": self.kline_volume_lookback,
            "kline_min_volume_usdt": self.kline_min_volume_usdt,
            "kline_max_symbols_per_scan": self.kline_max_symbols_per_scan,
            "seen_symbol_count": len(self._seen_symbols),
            "recent_signals": list(self._recent_signals),
        }


altcoin_momentum_monitor = AltcoinMomentumMonitor()
