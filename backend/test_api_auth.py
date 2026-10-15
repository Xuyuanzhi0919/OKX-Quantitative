import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api import deps
from app.api.endpoints import strategies
from app.api.endpoints.strategies import (
    _get_account_position_status,
    _get_account_summary,
    _select_mobile_strategy,
    _summarize_close_events,
)


def request(method: str) -> Request:
    return Request({"type": "http", "method": method, "headers": []})


def test_legacy_get_without_token_resolves_default_user(monkeypatch):
    monkeypatch.setattr(deps, "ensure_default_user", lambda db: 1)
    assert deps.require_current_user_id(
        request=request("GET"), db=object(), authorization=None
    ) == 1


def test_mutation_without_bearer_token_is_rejected():
    with pytest.raises(HTTPException) as exc:
        deps.require_current_user_id(
            request=request("POST"), db=object(), authorization=None
        )
    assert exc.value.status_code == 401


def test_invalid_bearer_token_is_rejected_for_mutation(monkeypatch):
    monkeypatch.setattr(deps.settings, "API_ACCESS_TOKEN", "mobile-read-token")
    with pytest.raises(HTTPException) as exc:
        deps.require_current_user_id(
            request=request("DELETE"),
            db=object(),
            authorization="Bearer incorrect",
        )
    assert exc.value.status_code == 401


def test_service_token_resolves_default_user(monkeypatch):
    monkeypatch.setattr(deps.settings, "API_ACCESS_TOKEN", "mobile-read-token")
    monkeypatch.setattr(deps, "ensure_default_user", lambda db: 1)
    user_id = deps.require_current_user_id(
        request=request("POST"),
        db=object(),
        authorization="Bearer mobile-read-token",
    )
    assert user_id == 1


def test_mobile_token_only_works_for_mobile_read_dependency(monkeypatch):
    monkeypatch.setattr(deps.settings, "API_ACCESS_TOKEN", "full-service-token")
    monkeypatch.setattr(deps.settings, "MOBILE_READ_TOKEN", "scoped-mobile-token")
    monkeypatch.setattr(deps, "ensure_default_user", lambda db: 1)

    with pytest.raises(HTTPException) as exc:
        deps.require_current_user_id(
            request=request("POST"),
            db=object(),
            authorization="Bearer scoped-mobile-token",
        )
    assert exc.value.status_code == 401

    assert deps.require_mobile_read_user_id(
        db=object(),
        authorization="Bearer scoped-mobile-token",
    ) == 1


def test_mobile_dependency_stays_strict_without_token():
    with pytest.raises(HTTPException) as exc:
        deps.require_mobile_read_user_id(db=object(), authorization=None)
    assert exc.value.status_code == 401


def test_mobile_strategy_selection_prefers_running_then_newest():
    class StrategyRow:
        def __init__(self, strategy_id, status):
            self.id = strategy_id
            self.status = status

    class Query:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def all(self):
            return self.rows

    class DB:
        def __init__(self, rows):
            self.rows = rows

        def query(self, model):
            return Query(self.rows)

    newest = StrategyRow(3, "paused")
    running = StrategyRow(2, "running")
    assert _select_mobile_strategy(DB([newest, running]), 1) is running
    assert _select_mobile_strategy(DB([newest]), 1) is newest
    assert _select_mobile_strategy(DB([]), 1) is None


def test_close_event_summary_is_restart_safe():
    class Event:
        def __init__(self, pnl):
            self.data = {"pnl": pnl}

    summary = _summarize_close_events([Event("37.65"), Event(29.67), Event(-8)])
    assert summary["realized_pnl"] == pytest.approx(59.32)
    assert summary["total_trades"] == 3
    assert summary["winning_trades"] == 2
    assert summary["win_rate"] == pytest.approx(66.6666667)


def test_partial_close_contributes_pnl_without_incrementing_trade_count():
    class Event:
        def __init__(self, event_type, pnl):
            self.event_type = event_type
            self.data = {"pnl": pnl}

    summary = _summarize_close_events([
        Event("partial_close", -35.87),
        Event("close_position", -8.2),
    ])

    assert summary["realized_pnl"] == pytest.approx(-44.07)
    assert summary["total_trades"] == 1
    assert summary["winning_trades"] == 0


@pytest.mark.asyncio
async def test_stopped_strategy_still_reads_account_from_bound_api(monkeypatch):
    class Exchange:
        closed = False

        async def get_balance(self):
            return {
                "totalEq": "160.68",
                "imr": "0",
                "notionalUsd": "0",
                "details": [{"availBal": "159.50", "cashBal": "160.68", "upl": "0"}],
            }

        async def close(self):
            self.closed = True

    class Strategy:
        id = 1
        user_id = 1
        api_config_id = 2

    exchange = Exchange()
    monkeypatch.setattr(strategies.strategy_manager, "get_strategy", lambda _strategy_id: None)
    monkeypatch.setattr(
        strategies.api_config_service,
        "get_exchange",
        lambda user_id, config_id: exchange,
    )

    account = await _get_account_summary(Strategy())

    assert account["total_equity"] == pytest.approx(160.68)
    assert account["available_balance"] == pytest.approx(159.50)
    assert exchange.closed is True


@pytest.mark.asyncio
async def test_stopped_strategy_includes_manual_exchange_positions(monkeypatch):
    class Exchange:
        closed = False

        async def get_positions(self, inst_type=None):
            assert inst_type == "SWAP"
            return [{
                "instId": "BTC-USDT-SWAP",
                "pos": "2",
                "posSide": "long",
                "avgPx": "100000",
                "markPx": "101000",
                "lever": "3",
                "notionalUsd": "2020",
                "margin": "670",
                "imr": "673.33",
                "liqPx": "75000",
                "upl": "20",
                "uplRatio": "0.01",
                "cTime": "1760000000000",
            }]

        async def close(self):
            self.closed = True

    class Strategy:
        id = 1
        user_id = 1
        api_config_id = 2

    exchange = Exchange()
    monkeypatch.setattr(strategies.strategy_manager, "get_strategy", lambda _strategy_id: None)
    monkeypatch.setattr(
        strategies.api_config_service,
        "get_exchange",
        lambda user_id, config_id: exchange,
    )

    status = await _get_account_position_status(Strategy())

    assert status["open_positions"] == 1
    assert status["current_notional_usd"] == pytest.approx(2020)
    assert status["positions"][0]["source"] == "manual"
    assert status["positions"][0]["unrealized_pnl"] == pytest.approx(20)
    assert status["positions"][0]["initial_margin"] == pytest.approx(673.33)
    assert status["positions"][0]["liquidation_price"] == pytest.approx(75000)
    assert exchange.closed is True
