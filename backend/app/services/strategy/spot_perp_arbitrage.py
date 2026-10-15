"""
Conservative OKX spot-perp basis arbitrage strategy.

First version:
- Open only the cash-and-carry leg: buy spot + short USDT perpetual.
- Use top-of-book prices from ticker REST calls.
- Keep one paired position at a time.
- Compensate immediately if only one leg is accepted.

This is intentionally not a millisecond HFT engine yet. It gives the system a
real arbitrage execution path that can be upgraded to WebSocket market data.
"""

from __future__ import annotations

import asyncio
import math
import time
from decimal import Decimal
from typing import Dict, Optional

from loguru import logger

from app.services.strategy.base import StrategyBase


class SpotPerpArbitrageStrategy(StrategyBase):
    """Buy spot and short perp when the perp premium is large enough."""

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
        self.perp_symbol = str(
            p.get("perp_symbol") or self._infer_perp_symbol(symbol)
        ).upper()
        self.spot_symbol = str(
            p.get("spot_symbol") or self._infer_spot_symbol(symbol)
        ).upper()
        self.margin_mode = str(p.get("margin_mode", "isolated")).lower()
        self.leverage = int(p.get("leverage", 1))

        self.target_notional_usd = float(p.get("target_notional_usd", 100))
        self.max_notional_usd = float(
            p.get("max_notional_usd", self.target_notional_usd)
        )
        self.open_edge_threshold = float(p.get("open_edge_threshold", 0.003))
        self.close_edge_threshold = float(p.get("close_edge_threshold", 0.0008))
        self.min_net_edge = float(p.get("min_net_edge", 0.0015))
        self.fee_buffer = float(p.get("fee_buffer", 0.0012))
        self.slippage_buffer = float(p.get("slippage_buffer", 0.0008))
        self.poll_interval = float(p.get("poll_interval", 1.0))
        self.max_leg_wait_seconds = float(p.get("max_leg_wait_seconds", 2.0))
        self.close_on_stop = bool(p.get("close_on_stop", False))

        self._spot_lot_sz = Decimal("0.00000001")
        self._spot_min_sz = Decimal("0.00000001")
        self._perp_lot_sz = Decimal("1")
        self._perp_min_sz = Decimal("1")
        self._perp_ct_val = Decimal("1")
        self._use_pos_side = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._busy = False

        self._in_position = False
        self._spot_qty = Decimal("0")
        self._perp_qty = Decimal("0")
        self._entry_edge = 0.0
        self._last_edge = 0.0
        self._last_net_edge = 0.0
        self._last_open_time = 0.0
        self._last_prices: Dict = {}

        self.realized_pnl = 0.0
        self.total_trades = 0
        self.win_rate = 0.0

    @staticmethod
    def _infer_spot_symbol(symbol: str) -> str:
        value = symbol.upper()
        if value.endswith("-SWAP"):
            return value.removesuffix("-SWAP")
        return value

    @staticmethod
    def _infer_perp_symbol(symbol: str) -> str:
        value = symbol.upper()
        if value.endswith("-SWAP"):
            return value
        return f"{value}-SWAP"

    async def start(self):
        self.is_running = True
        await self._init_instruments()
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(
            f"[{self.strategy_id}] spot-perp arbitrage started: "
            f"spot={self.spot_symbol}, perp={self.perp_symbol}, "
            f"open_edge={self.open_edge_threshold:.4%}, close_edge={self.close_edge_threshold:.4%}"
        )

    async def stop(self, cancel_orders: bool = True, close_position: bool = True):
        self.is_running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        if close_position and self.close_on_stop and self._in_position:
            await self._close_pair("stop")
        logger.info(f"[{self.strategy_id}] spot-perp arbitrage stopped")

    async def on_tick(self, ticker: Dict):
        return None

    async def on_kline(self, kline: Dict):
        return None

    async def on_order_update(self, order: Dict):
        logger.debug(f"[{self.strategy_id}] order update: {order}")

    async def _init_instruments(self):
        spot = await self.exchange.get_instrument(self.spot_symbol)
        perp = await self.exchange.get_instrument(self.perp_symbol)

        self._spot_lot_sz = Decimal(str(spot.get("lotSz") or self._spot_lot_sz))
        self._spot_min_sz = Decimal(str(spot.get("minSz") or self._spot_min_sz))
        self._perp_lot_sz = Decimal(str(perp.get("lotSz") or self._perp_lot_sz))
        self._perp_min_sz = Decimal(str(perp.get("minSz") or self._perp_min_sz))
        self._perp_ct_val = Decimal(str(perp.get("ctVal") or self._perp_ct_val))

        try:
            config = await self.exchange.get_account_config()
            if config.get("posMode") != "long_short_mode":
                await self.exchange.set_position_mode("long_short_mode")
                self._use_pos_side = True
            else:
                self._use_pos_side = True
        except Exception as exc:
            self._use_pos_side = False
            logger.warning(f"[{self.strategy_id}] keep current position mode: {exc}")

        try:
            kwargs = {
                "lever": str(self.leverage),
                "mgn_mode": self.margin_mode,
                "inst_id": self.perp_symbol,
            }
            if self._use_pos_side:
                kwargs["pos_side"] = "short"
            await self.exchange.set_leverage(**kwargs)
        except Exception as exc:
            logger.warning(f"[{self.strategy_id}] set leverage failed, continue: {exc}")

    async def _monitor_loop(self):
        while self.is_running:
            try:
                if not self._busy:
                    await self._evaluate_once()
                await asyncio.sleep(max(self.poll_interval, 0.2))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"[{self.strategy_id}] arbitrage monitor error: {exc}")
                await asyncio.sleep(max(self.poll_interval, 1.0))

    async def _evaluate_once(self):
        spot_ticker, perp_ticker = await asyncio.gather(
            self.exchange.get_ticker(self.spot_symbol),
            self.exchange.get_ticker(self.perp_symbol),
        )
        spot_ask = self._price(spot_ticker, "askPx")
        spot_bid = self._price(spot_ticker, "bidPx")
        perp_bid = self._price(perp_ticker, "bidPx")
        perp_ask = self._price(perp_ticker, "askPx")
        if min(spot_ask, spot_bid, perp_bid, perp_ask) <= 0:
            return

        open_edge = (perp_bid - spot_ask) / spot_ask
        close_edge = (perp_ask - spot_bid) / spot_bid
        net_open_edge = open_edge - self.fee_buffer - self.slippage_buffer

        self._last_edge = open_edge
        self._last_net_edge = net_open_edge
        self._last_prices = {
            "spot_bid": spot_bid,
            "spot_ask": spot_ask,
            "perp_bid": perp_bid,
            "perp_ask": perp_ask,
            "open_edge": open_edge,
            "close_edge": close_edge,
            "net_open_edge": net_open_edge,
            "ts": time.time(),
        }

        if not self._in_position:
            if (
                open_edge >= self.open_edge_threshold
                and net_open_edge >= self.min_net_edge
            ):
                await self._open_pair(spot_ask, perp_bid, open_edge, net_open_edge)
            return

        if close_edge <= self.close_edge_threshold:
            await self._close_pair("edge_mean_reversion")

    @staticmethod
    def _price(ticker: Dict, key: str) -> float:
        try:
            return float(ticker.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    def _floor_to_step(self, value: Decimal, step: Decimal) -> Decimal:
        if step <= 0:
            return value
        steps = math.floor(value / step)
        return Decimal(steps) * step

    def _plain(self, value: Decimal) -> str:
        return format(value.normalize(), "f")

    def _calc_sizes(
        self, spot_price: float, perp_price: float
    ) -> tuple[Decimal, Decimal]:
        notional = Decimal(str(min(self.target_notional_usd, self.max_notional_usd)))
        spot_qty = self._floor_to_step(
            notional / Decimal(str(spot_price)), self._spot_lot_sz
        )
        if spot_qty < self._spot_min_sz:
            return Decimal("0"), Decimal("0")

        perp_contracts = self._floor_to_step(
            (spot_qty * Decimal(str(perp_price)))
            / (self._perp_ct_val * Decimal(str(perp_price))),
            self._perp_lot_sz,
        )
        if perp_contracts < self._perp_min_sz:
            return Decimal("0"), Decimal("0")

        hedged_spot_qty = self._floor_to_step(
            perp_contracts * self._perp_ct_val, self._spot_lot_sz
        )
        if hedged_spot_qty < self._spot_min_sz:
            return Decimal("0"), Decimal("0")
        return hedged_spot_qty, perp_contracts

    async def _open_pair(
        self, spot_ask: float, perp_bid: float, edge: float, net_edge: float
    ):
        if self._busy:
            return
        self._busy = True
        spot_qty, perp_qty = self._calc_sizes(spot_ask, perp_bid)
        if spot_qty <= 0 or perp_qty <= 0:
            logger.warning(f"[{self.strategy_id}] arbitrage size too small, skip")
            self._busy = False
            return

        logger.info(
            f"[{self.strategy_id}] opening arbitrage pair: spot_qty={spot_qty}, "
            f"perp_qty={perp_qty}, edge={edge:.4%}, net={net_edge:.4%}"
        )
        spot_order_task = self.exchange.create_order(
            symbol=self.spot_symbol,
            side="buy",
            order_type="market",
            amount=spot_qty,
            td_mode="cash",
            tgt_ccy="base_ccy",
        )
        perp_order_task = self.exchange.create_order(
            symbol=self.perp_symbol,
            side="sell",
            order_type="market",
            amount=perp_qty,
            td_mode=self.margin_mode,
            pos_side="short" if self._use_pos_side else None,
        )
        spot_result, perp_result = await asyncio.gather(
            spot_order_task,
            perp_order_task,
            return_exceptions=True,
        )

        spot_ok = not isinstance(spot_result, Exception)
        perp_ok = not isinstance(perp_result, Exception)
        if spot_ok and perp_ok:
            self._in_position = True
            self._spot_qty = spot_qty
            self._perp_qty = perp_qty
            self._entry_edge = edge
            self._last_open_time = time.time()
            logger.success(
                f"[{self.strategy_id}] arbitrage pair opened: "
                f"spot_order={spot_result.get('ordId')}, perp_order={perp_result.get('ordId')}"
            )
        else:
            logger.error(
                f"[{self.strategy_id}] paired open failed: "
                f"spot_ok={spot_ok}, perp_ok={perp_ok}, spot={spot_result}, perp={perp_result}"
            )
            await self._compensate_open_failure(spot_ok, perp_ok, spot_qty, perp_qty)
        self._busy = False

    async def _compensate_open_failure(
        self,
        spot_ok: bool,
        perp_ok: bool,
        spot_qty: Decimal,
        perp_qty: Decimal,
    ):
        tasks = []
        if spot_ok and not perp_ok:
            tasks.append(
                self.exchange.create_order(
                    symbol=self.spot_symbol,
                    side="sell",
                    order_type="market",
                    amount=spot_qty,
                    td_mode="cash",
                )
            )
        if perp_ok and not spot_ok:
            tasks.append(
                self.exchange.create_order(
                    symbol=self.perp_symbol,
                    side="buy",
                    order_type="market",
                    amount=perp_qty,
                    td_mode=self.margin_mode,
                    pos_side="short" if self._use_pos_side else None,
                    reduce_only=not self._use_pos_side,
                )
            )
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            logger.warning(f"[{self.strategy_id}] compensation results: {results}")
            compensation_failed = any(
                isinstance(result, Exception) for result in results
            )
            if compensation_failed:
                self._in_position = True
                self._spot_qty = spot_qty if spot_ok and not perp_ok else Decimal("0")
                self._perp_qty = perp_qty if perp_ok and not spot_ok else Decimal("0")
                self._entry_edge = self._last_edge
                logger.error(
                    f"[{self.strategy_id}] compensation incomplete, remaining exposure: "
                    f"spot_qty={self._spot_qty}, perp_qty={self._perp_qty}"
                )

    async def _close_pair(self, reason: str):
        if self._busy or not self._in_position:
            return
        self._busy = True
        logger.info(f"[{self.strategy_id}] closing arbitrage pair: reason={reason}")
        spot_task = None
        perp_task = None
        if self._spot_qty > 0:
            spot_task = self.exchange.create_order(
                symbol=self.spot_symbol,
                side="sell",
                order_type="market",
                amount=self._spot_qty,
                td_mode="cash",
            )
        if self._perp_qty > 0:
            perp_task = self.exchange.create_order(
                symbol=self.perp_symbol,
                side="buy",
                order_type="market",
                amount=self._perp_qty,
                td_mode=self.margin_mode,
                pos_side="short" if self._use_pos_side else None,
                reduce_only=not self._use_pos_side,
            )

        tasks = [task for task in (spot_task, perp_task) if task is not None]
        if not tasks:
            self._in_position = False
            self._busy = False
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)
        if spot_task is not None and perp_task is not None:
            spot_result, perp_result = results
        elif spot_task is not None:
            spot_result, perp_result = results[0], None
        else:
            spot_result, perp_result = None, results[0]

        if spot_task is not None and not isinstance(spot_result, Exception):
            self._spot_qty = Decimal("0")
        if perp_task is not None and not isinstance(perp_result, Exception):
            self._perp_qty = Decimal("0")

        if isinstance(spot_result, Exception) or isinstance(perp_result, Exception):
            logger.error(
                f"[{self.strategy_id}] paired close incomplete: spot={spot_result}, perp={perp_result}, "
                f"remaining spot_qty={self._spot_qty}, perp_qty={self._perp_qty}"
            )
            self._in_position = self._spot_qty > 0 or self._perp_qty > 0
            self._busy = False
            return

        approx_pnl = self._entry_edge - self._last_prices.get(
            "close_edge", self._entry_edge
        )
        approx_pnl -= self.fee_buffer + self.slippage_buffer
        approx_usd = (
            approx_pnl * float(self._spot_qty) * self._last_prices.get("spot_bid", 0)
        )
        self.realized_pnl += approx_usd
        self.total_trades += 1
        self.record_trade_result(approx_usd)

        self._in_position = False
        self._spot_qty = Decimal("0")
        self._perp_qty = Decimal("0")
        self._entry_edge = 0.0
        logger.success(
            f"[{self.strategy_id}] arbitrage pair closed, approx_pnl={approx_usd:.4f} USDT"
        )
        self._busy = False

    def get_signal_status(self) -> Dict:
        return {
            "strategy": "spot_perp_arbitrage",
            "spot_symbol": self.spot_symbol,
            "perp_symbol": self.perp_symbol,
            "in_position": self._in_position,
            "entry_edge": round(self._entry_edge, 6),
            "open_edge": round(self._last_edge, 6),
            "net_open_edge": round(self._last_net_edge, 6),
            "open_threshold": self.open_edge_threshold,
            "close_threshold": self.close_edge_threshold,
            "prices": self._last_prices,
        }

    async def calculate_pnl(self) -> Dict:
        return {
            "total_pnl": round(self.realized_pnl, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "unrealized_pnl": 0,
            "total_fee": 0,
            "pnl_rate": 0,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "in_position": self._in_position,
            "position_side": "spot_long_perp_short" if self._in_position else "",
            "entry_price": 0,
        }

    def get_stats(self) -> Dict:
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "spot_symbol": self.spot_symbol,
            "perp_symbol": self.perp_symbol,
            "is_running": self.is_running,
            "in_position": self._in_position,
            "spot_qty": float(self._spot_qty),
            "perp_qty": float(self._perp_qty),
            "entry_edge": self._entry_edge,
            "open_edge": self._last_edge,
            "net_open_edge": self._last_net_edge,
            "realized_pnl": self.realized_pnl,
            "total_trades": self.total_trades,
        }
