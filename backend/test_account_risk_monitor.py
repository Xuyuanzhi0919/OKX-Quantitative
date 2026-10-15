import pytest

from app.services.account_monitor import AccountMonitor
from app.services.exchange.okx import OKXExchange
from app.services.notification.notification_service import notification_service


def make_position(**overrides):
    position = {
        "symbol": "SHAZ-USDT-SWAP",
        "leverage": 10,
        "current_price": 50,
        "liquidation_price": 47,
        "unrealized_pnl": 30,
    }
    position.update(overrides)
    return position


def test_build_risk_conditions_covers_account_position_and_stop_risks():
    monitor = AccountMonitor(interval=10)
    conditions = monitor._build_risk_conditions(
        balance_data={
            "total_equity": 300,
            "available_balance": 10,
            "initial_margin": 180,
        },
        positions=[make_position()],
        protected_symbols=set(),
    )

    codes = {item["code"] for item in conditions}
    assert "margin_usage" in codes
    assert "low_available" in codes
    assert "high_leverage:SHAZ-USDT-SWAP" in codes
    assert "liquidation_distance:SHAZ-USDT-SWAP" in codes
    assert "missing_stop:SHAZ-USDT-SWAP" in codes


def test_protected_position_does_not_emit_missing_stop():
    monitor = AccountMonitor(interval=10)
    conditions = monitor._build_risk_conditions(
        balance_data={"total_equity": 300, "available_balance": 300, "initial_margin": 0},
        positions=[make_position(leverage=1, liquidation_price=0)],
        protected_symbols={"SHAZ-USDT-SWAP"},
    )

    assert not any(item["code"].startswith("missing_stop:") for item in conditions)


def test_isolated_position_margin_is_used_when_account_imr_is_blank():
    monitor = AccountMonitor(interval=10)
    conditions = monitor._build_risk_conditions(
        balance_data={"total_equity": 300, "available_balance": 200, "initial_margin": 0},
        positions=[make_position(leverage=1, liquidation_price=0, margin=180, imr=0)],
        protected_symbols={"SHAZ-USDT-SWAP"},
    )

    assert "margin_usage" in {item["code"] for item in conditions}


def test_profit_drawdown_is_measured_from_position_peak():
    monitor = AccountMonitor(interval=10)
    balance = {"total_equity": 300, "available_balance": 300, "initial_margin": 0}
    monitor._build_risk_conditions(
        balance,
        [make_position(leverage=1, liquidation_price=0, unrealized_pnl=100)],
        {"SHAZ-USDT-SWAP"},
    )
    conditions = monitor._build_risk_conditions(
        balance,
        [make_position(leverage=1, liquidation_price=0, unrealized_pnl=50)],
        {"SHAZ-USDT-SWAP"},
    )

    assert "profit_drawdown:SHAZ-USDT-SWAP" in {item["code"] for item in conditions}


@pytest.mark.asyncio
async def test_identical_risk_alert_is_deduplicated_during_cooldown(monkeypatch):
    monitor = AccountMonitor(interval=10)
    monitor.configure({"check_interval_seconds": 10, "cooldown_seconds": 1800})
    monkeypatch.setattr(monitor, "_get_stop_protected_symbols", lambda: _async_value(set()))
    sent = []

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr(notification_service, "send_bark_alert", fake_send)
    balance = {"total_equity": 300, "available_balance": 10, "initial_margin": 180}
    positions = {"positions": [make_position()]}

    await monitor._maybe_send_risk_alert(balance, positions)
    await monitor._maybe_send_risk_alert(balance, positions)

    assert len(sent) == 1
    assert "只读监控" in sent[0]["data"]["模式"]


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_okx_pending_algo_orders_uses_official_read_endpoint(monkeypatch):
    exchange = OKXExchange("key", "secret", "passphrase")

    async def fake_request(**kwargs):
        assert kwargs["method"] == "GET"
        assert kwargs["endpoint"] == "/api/v5/trade/orders-algo-pending"
        assert kwargs["params"] == {"ordType": "conditional", "instType": "SWAP"}
        assert kwargs["auth_required"] is True
        return {"code": "0", "data": [{"instId": "SHAZ-USDT-SWAP", "slTriggerPx": "45"}]}

    monkeypatch.setattr(exchange, "_request", fake_request)
    orders = await exchange.get_pending_algo_orders("conditional", inst_type="SWAP")

    assert orders[0]["slTriggerPx"] == "45"
