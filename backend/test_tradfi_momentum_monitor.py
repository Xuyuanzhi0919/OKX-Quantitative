from collections import deque

import pytest

from app.services.notification.notification_service import notification_service
from app.services.tradfi_momentum_monitor import TradFiMomentumMonitor


class FakeExchange:
    async def get_instruments(self, inst_type="SWAP"):
        assert inst_type == "SWAP"
        return [
            {"instId": "AAPL-USDT-SWAP", "instCategory": "3", "state": "live"},
            {"instId": "XAU-USDT-SWAP", "instCategory": "4", "state": "live"},
            {"instId": "EUR-USDT-SWAP", "instCategory": "6", "state": "suspend"},
            {"instId": "BTC-USDT-SWAP", "instCategory": "1", "state": "live"},
        ]

    async def get_tickers(self, inst_type="SWAP"):
        return []

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_instrument_refresh_keeps_only_live_tradfi_categories():
    monitor = TradFiMomentumMonitor()
    monitor._exchange = FakeExchange()

    await monitor._refresh_instruments(1000)

    assert monitor._instruments == {
        "AAPL-USDT-SWAP": "3",
        "XAU-USDT-SWAP": "4",
    }
    assert monitor.status()["read_only"] is True


@pytest.mark.asyncio
async def test_monitor_can_start_without_bark(monkeypatch):
    monitor = TradFiMomentumMonitor()
    monitor.enabled = True
    monkeypatch.setattr(
        "app.services.tradfi_momentum_monitor.OKXExchange",
        lambda **kwargs: FakeExchange(),
    )

    await monitor.start()

    assert monitor.status()["running"] is True
    await monitor.stop()


def test_find_baseline_uses_latest_point_before_window():
    history = deque([(100.0, 10.0), (150.0, 11.0), (210.0, 12.0)])

    assert TradFiMomentumMonitor._find_baseline(history, 220.0, 60) == (150.0, 11.0)


@pytest.mark.asyncio
async def test_alert_supports_both_directions_and_cooldown(monkeypatch):
    monitor = TradFiMomentumMonitor()
    monitor.cooldown_seconds = 1800
    sent = []

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr(notification_service, "send_bark_notification", fake_send)

    await monitor._maybe_alert(
        "XAU-USDT-SWAP", "4", 101, 100, 1.0, 2000000, 5000, 300, 0.4,
    )
    await monitor._maybe_alert(
        "XAU-USDT-SWAP", "4", 102, 100, 2.0, 2000000, 5100, 300, 0.4,
    )
    await monitor._maybe_alert(
        "XAU-USDT-SWAP", "4", 99, 100, -1.0, 2000000, 5200, 300, 0.4,
    )

    assert len(sent) == 2
    assert "上涨" in sent[0]["title"]
    assert "下跌" in sent[1]["title"]
    assert all(item["data"]["性质"] == "只读预警，不会自动下单" for item in sent)
