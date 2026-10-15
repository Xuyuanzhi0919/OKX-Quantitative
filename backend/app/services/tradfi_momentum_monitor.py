"""OKX TradFi 产品短线双向异动监控（只读，不下单）。"""
import asyncio
import time
from collections import Counter, defaultdict, deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

from loguru import logger

from app.core.config import settings
from app.services.exchange.okx import OKXExchange
from app.services.notification.notification_service import NotificationLevel, notification_service


CATEGORY_NAMES = {
    "3": "股票代币",
    "4": "贵金属",
    "5": "商品",
    "6": "外汇",
    "7": "债券",
}

DEFAULT_WINDOWS = [
    {
        "window_seconds": 300,
        "threshold_pct_by_category": {
            "3": 1.5, "4": 0.4, "5": 0.6, "6": 0.2, "7": 0.3,
        },
    },
    {
        "window_seconds": 900,
        "threshold_pct_by_category": {
            "3": 3.0, "4": 0.8, "5": 1.2, "6": 0.4, "7": 0.6,
        },
    },
]

DEFAULT_MIN_VOLUME_USDT = {
    "3": 100000, "4": 500000, "5": 200000, "6": 200000, "7": 100000,
}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class TradFiMomentumMonitor:
    """按资产类别阈值扫描 TradFi SWAP 行情，只推送告警。"""

    def __init__(self):
        self.enabled = False
        self.inst_type = "SWAP"
        self.interval_seconds = 30
        self.instrument_refresh_seconds = 3600
        self.cooldown_seconds = 1800
        self.windows = [dict(item) for item in DEFAULT_WINDOWS]
        self.min_volume_usdt_by_category = dict(DEFAULT_MIN_VOLUME_USDT)
        self._task: Optional[asyncio.Task] = None
        self._exchange: Optional[OKXExchange] = None
        self._instruments: Dict[str, str] = {}
        self._price_history: Dict[str, Deque[tuple[float, float]]] = defaultdict(deque)
        self._last_alert_at: Dict[str, float] = {}
        self._recent_signals: Deque[Dict[str, Any]] = deque(maxlen=100)
        self._last_instrument_refresh_at = 0.0
        self._last_scan_at = 0.0
        self._last_error: Optional[str] = None

    def configure(self, config: Dict[str, Any]):
        self.enabled = bool(config.get("enabled", False))
        self.inst_type = str(config.get("inst_type", self.inst_type)).upper()
        self.interval_seconds = max(10, int(config.get("interval_seconds", self.interval_seconds)))
        self.instrument_refresh_seconds = max(
            300, int(config.get("instrument_refresh_seconds", self.instrument_refresh_seconds))
        )
        self.cooldown_seconds = max(60, int(config.get("cooldown_seconds", self.cooldown_seconds)))

        configured_windows = config.get("windows")
        if isinstance(configured_windows, list) and configured_windows:
            parsed = []
            for item in configured_windows:
                if not isinstance(item, dict):
                    continue
                seconds = int(item.get("window_seconds", 0))
                thresholds = item.get("threshold_pct_by_category", {})
                thresholds = {
                    str(key): float(value)
                    for key, value in thresholds.items()
                    if str(key) in CATEGORY_NAMES and safe_float(value) > 0
                }
                if seconds > 0 and thresholds:
                    parsed.append({
                        "window_seconds": seconds,
                        "threshold_pct_by_category": thresholds,
                    })
            if parsed:
                self.windows = parsed

        configured_volume = config.get("min_volume_usdt_by_category", {})
        if isinstance(configured_volume, dict):
            for category, value in configured_volume.items():
                if str(category) in CATEGORY_NAMES and safe_float(value) >= 0:
                    self.min_volume_usdt_by_category[str(category)] = float(value)

    async def start(self):
        if not self.enabled:
            logger.info("TradFi 异动监控未启用")
            return
        bark = notification_service.channels.get("bark")
        if not bark or not bark.is_enabled():
            logger.warning("Bark 渠道未启用，TradFi 异动监控仍将运行但只记录信号")
        if self._task and not self._task.done():
            return

        self._exchange = OKXExchange(
            api_key="",
            secret_key="",
            passphrase="",
            simulated=False,
            proxy=settings.OKX_PROXY,
        )
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("TradFi 双向异动监控已启动（只读）")

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
        logger.info("TradFi 异动监控已停止")

    async def _monitor_loop(self):
        while True:
            try:
                await self._scan_once()
                self._last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                logger.error(f"TradFi 异动监控出错: {exc}")
            await asyncio.sleep(self.interval_seconds)

    async def _refresh_instruments(self, now: float):
        if not self._exchange:
            return
        instruments = await self._exchange.get_instruments(inst_type=self.inst_type)
        selected: Dict[str, str] = {}
        for item in instruments:
            category = str(item.get("instCategory") or "")
            inst_id = str(item.get("instId") or "")
            state = str(item.get("state") or "live").lower()
            if category in CATEGORY_NAMES and inst_id and state == "live":
                selected[inst_id] = category
        self._instruments = selected
        self._last_instrument_refresh_at = now
        counts = Counter(selected.values())
        summary = ", ".join(f"{CATEGORY_NAMES[key]}={counts.get(key, 0)}" for key in CATEGORY_NAMES)
        logger.info(f"TradFi 产品清单已刷新: total={len(selected)}, {summary}")

    async def _scan_once(self):
        if not self._exchange:
            return
        now = time.time()
        if (
            not self._instruments
            or now - self._last_instrument_refresh_at >= self.instrument_refresh_seconds
        ):
            await self._refresh_instruments(now)

        tickers = await self._exchange.get_tickers(self.inst_type)
        self._last_scan_at = now
        max_window = max(item["window_seconds"] for item in self.windows)
        for ticker in tickers:
            symbol = str(ticker.get("instId") or "")
            category = self._instruments.get(symbol)
            if not category:
                continue
            last = safe_float(ticker.get("last"))
            if last <= 0:
                continue
            volume_usdt = self._volume_usdt(ticker)
            if volume_usdt < self.min_volume_usdt_by_category.get(category, 0):
                continue

            history = self._price_history[symbol]
            history.append((now, last))
            while history and now - history[0][0] > max_window * 2:
                history.popleft()

            for window in self.windows:
                threshold = window["threshold_pct_by_category"].get(category)
                if not threshold:
                    continue
                window_seconds = window["window_seconds"]
                baseline = self._find_baseline(history, now, window_seconds)
                if not baseline:
                    continue
                baseline_ts, baseline_price = baseline
                if baseline_price <= 0 or now - baseline_ts < window_seconds * 0.8:
                    continue
                change_pct = (last - baseline_price) / baseline_price * 100
                if abs(change_pct) >= threshold:
                    await self._maybe_alert(
                        symbol, category, last, baseline_price, change_pct,
                        volume_usdt, now, window_seconds, threshold,
                    )

    @staticmethod
    def _find_baseline(
        history: Deque[tuple[float, float]], now: float, window_seconds: int
    ) -> Optional[tuple[float, float]]:
        target = now - window_seconds
        eligible = [point for point in history if point[0] <= target]
        return eligible[-1] if eligible else None

    @staticmethod
    def _volume_usdt(ticker: Dict[str, Any]) -> float:
        direct = max(
            safe_float(ticker.get("volCcyQuote24h")),
            safe_float(ticker.get("volQuote24h")),
            safe_float(ticker.get("volUsd24h")),
        )
        last = safe_float(ticker.get("last"))
        return max(direct, safe_float(ticker.get("volCcy24h")) * last, safe_float(ticker.get("vol24h")) * last)

    async def _maybe_alert(
        self, symbol: str, category: str, last: float, baseline_price: float,
        change_pct: float, volume_usdt: float, now: float,
        window_seconds: int, threshold: float,
    ):
        direction = "上涨" if change_pct > 0 else "下跌"
        alert_key = f"{symbol}:{window_seconds}:{direction}"
        if now - self._last_alert_at.get(alert_key, 0) < self.cooldown_seconds:
            return
        self._last_alert_at[alert_key] = now
        window_label = f"{round(window_seconds / 60)}分钟"
        signal = {
            "symbol": symbol,
            "category": CATEGORY_NAMES[category],
            "direction": direction,
            "window_seconds": window_seconds,
            "change_pct": round(change_pct, 4),
            "price": last,
            "detected_at": datetime.now().isoformat(),
        }
        self._recent_signals.appendleft(signal)
        await notification_service.send_bark_notification(
            title=f"{CATEGORY_NAMES[category]}{window_label}{direction}: {symbol}",
            message=f"{symbol} 约{window_label}{direction} {abs(change_pct):.2f}%",
            level=NotificationLevel.WARNING,
            data={
                "资产类别": CATEGORY_NAMES[category],
                "交易对": symbol,
                "方向": direction,
                "观察窗口": window_label,
                "窗口前价格": f"{baseline_price:.8g}",
                "当前价格": f"{last:.8g}",
                "涨跌幅": f"{change_pct:+.2f}%",
                "24h成交额估算": f"{volume_usdt:,.0f} USDT",
                "触发阈值": f"{threshold:.2f}%",
                "性质": "只读预警，不会自动下单",
            },
        )

    def status(self) -> Dict[str, Any]:
        counts = Counter(self._instruments.values())
        return {
            "enabled": self.enabled,
            "running": bool(self._task and not self._task.done()),
            "read_only": True,
            "instrument_count": len(self._instruments),
            "category_counts": {CATEGORY_NAMES[key]: counts.get(key, 0) for key in CATEGORY_NAMES},
            "interval_seconds": self.interval_seconds,
            "instrument_refresh_seconds": self.instrument_refresh_seconds,
            "cooldown_seconds": self.cooldown_seconds,
            "windows": self.windows,
            "min_volume_usdt_by_category": self.min_volume_usdt_by_category,
            "last_scan_at": datetime.fromtimestamp(self._last_scan_at).isoformat() if self._last_scan_at else None,
            "last_error": self._last_error,
            "recent_signals": list(self._recent_signals),
        }


tradfi_momentum_monitor = TradFiMomentumMonitor()
