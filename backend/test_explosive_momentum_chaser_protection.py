import time

import pytest

from app.services.strategy.explosive_momentum_chaser import (
    ExplosiveMomentumChaserStrategy,
    ExplosivePosition,
)


class FakeExchange:
    async def get_positions(self, **kwargs):
        return []

    async def get_orders_history(self, **kwargs):
        return [{
            "instId": "RE-USDT-SWAP",
            "side": "sell",
            "fillSz": "166",
            "avgPx": "0.5534059638554218",
            "pnl": "-78.5341",
            "fee": "-0.45932695",
            "algoId": "3773830726844858368",
            "ordId": "3773890462720794624",
            "fillTime": str(int(time.time() * 1000)),
        }]


class FakeMergedPositionExchange:
    async def get_positions(self, **kwargs):
        return [{
            "instId": "ESP-USDT-SWAP",
            "posSide": "long",
            "pos": "72",
            "avgPx": "0.0827",
            "markPx": "0.08049",
            "upl": "-15.91",
            "uplRatio": "-0.0802",
            "notionalUsd": "578.7",
            "lever": "3",
            "cTime": str(int((time.time() - 120) * 1000)),
        }]


class FakePartialCloseExchange:
    async def get_positions(self, **kwargs):
        return [{
            "instId": "ESP-USDT-SWAP",
            "posSide": "long",
            "pos": "17",
            "avgPx": "0.0821",
            "markPx": "0.081",
        }]

    async def get_orders_history(self, **kwargs):
        return [{
            "instId": "ESP-USDT-SWAP",
            "side": "sell",
            "fillSz": "3",
            "accFillSz": "55",
            "avgPx": "0.07639",
            "pnl": "-35.72",
            "fee": "-0.15",
            "ordId": "partial-stop-55",
            "fillTime": str(int(time.time() * 1000)),
        }]


class FakeConfirmedCandleExchange:
    def __init__(self):
        self.confirmed_ts = 1_000

    async def get_kline(self, symbol, timeframe, limit=2):
        return [{
            "ts": str(self.confirmed_ts),
            "o": "1",
            "h": "1",
            "l": "1",
            "c": "1",
            "volCcyQuote": "1",
            "confirm": "1",
        }]

    async def get_tickers(self, inst_type):
        return []


class FakeSizingExchange:
    async def get_balance(self):
        return {"totalEq": "700", "details": [{"ccy": "USDT", "availBal": "700"}]}


@pytest.mark.asyncio
async def test_native_close_reconciliation_clears_phantom_pnl_and_records_fees():
    strategy = ExplosiveMomentumChaserStrategy(
        strategy_id=17,
        exchange=FakeExchange(),
        symbol="BTC-USDT-SWAP",
        parameters={},
    )
    strategy.positions["RE-USDT-SWAP"] = ExplosivePosition(
        symbol="RE-USDT-SWAP",
        qty=166,
        entry_price=0.600715662650603,
        stop_px=0.5526584096385546,
        take_profit_px=0.6607872289156632,
        open_time=time.time() - 3600,
        ct_val=1,
        current_price=0.552,
        highest_price=0.61,
        entry_fee=-0.498594,
    )
    strategy._unrealized_pnl = -80.0214
    strategy._log_event = lambda *args, **kwargs: None

    async def no_notification(*args, **kwargs):
        return None

    strategy._notify_android_push = no_notification

    await strategy._manage_positions()

    assert strategy.positions == {}
    assert strategy._unrealized_pnl == 0
    assert strategy.total_trades == 1
    assert strategy.win_rate == 0
    assert strategy.realized_pnl == pytest.approx(-79.49202095)


def test_attached_protection_supports_stop_only_and_stop_take_profit():
    assert ExplosiveMomentumChaserStrategy._attached_tp_sl(None, 0.55) == [{
        "slTriggerPx": "0.55",
        "slOrdPx": "-1",
    }]
    assert ExplosiveMomentumChaserStrategy._attached_tp_sl(0.66, 0.55) == [{
        "slTriggerPx": "0.55",
        "slOrdPx": "-1",
        "tpTriggerPx": "0.66",
        "tpOrdPx": "-1",
    }]


