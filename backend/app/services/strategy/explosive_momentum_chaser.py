"""Explosive intraday momentum chaser for liquid OKX USDT swaps.

High-risk strategy. It looks for one-hour volume-backed breakouts in liquid
altcoin swaps, only opens longs when the BTC short-term filter is positive, and
exits by fixed take-profit, hard stop, or fixed holding time.
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from loguru import logger

from app.core.database import SessionLocal
from app.models.strategy import StrategyEvent
from app.services.notification.notification_service import notification_service
from app.services.strategy.base import StrategyBase


BENCHMARK_SYMBOLS = {"BTC-USDT-SWAP", "ETH-USDT-SWAP"}
SUPPORTED_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1H", "4H"}
TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1H": 60 * 60,
    "4H": 4 * 60 * 60,
}
EXCLUDED_SYMBOLS = {
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
}


@dataclass
class ExplosivePosition:
    symbol: str
    qty: float
    entry_price: float
    stop_px: float
    take_profit_px: Optional[float]
    open_time: float
    ct_val: float
    current_price: float
    highest_price: float
    entry_fee: float = 0.0


class ExplosiveMomentumChaserStrategy(StrategyBase):
    """One-hour breakout continuation strategy with BTC filter and hard stop."""

    def __init__(
        self,
        strategy_id: int,
        exchange,
        symbol: str,
        parameters: Dict,
        user_id: int = 1,
    ):
        super().__init__(strategy_id, exchange, symbol, parameters, user_id)
        p = parameters or {}
        self._self_driven = True

        self.timeframe = str(p.get("timeframe", "1H"))
        if self.timeframe not in SUPPORTED_TIMEFRAMES:
            self.timeframe = "1H"
        self.timeframe_seconds = TIMEFRAME_SECONDS[self.timeframe]
        self.lookback_1h_bars = max(1, math.ceil(60 * 60 / self.timeframe_seconds))
        self.lookback_4h_bars = max(1, math.ceil(4 * 60 * 60 / self.timeframe_seconds))
        self.lookback_24h_bars = max(
            1, math.ceil(24 * 60 * 60 / self.timeframe_seconds)
        )

        self.rank_feature = str(p.get("rank_feature", "ret_1h"))
        if self.rank_feature not in {"ret_1h", "ret_4h", "continuation"}:
            self.rank_feature = "ret_1h"
        self.hold_hours = max(1, min(int(p.get("hold_hours", 8)), 12))
        self.top_n = max(1, min(int(p.get("top_n", 1)), 3))
        self.min_signal = float(p.get("min_signal", 0.04))
        self.min_gap = float(p.get("min_gap", 0.01))
        self.min_vol_ratio = float(p.get("min_vol_ratio", 3.0))
        self.max_signal = self._optional_positive_float(p.get("max_signal"))
        self.max_ret_4h = self._optional_positive_float(p.get("max_ret_4h"))
        self.max_ret_24h = self._optional_positive_float(p.get("max_ret_24h"))
        self.max_vol_ratio = self._optional_positive_float(p.get("max_vol_ratio"))
        self.min_pre_3h = float(p.get("min_pre_3h", -1.0))
        self.max_upper_wick = self._optional_positive_float(p.get("max_upper_wick"))
        self.min_close_location = max(
            0.0, min(float(p.get("min_close_location", 0.0)), 1.0)
        )
        self.min_btc_4h = self._optional_float(p.get("min_btc_4h"))
        self.max_btc_4h = self._optional_positive_float(p.get("max_btc_4h"))
        self.min_btc_24h = self._optional_float(p.get("min_btc_24h"))
        raw_max_market_pumps = p.get("max_market_pumps")
        self.max_market_pumps = (
            max(1, int(raw_max_market_pumps))
            if raw_max_market_pumps not in (None, "", 0, "0")
            else None
        )
        self.stop_loss_pct = float(p.get("stop_loss_pct", 0.08))
        raw_take_profit_pct = p.get("take_profit_pct", 0.10)
        try:
            self.take_profit_pct = (
                float(raw_take_profit_pct)
                if raw_take_profit_pct not in (None, "", 0, "0")
                else None
            )
        except (TypeError, ValueError):
            self.take_profit_pct = None
        if self.take_profit_pct is not None and self.take_profit_pct <= 0:
            self.take_profit_pct = None
        self.market_filter = str(p.get("market_filter", "btc_4h_positive"))
        self.universe_size = max(10, min(int(p.get("universe_size", 80)), 200))

        self.max_leverage = max(1, min(int(p.get("max_leverage", 3)), 10))
        self.margin_mode = str(p.get("margin_mode", "isolated")).lower()
        if self.margin_mode not in {"isolated", "cross"}:
            self.margin_mode = "isolated"
        self.max_position_usd = float(p.get("max_position_usd", 300))
        self.max_total_position_usd = float(
            p.get("max_total_position_usd", self.max_position_usd)
        )
        self.balance_usage_fraction = max(
            0.05, min(float(p.get("balance_usage_fraction", 0.75)), 1.0)
        )
        self.max_open_positions = max(1, min(int(p.get("max_open_positions", 1)), 2))
        self.loop_interval_seconds = max(15, int(p.get("loop_interval_seconds", 60)))
        self.cooldown_seconds = max(0, int(p.get("cooldown_seconds", 2 * 3600)))
        self.observe_first_scan = bool(p.get("observe_first_scan", True))
        self.use_attached_tp_sl = bool(p.get("use_attached_tp_sl", True))
        self.use_volume_profile_filter = bool(p.get("use_volume_profile_filter", False))
        self.volume_profile_hours = max(
            4, min(int(p.get("volume_profile_hours", 8)), 12)
        )
        self.volume_profile_bins = max(
            20, min(int(p.get("volume_profile_bins", 48)), 100)
        )
        self.volume_profile_level = str(p.get("volume_profile_level", "poc")).lower()
        if self.volume_profile_level not in {"poc", "vah"}:
            self.volume_profile_level = "poc"
        self.max_high_pullback_pct = max(
            0.0,
            min(float(p.get("max_high_pullback_pct", 0.02)), 0.20),
        )

        self.positions: Dict[str, ExplosivePosition] = {}
        self._instrument_cache: Dict[str, Dict[str, float]] = {}
        self._crypto_swap_symbols: Optional[set[str]] = None
        self._last_trade_at: Dict[str, float] = {}
        self._accounted_close_order_ids: Dict[str, set[str]] = {}
        # Drive scans from the exchange's latest confirmed candle rather than
        # the server wall clock. OKX can mark a just-closed candle as confirmed
        # a few seconds after the boundary; a wall-clock bucket would otherwise
        # mark the hour as scanned and silently skip that candle.
        self._last_scan_candle_ts: Optional[int] = None
        self._last_rejections: List[Dict] = []
        self._last_selection_reason: Optional[Dict] = None
        self._last_scan_snapshot: Dict = {}
        self._last_market_snapshot: Dict = {}
        self._has_completed_first_scan = False
        self._runner_task: Optional[asyncio.Task] = None
        self._signal_status: Dict = {}
        self._unrealized_pnl = 0.0
        self.realized_pnl = 0.0
        self.total_trades = 0
        self._win_trades = 0
        self.win_rate = 0.0

    async def start(self):
        # Dynamic-universe positions are not stored in the single-symbol columns
        # on Strategy. Rebuild them from persisted open/close events and the
        # exchange before scanning, otherwise every backend restart can open an
        # additional position on top of the existing one.
        self._accounted_close_order_ids = self._persisted_close_order_ids()
        await self._restore_exchange_positions()
        self.is_running = True
        self._runner_task = asyncio.create_task(self._run_loop())
        take_profit_label = (
            f"{self.take_profit_pct:.2%}" if self.take_profit_pct is not None else "off"
        )
        logger.info(
            f"策略 {self.strategy_id} 爆量急拉追涨已启动: signal={self.min_signal:.2%}, "
            f"timeframe={self.timeframe}, hold={self.hold_hours}h, "
            f"stop={self.stop_loss_pct:.2%}, take_profit={take_profit_label}, "
            f"leverage={self.max_leverage}x, volume_profile="
            f"{'on' if self.use_volume_profile_filter else 'off'}"
        )

    def _persisted_open_symbols(self) -> set[str]:
        db = SessionLocal()
        try:
            events = (
                db.query(StrategyEvent)
                .filter(
                    StrategyEvent.strategy_id == self.strategy_id,
                    StrategyEvent.event_type.in_(
                        [
                            "open_position",
                            "close_position",
                            "external_close_unresolved",
                        ]
                    ),
                )
                .order_by(StrategyEvent.created_at.asc(), StrategyEvent.id.asc())
                .all()
            )
            active: set[str] = set()
            for event in events:
                data = event.data if isinstance(event.data, dict) else {}
                symbol = str(data.get("symbol") or "")
                if not symbol and event.message:
                    first_word = str(event.message).split(maxsplit=1)[0]
                    if first_word.endswith("-USDT-SWAP"):
                        symbol = first_word
                if not symbol:
                    continue
                if event.event_type == "open_position":
                    active.add(symbol)
                else:
                    active.discard(symbol)
            return active
        finally:
            db.close()

    def _persisted_close_order_ids(self) -> Dict[str, set[str]]:
        db = SessionLocal()
        try:
            events = (
                db.query(StrategyEvent)
                .filter(
                    StrategyEvent.strategy_id == self.strategy_id,
                    StrategyEvent.event_type.in_(["partial_close", "close_position"]),
                )
                .all()
            )
            result: Dict[str, set[str]] = {}
            for event in events:
                data = event.data if isinstance(event.data, dict) else {}
                symbol = str(data.get("symbol") or "")
                if not symbol:
                    continue
                raw_ids = data.get("order_ids") or data.get("order_id") or []
                if isinstance(raw_ids, str):
                    raw_ids = raw_ids.split(",")
                for order_id in raw_ids:
                    normalized = str(order_id or "").strip()
                    if normalized:
                        result.setdefault(symbol, set()).add(normalized)
            return result
        finally:
            db.close()

    def _persisted_open_fees(self) -> Dict[str, float]:
        db = SessionLocal()
        try:
            events = (
                db.query(StrategyEvent)
                .filter(
                    StrategyEvent.strategy_id == self.strategy_id,
                    StrategyEvent.event_type.in_(
                        [
                            "open_position",
                            "close_position",
                            "external_close_unresolved",
                        ]
                    ),
                )
                .order_by(StrategyEvent.created_at.asc(), StrategyEvent.id.asc())
                .all()
            )
            fees: Dict[str, float] = {}
            for event in events:
                data = event.data if isinstance(event.data, dict) else {}
                symbol = str(data.get("symbol") or "")
                if not symbol:
                    continue
                if event.event_type == "open_position":
                    fees[symbol] = fees.get(symbol, 0.0) + self._safe_float(
                        data.get("entry_fee")
                    )
                else:
                    fees.pop(symbol, None)
            return fees
        finally:
            db.close()

    async def _restore_exchange_positions(self):
        expected_symbols = self._persisted_open_symbols()
        if not expected_symbols:
            return
        persisted_open_fees = self._persisted_open_fees()

        try:
            exchange_positions = await self.exchange.get_positions(inst_type="SWAP")
        except Exception as exc:
            raise RuntimeError(
                f"恢复交易所持仓失败，已阻止策略启动以避免重复开仓: {exc}"
            ) from exc

        restored = {}
        exchange_unrealized = 0.0
        for item in exchange_positions:
            symbol = str(item.get("instId") or "")
            if symbol not in expected_symbols:
                continue
            raw_qty = self._safe_float(item.get("pos"))
            pos_side = str(item.get("posSide") or "net").lower()
            is_long = (pos_side == "long" and raw_qty > 0) or (
                pos_side == "net" and raw_qty > 0
            )
            if not is_long:
                logger.warning(
                    f"[{symbol}] 历史策略记录为多仓，但交易所方向不匹配，跳过接管"
                )
                continue

            info = await self._instrument(symbol)
            entry = self._safe_float(item.get("avgPx"))
            current = self._safe_float(item.get("markPx") or item.get("last")) or entry
            opened_ms = self._safe_float(item.get("cTime"))
            stop_px = entry * (1 - self.stop_loss_pct)
            take_profit_px = (
                entry * (1 + self.take_profit_pct)
                if self.take_profit_pct is not None
                else None
            )
            restored[symbol] = ExplosivePosition(
                symbol=symbol,
                qty=abs(raw_qty),
                entry_price=entry,
                stop_px=stop_px,
                take_profit_px=take_profit_px,
                open_time=opened_ms / 1000 if opened_ms > 0 else time.time(),
                ct_val=info["ct_val"],
                current_price=current,
                highest_price=max(entry, current),
                entry_fee=persisted_open_fees.get(symbol, 0.0),
            )
            exchange_unrealized += self._safe_float(item.get("upl"))

        self.positions = restored
        self._unrealized_pnl = exchange_unrealized
        if restored:
            details = ", ".join(
                f"{symbol} {pos.qty:g}张" for symbol, pos in restored.items()
            )
            logger.warning(f"策略 {self.strategy_id} 已从交易所恢复真实持仓: {details}")
            self._log_event(
                "position_restored",
                "已恢复交易所真实持仓",
                details,
                level="warning",
                data={
                    "positions": {
                        symbol: {
                            "qty": pos.qty,
                            "entry": pos.entry_price,
                            "stop": pos.stop_px,
                            "take_profit": pos.take_profit_px,
                        }
                        for symbol, pos in restored.items()
                    }
                },
            )

    async def stop(self, cancel_orders: bool = True, close_position: bool = False):
        self.is_running = False
        if self._runner_task:
            self._runner_task.cancel()
            try:
                await self._runner_task
            except asyncio.CancelledError:
                pass
            self._runner_task = None
        if close_position:
            for symbol in list(self.positions.keys()):
                await self._close_position(symbol, "manual_stop")
        logger.info(f"策略 {self.strategy_id} 爆量急拉追涨已停止")

    async def on_tick(self, ticker: Dict):
        return None

    async def on_kline(self, kline: Dict):
        return None

    async def on_order_update(self, order: Dict):
        logger.debug(f"[ExplosiveMomentumChaser] 订单更新: {order}")

    async def _run_loop(self):
        while self.is_running:
            try:
                await self._scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error_at = time.time()
                self.last_error_message = str(exc)
                logger.error(f"爆量急拉追涨循环异常: {exc}")
                self._log_event(
                    "runtime_error", "爆量急拉追涨循环异常", str(exc), level="error"
                )
                await self._notify_android_push(
                    "爆量急拉策略异常",
                    str(exc),
                    level="error",
                    data={"错误": str(exc)[:300]},
                )
            await asyncio.sleep(self.loop_interval_seconds)

    async def _scan_once(self):
        await self._manage_positions()

        scan_candle_ts = await self._latest_confirmed_candle_ts()
        if scan_candle_ts is None:
            self._publish_status(f"等待{self.timeframe} K线确认", candidates=[])
            return
        if scan_candle_ts == self._last_scan_candle_ts:
            self._publish_status(f"等待下一根{self.timeframe} K线", candidates=[])
            return

        if len(self.positions) >= self.max_open_positions:
            self._last_scan_candle_ts = scan_candle_ts
            self._publish_status("已有持仓，等待退出", candidates=[])
            return

        tickers = await self.exchange.get_tickers("SWAP")
        if not await self._market_filter_ok():
            self._last_scan_candle_ts = scan_candle_ts
            self._publish_status(
                f"BTC/ETH市场过滤未通过，跳过本根{self.timeframe} K线", candidates=[]
            )
            return

        candidates = await self._rank_candidates(tickers)
        self._last_scan_candle_ts = scan_candle_ts
        self._publish_status(
            "已扫描爆量急拉候选",
            candidates=candidates[:5],
            record_scan=True,
        )
        if self.observe_first_scan and not self._has_completed_first_scan:
            self._has_completed_first_scan = True
            self._log_event(
                "observe",
                "爆量急拉首轮观察",
                "首轮扫描只观察，不开仓",
                data={"candidates": candidates[:5]},
            )
            if candidates:
                await self._notify_signal(candidates[0], observe=True)
            return
        self._has_completed_first_scan = True
        if candidates:
            await self._notify_signal(candidates[0], observe=False)

        for item in candidates[: self.top_n]:
            if len(self.positions) >= self.max_open_positions:
                break
            symbol = item["symbol"]
            if symbol in self.positions:
                continue
            if (
                time.time() - self._last_trade_at.get(symbol, 0.0)
                < self.cooldown_seconds
            ):
                continue
            await self._open_position(symbol, item)

    async def _market_filter_ok(self) -> bool:
        has_btc_range_filter = any(
            value is not None
            for value in (self.min_btc_4h, self.max_btc_4h, self.min_btc_24h)
        )
        if self.market_filter == "none" and not has_btc_range_filter:
            return True
        limit = min(300, max(32, self.lookback_24h_bars + 2))
        btc = await self._load_candles("BTC-USDT-SWAP", limit=limit)
        if len(btc) <= self.lookback_24h_bars:
            return False
        btc_1h = self._window_return(btc, self.lookback_1h_bars)
        btc_4h = self._window_return(btc, self.lookback_4h_bars)
        btc_24h = self._window_return(btc, self.lookback_24h_bars)
        self._last_market_snapshot = {
            "btc_1h": btc_1h,
            "btc_4h": btc_4h,
            "btc_24h": btc_24h,
        }
        if self.min_btc_4h is not None and btc_4h < self.min_btc_4h:
            return False
        if self.max_btc_4h is not None and btc_4h > self.max_btc_4h:
            return False
        if self.min_btc_24h is not None and btc_24h < self.min_btc_24h:
            return False
        if self.market_filter == "none":
            return True
        if self.market_filter == "btc_4h_positive":
            return btc_4h > 0
        eth = await self._load_candles("ETH-USDT-SWAP", limit=limit)
        if len(eth) <= self.lookback_4h_bars:
            return False
        eth_1h = self._window_return(eth, self.lookback_1h_bars)
        eth_4h = self._window_return(eth, self.lookback_4h_bars)
        if self.market_filter == "btc_eth_1h_positive":
            return btc_1h > 0 and eth_1h > 0
        if self.market_filter == "btc_eth_4h_positive":
            return btc_4h > 0 and eth_4h > 0
        return False

    async def _latest_confirmed_candle_ts(self) -> Optional[int]:
        """Return the exchange-confirmed candle used to key one scan cycle."""
        candles = await self._load_candles("BTC-USDT-SWAP", limit=2)
        if not candles:
            return None
        return int(candles[-1]["ts"])

    async def _rank_candidates(self, tickers: List[Dict]) -> List[Dict]:
        crypto_symbols = await self._load_crypto_swap_symbols()
        liquid = []
        for ticker in tickers:
            symbol = str(ticker.get("instId") or "")
            if not symbol.endswith("-USDT-SWAP") or symbol in EXCLUDED_SYMBOLS:
                continue
            if crypto_symbols is not None and symbol not in crypto_symbols:
                continue
            last = self._safe_float(ticker.get("last"))
            liquidity_score = self._ticker_liquidity_score(ticker, last)
            if last > 0 and liquidity_score > 0:
                liquid.append((liquidity_score, symbol, last))
        liquid.sort(reverse=True)

        candidates = []
        rejections = []
        market_pump_count = 0
        self._last_selection_reason = None
        for liquidity_rank, (_, symbol, last) in enumerate(
            liquid[: self.universe_size], start=1
        ):
            try:
                candles = await self._load_candles(
                    symbol, limit=min(300, max(32, self.lookback_4h_bars + 25))
                )
                signal, rejection = self._evaluate_candidate(symbol, candles, last)
                if signal:
                    signal["liquidity_rank"] = liquidity_rank
                    candidates.append(signal)
                    market_pump_count += int(bool(signal.get("base_market_pump")))
                elif rejection:
                    rejection["liquidity_rank"] = liquidity_rank
                    rejections.append(rejection)
                    market_pump_count += int(bool(rejection.get("base_market_pump")))
            except Exception as exc:
                logger.debug(f"[{symbol}] 爆量候选计算失败: {exc}")
                rejections.append(
                    {
                        "symbol": symbol,
                        "liquidity_rank": liquidity_rank,
                        "reason": "calculation_error",
                        "reason_text": "候选计算失败",
                    }
                )
            await asyncio.sleep(0.02)

        self._last_rejections = sorted(
            rejections,
            key=lambda item: item.get("ret_1h", float("-inf")),
            reverse=True,
        )
        self._last_market_snapshot["market_pump_count"] = market_pump_count
        if (
            self.max_market_pumps is not None
            and market_pump_count > self.max_market_pumps
        ):
            self._last_selection_reason = {
                "reason": "market_too_crowded",
                "reason_text": "同时爆量币数量超过上限",
                "actual": market_pump_count,
                "maximum": self.max_market_pumps,
            }
            return []
        by_ret_1h = sorted(candidates, key=lambda item: item["ret_1h"], reverse=True)
        if not candidates:
            self._last_selection_reason = {
                "reason": "no_qualified_candidate",
                "reason_text": "没有币种通过基础信号过滤",
            }
            return []
        if (
            len(by_ret_1h) > 1
            and by_ret_1h[0]["ret_1h"] - by_ret_1h[1]["ret_1h"] < self.min_gap
        ):
            self._last_selection_reason = {
                "reason": "insufficient_lead_gap",
                "reason_text": "第一候选与第二候选的涨幅差不足",
                "leader": by_ret_1h[0]["symbol"],
                "runner_up": by_ret_1h[1]["symbol"],
                "actual_gap": by_ret_1h[0]["ret_1h"] - by_ret_1h[1]["ret_1h"],
                "required_gap": self.min_gap,
            }
            return []
        candidates.sort(key=lambda item: item["score"], reverse=True)
        if self.use_volume_profile_filter:
            accepted, profile_data = await self._volume_profile_acceptance(
                candidates[0]
            )
            candidates[0]["volume_profile"] = profile_data
            if not accepted:
                reason = str(profile_data.get("reason") or "成交量分布过滤未通过")
                self._log_event(
                    "skip",
                    "爆量急拉成交量分布过滤",
                    f"{candidates[0]['symbol']} 跳过开仓: {reason}",
                    level="info",
                    data=candidates[0],
                )
                self._last_selection_reason = {
                    "reason": "volume_profile_rejected",
                    "reason_text": reason,
                    "symbol": candidates[0]["symbol"],
                }
                return []
        return candidates

    async def _load_crypto_swap_symbols(self) -> Optional[set[str]]:
        """Exclude tokenized equities/ETFs that OKX also labels as USDT swaps."""
        if self._crypto_swap_symbols is not None:
            return self._crypto_swap_symbols
        try:
            instruments = await self.exchange.get_instruments(inst_type="SWAP")
            self._crypto_swap_symbols = {
                str(item.get("instId") or "")
                for item in instruments
                if str(item.get("instId") or "").endswith("-USDT-SWAP")
                and str(item.get("instCategory") or "1") == "1"
                and str(item.get("state") or "live") == "live"
            }
            return self._crypto_swap_symbols
        except Exception as exc:
            logger.warning(f"加载加密永续产品分类失败，本轮仅按交易对后缀过滤: {exc}")
            return None

    def _ticker_liquidity_score(self, ticker: Dict, last: float) -> float:
        """Estimate 24h USDT notional liquidity for comparable swap sorting."""
        for key in ("volCcyQuote24h", "volQuote24h", "volUsd24h"):
            value = self._safe_float(ticker.get(key))
            if value > 0:
                return value

        volume_ccy = self._safe_float(ticker.get("volCcy24h"))
        if volume_ccy > 0 and last > 0:
            return volume_ccy * last

        volume_contracts = self._safe_float(ticker.get("vol24h"))
        ct_val = self._safe_float(ticker.get("ctVal"))
        if volume_contracts > 0 and ct_val > 0 and last > 0:
            return volume_contracts * ct_val * last

        return volume_contracts

    def _candidate_signal(
        self, symbol: str, candles: List[Dict], last: float
    ) -> Optional[Dict]:
        signal, _ = self._evaluate_candidate(symbol, candles, last)
        return signal

    def _evaluate_candidate(
        self,
        symbol: str,
        candles: List[Dict],
        last: float,
    ) -> tuple[Optional[Dict], Optional[Dict]]:
        min_len = max(25, self.lookback_4h_bars + 1)
        if len(candles) < min_len:
            return None, {
                "symbol": symbol,
                "reason": "insufficient_history",
                "reason_text": "已确认K线数量不足",
                "bars": len(candles),
                "required_bars": min_len,
            }
        c = candles[-1]
        ret_1h = self._window_return(candles, self.lookback_1h_bars)
        ret_4h = self._window_return(candles, self.lookback_4h_bars)
        volumes = [item["volume"] for item in candles[-25:-1]]
        avg_volume = sum(volumes) / len(volumes) if volumes else 0.0
        vol_ratio = c["volume"] / avg_volume if avg_volume > 0 else 0.0
        ret_24h = self._window_return(candles, min(24, len(candles) - 1))
        base_4h_close = candles[-self.lookback_4h_bars - 1]["close"]
        pre_signal_close = candles[-self.lookback_1h_bars - 1]["close"]
        pre_3h = pre_signal_close / base_4h_close - 1 if base_4h_close > 0 else 0.0
        upper_wick = (
            max(0.0, c["high"] - max(c["open"], c["close"])) / c["open"]
            if c["open"] > 0
            else 1.0
        )
        candle_range = c["high"] - c["low"]
        close_location = (
            (c["close"] - c["low"]) / candle_range if candle_range > 0 else 0.5
        )
        if self.rank_feature == "ret_4h":
            score = ret_4h
        elif self.rank_feature == "continuation":
            score = ret_4h - upper_wick + 0.01 * close_location
        else:
            score = ret_1h
        metrics = {
            "symbol": symbol,
            "last": last or c["close"],
            "score": score,
            "ret_1h": ret_1h,
            "ret_4h": ret_4h,
            "ret_24h": ret_24h,
            "vol_ratio": vol_ratio,
            "pre_3h": pre_3h,
            "upper_wick": upper_wick,
            "close_location": close_location,
            "base_market_pump": ret_1h >= 0.04 and vol_ratio >= 3.0,
            "candle_ts": c["ts"],
            "timeframe": self.timeframe,
        }

        def rejected(reason: str, reason_text: str, threshold: Optional[float] = None):
            result = dict(metrics)
            result.update({"reason": reason, "reason_text": reason_text})
            if threshold is not None:
                result["threshold"] = threshold
            return None, result

        if ret_1h < self.min_signal:
            return rejected(
                "below_min_signal", "涨幅未达到最低信号阈值", self.min_signal
            )
        if vol_ratio < self.min_vol_ratio:
            return rejected(
                "below_min_vol_ratio", "量比未达到最低阈值", self.min_vol_ratio
            )
        if self.max_signal is not None and ret_1h > self.max_signal:
            return rejected("above_max_signal", "涨幅超过过热上限", self.max_signal)
        if self.max_ret_4h is not None and ret_4h > self.max_ret_4h:
            return rejected(
                "above_max_ret_4h", "4小时涨幅超过过热上限", self.max_ret_4h
            )
        if self.max_ret_24h is not None and ret_24h > self.max_ret_24h:
            return rejected(
                "above_max_ret_24h", "24小时涨幅超过过热上限", self.max_ret_24h
            )
        if self.max_vol_ratio is not None and vol_ratio > self.max_vol_ratio:
            return rejected(
                "above_max_vol_ratio", "量比超过过热上限", self.max_vol_ratio
            )
        if pre_3h < self.min_pre_3h:
            return rejected("below_min_pre_3h", "信号前3小时涨幅不足", self.min_pre_3h)
        if self.max_upper_wick is not None and upper_wick > self.max_upper_wick:
            return rejected(
                "above_max_upper_wick", "上影线超过上限", self.max_upper_wick
            )
        if close_location < self.min_close_location:
            return rejected(
                "below_min_close_location", "收盘位置低于要求", self.min_close_location
            )
        return {
            **metrics,
            "signal_high": c["high"],
        }, None

    async def _volume_profile_acceptance(self, signal: Dict) -> tuple[bool, Dict]:
        symbol = str(signal["symbol"])
        try:
            rows = await self._load_profile_minute_candles(symbol)
            profile = self._build_volume_profile(rows, self.volume_profile_bins)
        except Exception as exc:
            logger.warning(f"[{symbol}] 成交量分布计算失败，拒绝本轮信号: {exc}")
            return False, {"reason": f"成交量分布计算失败: {exc}"}
        if profile is None:
            return False, {"reason": "有效1分钟数据不足"}

        current_price = self._safe_float(signal.get("last"))
        signal_high = self._safe_float(signal.get("signal_high"))
        required_price = profile[self.volume_profile_level]
        pullback = max(0.0, 1 - current_price / signal_high) if signal_high > 0 else 1.0
        accepted = (
            current_price >= required_price and pullback <= self.max_high_pullback_pct
        )
        reason = (
            "通过POC成交量分布确认"
            if accepted
            else (
                f"现价 {current_price:.8f} 低于 {self.volume_profile_level.upper()} {required_price:.8f}"
                if current_price < required_price
                else f"距1H高点回撤 {pullback:.2%} 超过 {self.max_high_pullback_pct:.2%}"
            )
        )
        return accepted, {
            **profile,
            "level": self.volume_profile_level,
            "required_price": required_price,
            "current_price": current_price,
            "pullback_from_high_pct": pullback * 100,
            "max_high_pullback_pct": self.max_high_pullback_pct * 100,
            "accepted": accepted,
            "reason": reason,
            "source": "OKX 1m typical-price volume approximation",
        }

    async def _load_profile_minute_candles(self, symbol: str) -> List[Dict]:
        needed = self.volume_profile_hours * 60
        rows: Dict[int, Dict] = {}
        cursor: Optional[str] = None
        for _ in range(max(2, math.ceil((needed + 30) / 300))):
            batch = await self.exchange.get_kline(
                symbol,
                "1m",
                limit=300,
                after=cursor,
            )
            confirmed = [item for item in batch if str(item.get("confirm", "1")) == "1"]
            if not confirmed:
                break
            for item in confirmed:
                ts = int(item["ts"])
                rows[ts] = {
                    "ts": ts,
                    "high": self._safe_float(item.get("h")),
                    "low": self._safe_float(item.get("l")),
                    "close": self._safe_float(item.get("c")),
                    "quote_volume": self._safe_float(
                        item.get("volCcyQuote") or item.get("volCcy") or item.get("vol")
                    ),
                }
            oldest = min(int(item["ts"]) for item in confirmed)
            if cursor == str(oldest) or len(rows) >= needed + 10:
                break
            cursor = str(oldest)
        ordered = sorted(rows.values(), key=lambda item: item["ts"])
        return ordered[-needed:]

    @staticmethod
    def _build_volume_profile(rows: List[Dict], bins: int = 48) -> Optional[Dict]:
        if len(rows) < 360:
            return None
        low = min(float(row["low"]) for row in rows)
        high = max(float(row["high"]) for row in rows)
        if low <= 0 or high <= low:
            return None
        width = (high - low) / bins
        volumes = [0.0] * bins
        for row in rows:
            typical = (float(row["high"]) + float(row["low"]) + float(row["close"])) / 3
            index = min(bins - 1, max(0, int((typical - low) / width)))
            volumes[index] += max(0.0, float(row.get("quote_volume") or 0.0))
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
        return {
            "low": low,
            "high": high,
            "poc": center(poc_index),
            "vah": low + (max(included) + 1) * width,
            "val": low + min(included) * width,
            "poc_position": (center(poc_index) - low) / (high - low),
            "bins": bins,
        }

    async def _open_position(self, symbol: str, signal: Dict):
        info = await self._instrument(symbol)
        price = float(signal["last"])
        stop_px = price * (1 - self.stop_loss_pct)
        take_profit_px = (
            price * (1 + self.take_profit_pct)
            if self.take_profit_pct is not None
            else None
        )
        qty = await self._calc_contract_qty(price, info)
        if qty <= 0:
            self._log_event(
                "skip",
                "爆量急拉跳过开仓",
                f"{symbol} 计算下单数量为0",
                level="warning",
                data=signal,
            )
            return

        await self._ensure_leverage(symbol)
        order = await self.exchange.create_order(
            symbol=symbol,
            side="buy",
            order_type="market",
            amount=Decimal(str(qty)),
            td_mode=self.margin_mode,
            pos_side=await self._pos_side(),
            attach_algo_ords=(
                self._attached_tp_sl(take_profit_px, stop_px)
                if self.use_attached_tp_sl
                else None
            ),
        )
        detail = await self._load_order_detail(symbol, order)
        fill_price = self._safe_float(detail.get("avgPx")) or price
        pos = ExplosivePosition(
            symbol=symbol,
            qty=qty,
            entry_price=fill_price,
            stop_px=stop_px,
            take_profit_px=take_profit_px,
            open_time=time.time(),
            ct_val=info["ct_val"],
            current_price=fill_price,
            highest_price=fill_price,
            entry_fee=self._safe_float(detail.get("fee")),
        )
        self.positions[symbol] = pos
        self._last_trade_at[symbol] = time.time()
        await self._save_symbol_order_to_db(
            symbol, detail, "buy", "market", None, Decimal(str(qty))
        )
        self._log_event(
            "open_position",
            "爆量急拉开多",
            f"{symbol} 开多 {qty} 张，入场 {fill_price:.8f}，止损 {stop_px:.8f}"
            + (f"，止盈 {take_profit_px:.8f}" if take_profit_px else ""),
            level="success",
            data={
                **signal,
                "qty": qty,
                "entry": fill_price,
                "stop": stop_px,
                "take_profit": take_profit_px,
                "take_profit_pct": self.take_profit_pct,
                "leverage": self.max_leverage,
                "native_protection": self.use_attached_tp_sl,
                "entry_fee": pos.entry_fee,
                "order_id": str(detail.get("ordId") or ""),
            },
        )
        await self._notify_android_push(
            "爆量急拉开仓",
            f"{symbol} 开多，入场 {fill_price:.8f}，止损 {stop_px:.8f}"
            + (f"，止盈 {take_profit_px:.8f}" if take_profit_px else ""),
            level="success",
            data={
                "交易对": symbol,
                "方向": "做多",
                "入场价": f"{fill_price:.8f}",
                "止损价": f"{stop_px:.8f}",
                "止盈价": f"{take_profit_px:.8f}" if take_profit_px else "-",
                "数量": f"{qty:g} 张",
                "杠杆": f"{self.max_leverage}x",
                "信号涨幅": f"{signal.get('score', 0) * 100:.2f}%",
                "放量倍数": f"{signal.get('vol_ratio', 0):.2f}x",
                "持仓上限": f"{self.hold_hours}小时",
            },
        )

    async def _manage_positions(self):
        for symbol in list(self.positions.keys()):
            pos = self.positions.get(symbol)
            if not pos:
                continue
            try:
                exchange_positions = await self.exchange.get_positions(inst_id=symbol)
                exchange_position = next(
                    (
                        item
                        for item in exchange_positions
                        if str(item.get("instId") or "") == symbol
                        and str(item.get("posSide") or "net") in {"long", "net"}
                        and self._safe_float(item.get("pos")) > 0
                    ),
                    None,
                )
                has_position = exchange_position is not None
            except Exception as exc:
                logger.warning(
                    f"[{symbol}] 获取交易所持仓失败，保留本地持仓等待下轮核对: {exc}"
                )
                continue
            if not has_position:
                await self._reconcile_exchange_close(symbol)
                continue
            # Native TP/SL or a manual trade can partially change a merged OKX
            # position. Keep the managed quantity and average price aligned with
            # the exchange so a later exit never closes only the stale subset.
            exchange_qty = abs(self._safe_float(exchange_position.get("pos")))
            if 0 < exchange_qty < pos.qty:
                await self._reconcile_partial_exchange_close(
                    symbol, pos.qty, exchange_qty
                )
            pos.qty = exchange_qty
            exchange_entry = self._safe_float(exchange_position.get("avgPx"))
            if exchange_entry > 0:
                pos.entry_price = exchange_entry
                pos.stop_px = exchange_entry * (1 - self.stop_loss_pct)
                pos.take_profit_px = (
                    exchange_entry * (1 + self.take_profit_pct)
                    if self.take_profit_pct is not None
                    else None
                )
            try:
                price = self._safe_float(
                    exchange_position.get("markPx") or exchange_position.get("last")
                )
                if price <= 0:
                    ticker = await self.exchange.get_ticker(symbol)
                    price = self._safe_float(ticker.get("last"))
            except Exception as exc:
                logger.warning(f"[{symbol}] 获取持仓行情失败: {exc}")
                continue
            if price <= 0:
                continue
            pos.current_price = price
            pos.highest_price = max(pos.highest_price, price)
            self._unrealized_pnl = sum(
                self._position_pnl(item) for item in self.positions.values()
            )
            elapsed = time.time() - pos.open_time
            if price <= pos.stop_px:
                await self._close_position(symbol, "hard_stop")
            elif pos.take_profit_px and price >= pos.take_profit_px:
                await self._close_position(symbol, "take_profit")
            elif elapsed >= self.hold_hours * 3600:
                await self._close_position(symbol, "time_exit")

    async def _close_position(self, symbol: str, reason: str):
        pos = self.positions.get(symbol)
        if not pos:
            return
        try:
            order = await self.exchange.create_order(
                symbol=symbol,
                side="sell",
                order_type="market",
                amount=Decimal(str(pos.qty)),
                td_mode=self.margin_mode,
                pos_side=await self._pos_side(),
                reduce_only=True,
            )
        except Exception as exc:
            error_msg = str(exc)
            if "51169" in error_msg or "don't have any positions" in error_msg:
                await self._reconcile_exchange_close(symbol, fallback_error=error_msg)
                return
            raise
        detail = await self._load_order_detail(symbol, order)
        exit_price = self._safe_float(detail.get("avgPx")) or pos.current_price
        gross_pnl = self._safe_float(detail.get("pnl"))
        if not detail.get("pnl"):
            gross_pnl = (exit_price - pos.entry_price) * pos.qty * pos.ct_val
        exit_fee = self._safe_float(detail.get("fee"))
        pnl = gross_pnl + pos.entry_fee + exit_fee
        await self._save_symbol_order_to_db(
            symbol, detail, "sell", "market", None, Decimal(str(pos.qty))
        )
        await self._finalize_position(
            symbol,
            reason,
            exit_price,
            pnl,
            gross_pnl=gross_pnl,
            exit_fee=exit_fee,
            order_id=str(detail.get("ordId") or ""),
        )

    async def _finalize_position(
        self,
        symbol: str,
        reason: str,
        exit_price: float,
        pnl: float,
        *,
        gross_pnl: Optional[float] = None,
        exit_fee: float = 0.0,
        order_id: str = "",
    ):
        pos = self.positions.get(symbol)
        if not pos:
            return
        for close_order_id in str(order_id or "").split(","):
            normalized = close_order_id.strip()
            if normalized:
                self._accounted_close_order_ids.setdefault(symbol, set()).add(
                    normalized
                )
        pos.current_price = exit_price
        self.realized_pnl += pnl
        self.total_trades += 1
        if pnl > 0:
            self._win_trades += 1
        self.win_rate = (
            self._win_trades / self.total_trades * 100 if self.total_trades else 0
        )
        self.record_trade_result(pnl)
        self._last_trade_at[symbol] = time.time()
        self.positions.pop(symbol, None)
        self._unrealized_pnl = sum(
            self._position_pnl(item) for item in self.positions.values()
        )
        self._log_event(
            "close_position",
            "爆量急拉平仓",
            f"{symbol} {reason} 平仓，盈亏 {pnl:.4f} USDT",
            level="success" if pnl >= 0 else "warning",
            data={
                "symbol": symbol,
                "reason": reason,
                "exit": exit_price,
                "pnl": pnl,
                "gross_pnl": gross_pnl,
                "entry_fee": pos.entry_fee,
                "exit_fee": exit_fee,
                "order_id": order_id,
            },
        )
        await self._notify_android_push(
            "爆量急拉平仓",
            f"{symbol} {self._reason_text(reason)}，盈亏 {pnl:.4f} USDT",
            level="success" if pnl >= 0 else "warning",
            data={
                "交易对": symbol,
                "原因": self._reason_text(reason),
                "入场价": f"{pos.entry_price:.8f}",
                "平仓价": f"{exit_price:.8f}",
                "最高价": f"{pos.highest_price:.8f}",
                "数量": f"{pos.qty:g} 张",
                "盈亏": f"{pnl:.4f} USDT",
                "累计交易": self.total_trades,
                "胜率": f"{self.win_rate:.2f}%",
            },
        )

    def _record_realized_adjustment(self, pnl: float) -> None:
        today = datetime.now().date()
        if today != self._daily_pnl_date:
            self._daily_pnl_date = today
            self.daily_realized_pnl = 0.0
        self.realized_pnl += pnl
        self.runtime_realized_pnl += pnl
        self.daily_realized_pnl += pnl
        self.runtime_equity_peak = max(
            self.runtime_equity_peak, self.runtime_realized_pnl
        )
        self.max_runtime_drawdown = max(
            self.max_runtime_drawdown,
            self.runtime_equity_peak - self.runtime_realized_pnl,
        )

    async def _reconcile_partial_exchange_close(
        self,
        symbol: str,
        previous_qty: float,
        remaining_qty: float,
    ) -> None:
        """Persist newly filled reductions before replacing the local merged quantity."""
        pos = self.positions.get(symbol)
        if not pos or remaining_qty >= previous_qty:
            return
        try:
            orders = await self.exchange.get_orders_history(
                inst_type="SWAP",
                inst_id=symbol,
                state="filled",
                limit=100,
            )
        except Exception as exc:
            logger.warning(f"[{symbol}] 部分平仓账单读取失败，暂不覆盖本地数量: {exc}")
            return

        opened_ms = int(pos.open_time * 1000)
        accounted = self._accounted_close_order_ids.setdefault(symbol, set())
        reductions = []
        for detail in orders:
            order_id = str(detail.get("ordId") or "").strip()
            fill_time = int(
                self._safe_float(
                    detail.get("fillTime") or detail.get("uTime") or detail.get("cTime")
                )
            )
            fill_qty = self._safe_float(
                detail.get("accFillSz") or detail.get("fillSz") or detail.get("sz")
            )
            if (
                str(detail.get("instId") or "") == symbol
                and str(detail.get("side") or "").lower() == "sell"
                and order_id
                and order_id not in accounted
                and fill_qty > 0
                and fill_time >= opened_ms
            ):
                reductions.append((fill_time, detail, fill_qty, order_id))
        reductions.sort(key=lambda item: item[0])

        missing_qty = max(0.0, previous_qty - remaining_qty)
        captured_qty = 0.0
        for _, detail, fill_qty, order_id in reductions:
            if captured_qty >= missing_qty - 1e-9:
                break
            fill_price = (
                self._safe_float(detail.get("avgPx") or detail.get("fillPx"))
                or pos.current_price
            )
            raw_pnl = detail.get("pnl")
            gross_pnl = (
                self._safe_float(raw_pnl)
                if raw_pnl not in (None, "")
                else (fill_price - pos.entry_price) * fill_qty * pos.ct_val
            )
            fee = self._safe_float(detail.get("fee"))
            pnl = gross_pnl + fee
            self._record_realized_adjustment(pnl)
            accounted.add(order_id)
            captured_qty += fill_qty
            self._log_event(
                "partial_close",
                "爆量急拉部分平仓",
                f"{symbol} 部分平仓 {fill_qty:g} 张，盈亏 {pnl:.4f} USDT",
                level="success" if pnl >= 0 else "warning",
                data={
                    "symbol": symbol,
                    "qty": fill_qty,
                    "remaining_qty": remaining_qty,
                    "exit": fill_price,
                    "pnl": pnl,
                    "gross_pnl": gross_pnl,
                    "exit_fee": fee,
                    "order_id": order_id,
                    "reason": "exchange_partial_close",
                },
            )

        if captured_qty + 1e-9 < missing_qty:
            logger.warning(
                f"[{symbol}] 交易所持仓从 {previous_qty:g} 减至 {remaining_qty:g}，"
                f"但只匹配到 {captured_qty:g} 张新平仓成交"
            )

    async def _reconcile_exchange_close(self, symbol: str, fallback_error: str = ""):
        """Import a native/manual exchange close and clear the local phantom position."""
        pos = self.positions.get(symbol)
        if not pos:
            return
        try:
            orders = await self.exchange.get_orders_history(
                inst_type="SWAP",
                inst_id=symbol,
                state="filled",
                limit=100,
            )
        except Exception as exc:
            orders = []
            fallback_error = fallback_error or str(exc)

        opened_ms = int(pos.open_time * 1000)
        close_orders = [
            item
            for item in orders
            if str(item.get("instId") or "") == symbol
            and str(item.get("side") or "").lower() == "sell"
            and self._safe_float(
                item.get("accFillSz") or item.get("fillSz") or item.get("sz")
            )
            > 0
            and int(
                self._safe_float(
                    item.get("fillTime") or item.get("uTime") or item.get("cTime")
                )
            )
            >= opened_ms
            and str(item.get("ordId") or "")
            not in self._accounted_close_order_ids.get(symbol, set())
        ]
        close_orders.sort(
            key=lambda item: self._safe_float(
                item.get("fillTime") or item.get("uTime") or item.get("cTime")
            ),
            reverse=True,
        )
        if close_orders:
            fills = []
            for detail in close_orders:
                fill_qty = self._safe_float(
                    detail.get("accFillSz") or detail.get("fillSz") or detail.get("sz")
                )
                fill_price = self._safe_float(
                    detail.get("avgPx") or detail.get("fillPx")
                )
                if fill_qty > 0 and fill_price > 0:
                    fills.append((detail, fill_qty, fill_price))
            total_fill_qty = sum(fill_qty for _, fill_qty, _ in fills)
            exit_price = (
                sum(fill_qty * fill_price for _, fill_qty, fill_price in fills)
                / total_fill_qty
                if total_fill_qty > 0
                else pos.current_price
            )
            gross_pnl = 0.0
            for detail, fill_qty, fill_price in fills:
                raw_pnl = detail.get("pnl")
                gross_pnl += (
                    self._safe_float(raw_pnl)
                    if raw_pnl not in (None, "")
                    else (fill_price - pos.entry_price) * fill_qty * pos.ct_val
                )
            exit_fee = sum(
                self._safe_float(detail.get("fee")) for detail, _, _ in fills
            )
            pnl = gross_pnl + pos.entry_fee + exit_fee
            reason = (
                "native_protection"
                if any(
                    detail.get("algoId") or detail.get("attachAlgoClOrdId")
                    for detail, _, _ in fills
                )
                else "external_close"
            )
            await self._finalize_position(
                symbol,
                reason,
                exit_price,
                pnl,
                gross_pnl=gross_pnl,
                exit_fee=exit_fee,
                order_id=",".join(
                    str(detail.get("ordId") or "") for detail, _, _ in fills
                ),
            )
            return

        self.positions.pop(symbol, None)
        self._last_trade_at[symbol] = time.time()
        self._unrealized_pnl = sum(
            self._position_pnl(item) for item in self.positions.values()
        )
        self._log_event(
            "external_close_unresolved",
            "爆量急拉外部平仓待核账",
            fallback_error or f"{symbol} 交易所已无持仓，但未找到对应成交记录",
            level="warning",
            data={"symbol": symbol},
        )
        await self._notify_android_push(
            "爆量急拉外部平仓待核账",
            f"{symbol} 已清除本地幽灵持仓，成交盈亏暂未计入",
            level="warning",
            data={"交易对": symbol, "原因": (fallback_error or "未找到成交记录")[:200]},
        )

    async def _load_candles(self, symbol: str, limit: int = 32) -> List[Dict]:
        raw = await self.exchange.get_kline(symbol, self.timeframe, limit=limit)
        candles = [
            {
                "ts": int(item["ts"]),
                "open": float(item["o"]),
                "high": float(item["h"]),
                "low": float(item["l"]),
                "close": float(item["c"]),
                "volume": float(
                    item.get("volCcyQuote")
                    or item.get("volCcy")
                    or item.get("vol")
                    or 0
                ),
            }
            for item in raw
            if str(item.get("confirm", "1")) == "1"
        ]
        return sorted(candles, key=lambda item: item["ts"])

    async def _calc_contract_qty(self, price: float, info: Dict[str, float]) -> float:
        if price <= 0:
            return 0.0
        balance = await self.exchange.get_balance()
        total_eq = self._safe_float(balance.get("totalEq"))
        details = balance.get("details", [])
        usdt = next((item for item in details if item.get("ccy") == "USDT"), {})
        available = self._safe_float(usdt.get("availBal"))
        equity = total_eq or available
        if equity <= 0 or available <= 0:
            return 0.0
        remaining_total_usd = max(
            0.0, self.max_total_position_usd - self._current_notional_usd()
        )
        if remaining_total_usd <= 0:
            return 0.0
        notional = min(
            self.max_position_usd,
            remaining_total_usd,
            available * self.balance_usage_fraction * self.max_leverage,
        )
        return self._round_qty(notional / (price * info["ct_val"]), info)

    def _current_notional_usd(self) -> float:
        return sum(
            max(pos.current_price, pos.entry_price) * pos.qty * pos.ct_val
            for pos in self.positions.values()
        )

    def _position_pnl(self, pos: ExplosivePosition) -> float:
        return (pos.current_price - pos.entry_price) * pos.qty * pos.ct_val

    async def _instrument(self, symbol: str) -> Dict[str, float]:
        if symbol in self._instrument_cache:
            return self._instrument_cache[symbol]
        raw = await self.exchange.get_instrument(symbol)
        info = {
            "ct_val": self._safe_float(raw.get("ctVal")) or 1.0,
            "lot_sz": self._safe_float(raw.get("lotSz")) or 1.0,
            "min_sz": self._safe_float(raw.get("minSz")) or 1.0,
        }
        self._instrument_cache[symbol] = info
        return info

    async def _ensure_leverage(self, symbol: str):
        try:
            await self.exchange.set_leverage(
                lever=str(self.max_leverage),
                mgn_mode=self.margin_mode,
                inst_id=symbol,
                pos_side=await self._pos_side(),
            )
        except Exception as exc:
            logger.warning(f"[{symbol}] 设置杠杆失败，继续尝试下单: {exc}")

    async def _pos_side(self) -> Optional[str]:
        try:
            config = await self.exchange.get_account_config()
            return "long" if config.get("posMode") == "long_short_mode" else "net"
        except Exception:
            return "net"

    async def _load_order_detail(self, symbol: str, order: Dict) -> Dict:
        order_id = order.get("ordId")
        if not order_id:
            return order
        try:
            await asyncio.sleep(0.8)
            return await self.exchange.get_order(symbol, order_id=order_id)
        except Exception as exc:
            logger.warning(f"[{symbol}] 查询订单详情失败，使用下单返回: {exc}")
            return order

    def _round_qty(self, qty: float, info: Dict[str, float]) -> float:
        if qty <= 0:
            return 0.0
        lot_sz = info["lot_sz"]
        min_sz = info["min_sz"]
        rounded = math.floor(qty / lot_sz) * lot_sz
        if rounded < min_sz:
            return 0.0
        return round(rounded, 8)

    @staticmethod
    def _attached_tp_sl(take_profit_px: Optional[float], stop_px: float) -> List[Dict]:
        protection = {
            "slTriggerPx": str(round(stop_px, 12)),
            "slOrdPx": "-1",
        }
        if take_profit_px is not None:
            protection.update(
                {
                    "tpTriggerPx": str(round(take_profit_px, 12)),
                    "tpOrdPx": "-1",
                }
            )
        return [protection]

    def _publish_status(
        self, message: str, candidates: List[Dict], record_scan: bool = False
    ):
        candidate_summary = [
            {
                "symbol": item["symbol"],
                "score_pct": round(item["score"] * 100, 4),
                "ret_1h_pct": round(item["ret_1h"] * 100, 4),
                "ret_4h_pct": round(item["ret_4h"] * 100, 4),
                "vol_ratio": round(item["vol_ratio"], 4),
                "liquidity_rank": item.get("liquidity_rank"),
            }
            for item in candidates
        ]
        if record_scan:
            self._last_scan_snapshot = {
                "candle_ts": self._last_scan_candle_ts,
                "candidates": candidate_summary,
                "selection_reason": self._last_selection_reason,
                "rejections": self._last_rejections,
            }
        self._signal_status = {
            "message": message,
            "strategy": "explosive_momentum_chaser",
            "timeframe": self.timeframe,
            "rank_feature": self.rank_feature,
            "min_signal": self.min_signal,
            "market_filter": self.market_filter,
            "market_snapshot": self._last_market_snapshot,
            "take_profit_pct": self.take_profit_pct,
            "volume_profile_filter": {
                "enabled": self.use_volume_profile_filter,
                "hours": self.volume_profile_hours,
                "bins": self.volume_profile_bins,
                "level": self.volume_profile_level,
                "max_high_pullback_pct": self.max_high_pullback_pct,
            },
            "open_positions": {
                symbol: pos.__dict__ for symbol, pos in self.positions.items()
            },
            "candidates": candidate_summary,
            "last_scan": self._last_scan_snapshot,
        }

    def get_signal_status(self) -> Dict:
        return self._signal_status or {"message": "等待爆量急拉扫描"}

    @staticmethod
    def _window_return(candles: List[Dict], lookback_bars: int) -> float:
        if len(candles) <= lookback_bars:
            return 0.0
        base = candles[-lookback_bars - 1]["close"]
        if base <= 0:
            return 0.0
        return candles[-1]["close"] / base - 1

    async def calculate_pnl(self) -> Dict:
        return {
            "total_pnl": self.realized_pnl + self._unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self._unrealized_pnl,
            "total_trades": self.total_trades,
            "buy_count": self.total_trades,
            "sell_count": self.total_trades,
            "win_rate": self.win_rate,
            "last_signal": self._signal_status,
            "open_positions": len(self.positions),
            "positions": {
                symbol: pos.__dict__ for symbol, pos in self.positions.items()
            },
        }

    def _log_event(
        self,
        event_type: str,
        title: str,
        message: str,
        level: str = "info",
        data: Optional[Dict] = None,
    ):
        db = SessionLocal()
        try:
            db.add(
                StrategyEvent(
                    strategy_id=self.strategy_id,
                    user_id=self.user_id,
                    event_type=event_type,
                    level=level,
                    title=title,
                    message=message,
                    data=data or {},
                    parameter_snapshot=(
                        self.parameters if isinstance(self.parameters, dict) else None
                    ),
                )
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.debug(f"爆量急拉写入事件失败: {exc}")
        finally:
            db.close()

    async def _notify_signal(self, signal: Dict, observe: bool = False):
        title = "爆量急拉候选观察" if observe else "爆量急拉候选触发"
        action = "首轮只观察，不开仓" if observe else "通过过滤，准备按规则开仓"
        await self._notify_android_push(
            title,
            f"{signal['symbol']} 近1小时涨幅 {signal.get('ret_1h', 0) * 100:.2f}%，{action}",
            level="info" if observe else "warning",
            data={
                "交易对": signal["symbol"],
                "动作": action,
                "K线周期": self.timeframe,
                "评分涨幅": f"{signal.get('score', 0) * 100:.2f}%",
                "近1小时涨幅": f"{signal.get('ret_1h', 0) * 100:.2f}%",
                "近4小时涨幅": f"{signal.get('ret_4h', 0) * 100:.2f}%",
                "放量倍数": f"{signal.get('vol_ratio', 0):.2f}x",
                "市场过滤": self.market_filter,
                "成交量分布": (
                    f"{self.volume_profile_level.upper()}确认/高点回撤≤{self.max_high_pullback_pct:.2%}"
                    if self.use_volume_profile_filter
                    else "关闭"
                ),
                "止损": f"{self.stop_loss_pct * 100:.2f}%",
                "持仓上限": f"{self.hold_hours}小时",
            },
        )

    async def _notify_android_push(
        self, title: str, message: str, level: str = "info", data: Optional[Dict] = None
    ):
        try:
            await notification_service.send_android_push_alert(
                title=title,
                message=message,
                level=level,
                data=data or {},
                category="爆量急拉追涨",
                strategy_id=self.strategy_id,
            )
        except Exception as exc:
            logger.debug(f"爆量急拉Android全能消息推送失败: {exc}")

    @staticmethod
    def _reason_text(reason: str) -> str:
        return {
            "hard_stop": "硬止损",
            "take_profit": "固定止盈",
            "time_exit": "到时平仓",
            "manual_stop": "手动停止",
            "native_protection": "交易所原生止损/止盈",
            "external_close": "交易所外部平仓",
        }.get(reason, reason)

    async def _save_symbol_order_to_db(
        self,
        symbol: str,
        order_data: Dict,
        side: str,
        order_type: str,
        price: Optional[Decimal],
        amount: Decimal,
    ):
        original_symbol = self.symbol
        self.symbol = symbol
        try:
            return await self._save_order_to_db(
                order_data, side, order_type, price, amount
            )
        finally:
            self.symbol = original_symbol

    @staticmethod
    def _optional_positive_float(value) -> Optional[float]:
        try:
            if value in (None, "", 0, "0"):
                return None
            parsed = float(value)
            return parsed if parsed > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_float(value) -> Optional[float]:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_float(value) -> float:
        try:
            if value in (None, ""):
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0
