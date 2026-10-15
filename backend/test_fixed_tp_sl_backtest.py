from app.services.backtest.fixed_tp_sl_backtest import FixedTpSlTrendBacktestEngine


def make_engine() -> FixedTpSlTrendBacktestEngine:
    return FixedTpSlTrendBacktestEngine(
        symbol="BTC-USDT-SWAP",
        initial_capital=10000.0,
        fee_rate=0.0,
        leverage=5,
        position_ratio=0.4,
        take_profit_pct=0.01,
        stop_loss_pct=0.005,
        fast_period=2,
        slow_period=3,
    )


def test_same_bar_exit_uses_stop_loss_first():
    engine = make_engine()
    engine.buy(price=100.0, amount=10.0, timestamp=1)
    engine.entry_price = 100.0

    exited = engine._close_if_exit_hit(low_price=99.0, high_price=102.0, timestamp=2)

    assert exited is True
    assert engine.position.amount == 0
    assert engine.trades[-1].price == 99.5
    assert engine.trades[-1].pnl < 0


def test_equity_includes_locked_margin():
    engine = make_engine()
    engine.buy(price=100.0, amount=10.0, timestamp=1)

    engine.update_equity(current_price=100.0, timestamp=1)

    assert engine.equity_curve[-1]["equity"] == 10000.0