@pytest.mark.asyncio
async def test_restart_restores_full_merged_exchange_position():
    strategy = ExplosiveMomentumChaserStrategy(
        strategy_id=1,
        exchange=FakeMergedPositionExchange(),
        symbol="BTC-USDT-SWAP",
        parameters={"stop_loss_pct": 0.08, "take_profit_pct": 0.10},
    )
    strategy._persisted_open_symbols = lambda: {"ESP-USDT-SWAP"}

    async def instrument(symbol):
        return {"ct_val": 100.0, "lot_sz": 1.0, "min_sz": 1.0}

    strategy._instrument = instrument
    strategy._log_event = lambda *args, **kwargs: None

    await strategy._restore_exchange_positions()

    position = strategy.positions["ESP-USDT-SWAP"]
    assert position.qty == 72
    assert position.entry_price == pytest.approx(0.0827)
    assert position.current_price == pytest.approx(0.08049)
    assert position.stop_px == pytest.approx(0.076084)
    assert strategy._unrealized_pnl == pytest.approx(-15.91)


@pytest.mark.asyncio
async def test_position_management_reconciles_partial_or_added_contracts():
    strategy = ExplosiveMomentumChaserStrategy(
        strategy_id=1,
        exchange=FakeMergedPositionExchange(),
        symbol="BTC-USDT-SWAP",
        parameters={"hold_hours": 8},
    )
    strategy.positions["ESP-USDT-SWAP"] = ExplosivePosition(
        symbol="ESP-USDT-SWAP",
        qty=4,
        entry_price=0.08106,
        stop_px=0.073,
        take_profit_px=0.09,
        open_time=time.time(),
        ct_val=100,
        current_price=0.08106,
        highest_price=0.08106,
    )

    await strategy._manage_positions()

    assert strategy.positions["ESP-USDT-SWAP"].qty == 72
    assert strategy.positions["ESP-USDT-SWAP"].entry_price == pytest.approx(0.0827)


@pytest.mark.asyncio
async def test_partial_exchange_close_is_persisted_once_before_quantity_sync():
    strategy = ExplosiveMomentumChaserStrategy(
        strategy_id=1,
        exchange=FakePartialCloseExchange(),
        symbol="BTC-USDT-SWAP",
        parameters={"hold_hours": 8},
    )
    strategy.positions["ESP-USDT-SWAP"] = ExplosivePosition(
        symbol="ESP-USDT-SWAP",
        qty=72,
        entry_price=0.0827,
        stop_px=0.074,
        take_profit_px=0.09,
        open_time=time.time() - 60,
        ct_val=100,
        current_price=0.082,
        highest_price=0.083,
    )
    events = []
    strategy._log_event = lambda *args, **kwargs: events.append((args, kwargs))

    await strategy._manage_positions()
    await strategy._manage_positions()

    assert strategy.positions["ESP-USDT-SWAP"].qty == 17
    assert strategy.realized_pnl == pytest.approx(-35.87)
    assert strategy.daily_realized_pnl == pytest.approx(-35.87)
    assert len(events) == 1
    assert events[0][0][0] == "partial_close"
    assert events[0][1]["data"]["order_id"] == "partial-stop-55"


def test_runtime_volume_profile_finds_dominant_high_price_node():
    rows = []
    for index in range(480):
        price = 108.0 if index < 360 else 101.0
        rows.append({
            "ts": index * 60_000,
            "high": price + 0.1,
            "low": price - 0.1,
            "close": price,
            "quote_volume": 10_000 if index < 360 else 100,
        })

    profile = ExplosiveMomentumChaserStrategy._build_volume_profile(rows, bins=40)

    assert profile is not None
    assert profile["poc"] == pytest.approx(108.0, abs=0.2)
    assert profile["poc_position"] > 0.60
    assert profile["val"] <= profile["poc"] <= profile["vah"]


