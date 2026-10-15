import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent / "scripts"))

from backtest_volume_vacuum import Profile, failed_p_trade, volume_profile  # noqa: E402


def test_volume_profile_places_poc_at_dominant_price_area():
    rows = []
    for index in range(480):
        price = 108.0 if index < 360 else 101.0
        rows.append({
            "ts": index * 60_000,
            "open": price,
            "high": price + 0.1,
            "low": price - 0.1,
            "close": price,
            "quote_volume": 10_000 if index < 360 else 100,
        })

    profile = volume_profile(rows, bins=40)

    assert profile is not None
    assert profile.poc == pytest.approx(108.0, abs=0.2)
    assert profile.poc_position > 0.60
    assert profile.val <= profile.poc <= profile.vah


def test_failed_p_short_uses_linear_swap_return():
    signal_ts = 8 * 60 * 60 * 1000
    profile = Profile(
        low=90.0,
        high=110.0,
        poc=105.0,
        vah=108.0,
        val=100.0,
        poc_position=0.75,
        bins=40,
    )
    rows = []
    # Rejection bar closes below POC and retests it from underneath.
    for minute in range(8 * 60, 8 * 60 + 5):
        rows.append({
            "ts": minute * 60_000,
            "open": 104.5,
            "high": 105.1,
            "low": 103.8,
            "close": 104.0,
            "quote_volume": 1_000,
        })
    # Price then reaches the vacuum target without touching the stop.
    for minute in range(8 * 60 + 5, 8 * 60 + 20):
        price = 103.0 - (minute - (8 * 60 + 5))
        rows.append({
            "ts": minute * 60_000,
            "open": price,
            "high": price + 0.1,
            "low": price - 1.0,
            "close": price - 0.5,
            "quote_volume": 1_000,
        })

    trade = failed_p_trade(
        {"signal_ts": signal_ts - 60 * 60 * 1000, "symbol": "TEST-USDT-SWAP"},
        profile,
        rows,
    )

    assert trade is not None
    expected_gross = (trade["entry"] - trade["exit"]) / trade["entry"]
    assert trade["net_return"] == pytest.approx(expected_gross - 0.0012)
