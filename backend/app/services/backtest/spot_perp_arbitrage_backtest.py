"""
Spot-perpetual basis arbitrage backtest engine.

The engine models a conservative cash-and-carry trade:
- open: buy spot + short USDT perpetual when perp premium is high
- close: sell spot + cover perpetual when premium mean-reverts

It uses synchronized K-line close prices for both legs, so results are only a
research approximation. Live execution still depends on order book depth,
latency, fees, funding, and partial-fill handling.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from loguru import logger

from .backtest_engine import BacktestEngine, Trade


class SpotPerpArbitrageBacktestEngine(BacktestEngine):
    """Backtest a spot-long/perp-short basis strategy with paired K-lines."""

    def __init__(
        self,
        symbol: str,
        initial_capital: float,
        spot_symbol: Optional[str] = None,
        perp_symbol: Optional[str] = None,
        target_notional_usd: float = 100.0,
        max_notional_usd: Optional[float] = None,
        open_edge_threshold: float = 0.003,
        close_edge_threshold: float = 0.0008,
        min_net_edge: float = 0.0015,
        fee_rate: float = 0.0005,
        slippage_rate: float = 0.0005,
        leverage: int = 1,
        max_holding_bars: int = 0,
    ):
        super().__init__(
            symbol=symbol,
            initial_capital=initial_capital,
            fee_rate=fee_rate,
            leverage=leverage,
            enable_short=True,
        )
        self.spot_symbol = (spot_symbol or self._infer_spot_symbol(symbol)).upper()
        self.perp_symbol = (perp_symbol or self._infer_perp_symbol(symbol)).upper()
        self.target_notional_usd = target_notional_usd
        self.max_notional_usd = max_notional_usd or target_notional_usd
        self.open_edge_threshold = open_edge_threshold
        self.close_edge_threshold = close_edge_threshold
        self.min_net_edge = min_net_edge
        self.slippage_rate = slippage_rate
        self.max_holding_bars = max_holding_bars

        self._pair_klines: Dict[str, List[Dict]] = {}
        self._spot_qty = 0.0
        self._perp_qty = 0.0
        self._entry_spot = 0.0
        self._entry_perp = 0.0
        self._entry_edge = 0.0
        self._perp_margin = 0.0
        self._open_bar_index = 0

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

    @classmethod
    def from_params(
        cls, symbol: str, initial_capital: float, params: Dict
    ) -> "SpotPerpArbitrageBacktestEngine":
        return cls(
            symbol=symbol,
            initial_capital=initial_capital,
            spot_symbol=params.get("spot_symbol"),
            perp_symbol=params.get("perp_symbol"),
            target_notional_usd=float(params.get("target_notional_usd", 100)),
            max_notional_usd=float(
                params.get("max_notional_usd", params.get("target_notional_usd", 100))
            ),
            open_edge_threshold=float(params.get("open_edge_threshold", 0.003)),
            close_edge_threshold=float(params.get("close_edge_threshold", 0.0008)),
            min_net_edge=float(params.get("min_net_edge", 0.0015)),
            fee_rate=float(
                params.get("fee_rate", params.get("taker_fee_rate", 0.0005))
            ),
            slippage_rate=float(
                params.get("slippage_rate", params.get("slippage_buffer", 0.0005))
            ),
            leverage=int(params.get("leverage", 1)),
            max_holding_bars=int(params.get("max_holding_bars", 0)),
        )

    def required_symbols(self) -> List[str]:
        return [self.spot_symbol, self.perp_symbol]

    def set_pair_klines(self, pair_klines: Dict[str, List[Dict]]) -> None:
        self._pair_klines = pair_klines

    def reset(self):
        super().reset()
        self._spot_qty = 0.0
        self._perp_qty = 0.0
        self._entry_spot = 0.0
        self._entry_perp = 0.0
        self._entry_edge = 0.0
        self._perp_margin = 0.0
        self._open_bar_index = 0

    def on_kline(self, kline: Dict):
        return None

    def run(
        self, klines: List[Dict], progress_callback: Optional[Callable] = None
    ) -> Dict:
        spot_map, perp_map = self._build_aligned_maps(klines)
        timestamps = sorted(set(spot_map.keys()) & set(perp_map.keys()))
        if not timestamps:
            raise ValueError(
                f"现货 {self.spot_symbol} 和永续 {self.perp_symbol} 没有可对齐的K线数据"
            )

        logger.info(
            f"开始现货-永续套利回测: spot={self.spot_symbol}, perp={self.perp_symbol}, "
            f"aligned_klines={len(timestamps)}, initial={self.initial_capital}"
        )
        self.reset()

        total = len(timestamps)
        for i, ts in enumerate(timestamps):
            spot_k = spot_map[ts]
            perp_k = perp_map[ts]
            spot_price = float(spot_k["close"])
            perp_price = float(perp_k["close"])
            if spot_price <= 0 or perp_price <= 0:
                continue

            edge = (perp_price - spot_price) / spot_price
            net_edge = edge - (self.fee_rate * 4) - (self.slippage_rate * 4)

            if self._in_position():
                holding_bars = i - self._open_bar_index
                should_close = edge <= self.close_edge_threshold
                if self.max_holding_bars > 0 and holding_bars >= self.max_holding_bars:
                    should_close = True
                if should_close:
                    self._close_pair(ts, spot_price, perp_price)
            elif edge >= self.open_edge_threshold and net_edge >= self.min_net_edge:
                self._open_pair(ts, spot_price, perp_price, edge, i)

            self._update_pair_equity(ts, spot_price, perp_price, edge)

            if progress_callback and i % 100 == 0:
                progress_callback(i + 1, total)

        if self._in_position():
            final_ts = timestamps[-1]
            self._close_pair(
                final_ts,
                float(spot_map[final_ts]["close"]),
                float(perp_map[final_ts]["close"]),
            )
            self._update_pair_equity(
                final_ts,
                float(spot_map[final_ts]["close"]),
                float(perp_map[final_ts]["close"]),
                (
                    float(perp_map[final_ts]["close"])
                    - float(spot_map[final_ts]["close"])
                )
                / float(spot_map[final_ts]["close"]),
            )

        if progress_callback:
            progress_callback(total, total)

        final_equity = (
            self.equity_curve[-1]["equity"]
            if self.equity_curve
            else self.initial_capital
        )
        logger.info(
            f"现货-永续套利回测完成: final_equity={final_equity:.2f}, trades={len(self.trades)}"
        )
        return {
            "final_equity": final_equity,
            "total_trades": len(self.trades),
            "initial_capital": self.initial_capital,
            "liquidation_count": 0,
            "leverage": self.leverage,
        }

    def _build_aligned_maps(
        self, primary_klines: List[Dict]
    ) -> tuple[Dict[int, Dict], Dict[int, Dict]]:
        pair_klines = dict(self._pair_klines)
        pair_klines.setdefault(self.symbol.upper(), primary_klines)
        if self.spot_symbol not in pair_klines:
            raise ValueError(f"缺少现货K线数据: {self.spot_symbol}")
        if self.perp_symbol not in pair_klines:
            raise ValueError(f"缺少永续K线数据: {self.perp_symbol}")

        spot_map = {int(k["timestamp"]): k for k in pair_klines[self.spot_symbol]}
        perp_map = {int(k["timestamp"]): k for k in pair_klines[self.perp_symbol]}
        return spot_map, perp_map

    def _in_position(self) -> bool:
        return self._spot_qty > 0 and self._perp_qty > 0

    def _round_notional(self) -> float:
        return max(0.0, min(self.target_notional_usd, self.max_notional_usd))

    def _open_pair(
        self,
        timestamp: int,
        spot_price: float,
        perp_price: float,
        edge: float,
        bar_index: int,
    ) -> None:
        notional = self._round_notional()
        spot_qty = notional / spot_price
        perp_qty = spot_qty
        perp_notional = perp_qty * perp_price
        perp_margin = perp_notional / self.leverage
        fee = (notional + perp_notional) * self.fee_rate
        slippage = (notional + perp_notional) * self.slippage_rate
        required = notional + perp_margin + fee + slippage
        if required > self.capital:
            return

        capital_before = self.capital
        self.capital -= required
        self._spot_qty = spot_qty
        self._perp_qty = perp_qty
        self._entry_spot = spot_price
        self._entry_perp = perp_price
        self._entry_edge = edge
        self._perp_margin = perp_margin
        self._open_bar_index = bar_index

        self.trades.append(
            Trade(
                timestamp=timestamp,
                side="buy",
                price=spot_price,
                amount=spot_qty,
                fee=fee + slippage,
                position_before=0,
                position_after=spot_qty,
                capital_before=capital_before,
                capital_after=self.capital,
                pnl=0.0,
                pnl_percent=0.0,
                direction="spot_long_perp_short",
                leverage=self.leverage,
                margin_used=perp_margin,
            )
        )

    def _close_pair(self, timestamp: int, spot_price: float, perp_price: float) -> None:
        if not self._in_position():
            return

        spot_value = self._spot_qty * spot_price
        perp_value = self._perp_qty * perp_price
        spot_pnl = self._spot_qty * (spot_price - self._entry_spot)
        perp_pnl = self._perp_qty * (self._entry_perp - perp_price)
        fee = (spot_value + perp_value) * self.fee_rate
        slippage = (spot_value + perp_value) * self.slippage_rate
        net_pnl = spot_pnl + perp_pnl - fee - slippage
        capital_before = self.capital

        self.capital += spot_value + self._perp_margin + perp_pnl - fee - slippage
        pnl_percent = (
            net_pnl / (self._entry_spot * self._spot_qty + self._perp_margin) * 100
        )

        self.trades.append(
            Trade(
                timestamp=timestamp,
                side="sell",
                price=spot_price,
                amount=self._spot_qty,
                fee=fee + slippage,
                position_before=self._spot_qty,
                position_after=0,
                capital_before=capital_before,
                capital_after=self.capital,
                pnl=net_pnl,
                pnl_percent=pnl_percent,
                direction="spot_long_perp_short",
                leverage=self.leverage,
                margin_used=self._perp_margin,
            )
        )

        self._spot_qty = 0.0
        self._perp_qty = 0.0
        self._entry_spot = 0.0
        self._entry_perp = 0.0
        self._entry_edge = 0.0
        self._perp_margin = 0.0

    def _update_pair_equity(
        self, timestamp: int, spot_price: float, perp_price: float, edge: float
    ) -> None:
        if self._in_position():
            spot_value = self._spot_qty * spot_price
            perp_unrealized = self._perp_qty * (self._entry_perp - perp_price)
            equity = self.capital + spot_value + self._perp_margin + perp_unrealized
            unrealized = (
                self._spot_qty * (spot_price - self._entry_spot) + perp_unrealized
            )
            position_value = spot_value + self._perp_qty * perp_price
        else:
            equity = self.capital
            unrealized = 0.0
            position_value = 0.0

        self.equity_curve.append(
            {
                "timestamp": timestamp,
                "equity": equity,
                "capital": self.capital,
                "position_value": position_value,
                "unrealized_pnl": unrealized,
                "position_direction": (
                    "spot_long_perp_short" if self._in_position() else "flat"
                ),
                "leverage": self.leverage,
                "edge": edge,
                "entry_edge": self._entry_edge,
            }
        )