@pytest.mark.asyncio
async def test_scan_retries_until_exchange_confirms_a_new_candle():
    exchange = FakeConfirmedCandleExchange()
    strategy = ExplosiveMomentumChaserStrategy(
        strategy_id=1,
        exchange=exchange,
        symbol="BTC-USDT-SWAP",
        parameters={"market_filter": "none"},
    )
    scans = []

    async def no_positions():
        return None

    async def rank_candidates(tickers):
        scans.append(exchange.confirmed_ts)
        strategy._last_rejections = []
        strategy._last_selection_reason = None
        return []

    strategy._manage_positions = no_positions
    strategy._rank_candidates = rank_candidates

    await strategy._scan_once()
    await strategy._scan_once()
    exchange.confirmed_ts = 2_000
    await strategy._scan_once()

    assert scans == [1_000, 2_000]
    assert strategy._last_scan_candle_ts == 2_000


def test_candidate_rejection_reports_exact_overheat_rule():
    strategy = ExplosiveMomentumChaserStrategy(
        strategy_id=1,
        exchange=FakeExchange(),
        symbol="BTC-USDT-SWAP",
        parameters={
            "min_signal": 0.04,
            "max_signal": 0.10,
            "min_vol_ratio": 3.0,
            "max_ret_4h": 0.15,
        },
    )
    candles = []
    for index in range(25):
        close = 1.0 if index < 24 else 1.14
        candles.append({
            "ts": index * 3_600_000,
            "open": 1.0,
            "high": close,
            "low": 1.0,
            "close": close,
            "volume": 100.0 if index < 24 else 1_000.0,
        })

    signal, rejection = strategy._evaluate_candidate("AEON-USDT-SWAP", candles, 1.14)

    assert signal is None
    assert rejection["reason"] == "above_max_signal"
    assert rejection["ret_1h"] == pytest.approx(0.14)
    assert rejection["vol_ratio"] == pytest.approx(10.0)


def test_candidate_quality_filters_match_research_features():
    strategy = ExplosiveMomentumChaserStrategy(
        strategy_id=1,
        exchange=FakeExchange(),
        symbol="BTC-USDT-SWAP",
        parameters={
            "rank_feature": "continuation",
            "min_signal": 0.04,
            "min_vol_ratio": 3.0,
            "min_pre_3h": 0.0,
            "max_upper_wick": 0.04,
            "min_close_location": 0.70,
        },
    )
    candles = []
    for index in range(24):
        close = 1.0 + index * 0.001
        candles.append({
            "ts": index * 3_600_000,
            "open": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "close": close,
            "volume": 100.0,
        })
    candles.append({
        "ts": 24 * 3_600_000,
        "open": 1.023,
        "high": 1.075,
        "low": 1.020,
        "close": 1.070,
        "volume": 500.0,
    })

    signal, rejection = strategy._evaluate_candidate("TEST-USDT-SWAP", candles, 1.070)

    assert rejection is None
    assert signal["ret_1h"] > 0.04
    assert signal["pre_3h"] >= 0
    assert signal["upper_wick"] < 0.04
    assert signal["close_location"] > 0.70
    assert signal["score"] == pytest.approx(
        signal["ret_4h"] - signal["upper_wick"] + 0.01 * signal["close_location"]
    )


@pytest.mark.asyncio
async def test_full_balance_usage_can_keep_requested_2000_notional():
    strategy = ExplosiveMomentumChaserStrategy(
        strategy_id=1,
        exchange=FakeSizingExchange(),
        symbol="BTC-USDT-SWAP",
        parameters={
            "max_position_usd": 2000,
            "max_total_position_usd": 2000,
            "max_leverage": 3,
            "balance_usage_fraction": 1.0,
        },
    )

    qty = await strategy._calc_contract_qty(
        price=1.0,
        info={"ct_val": 1.0, "lot_sz": 1.0, "min_sz": 1.0},
    )

    assert qty == 2000
