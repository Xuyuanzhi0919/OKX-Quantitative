# Archived strategy 7: top gainers momentum

Archived before deletion on 2026-07-15 (Asia/Shanghai).

## Configuration

- Name: 涨幅榜前三15m动量实盘
- Type: `top_gainers_momentum`
- Symbol placeholder: `TOP-GAINERS-USDT-SWAP`
- Runtime timeframe: `5m`
- Status at deletion: `paused`
- Started: `2026-07-13T23:04:39.578362+08:00`
- Stopped: `2026-07-14T05:40:34.785909+08:00`
- Initial capital / risk base: 1000 USDT
- Maximum leverage: 3x
- Maximum position notional: 1500 USDT
- Maximum open positions: 1
- Risk per trade: 2.5%
- ATR stop / take-profit R / trailing ATR: 1.8 / 1.8 / 1.6
- Direction: both
- Attached TP/SL: enabled
- Consecutive-loss fuse: 2

## Locally recorded order IDs

`3739733488752205824`, `3739854660785479680`,
`3739875273507938304`, `3740095234385977344`,
`3740383213386014720`, `3740383317069209600`,
`3740481380265828352`, `3740518089451970560`,
`3740528335566217216`.

The database omitted some attached TP/SL exit orders, so OKX bills/order history
remain the accounting source of truth.

## Verified performance verdict

- Reconstructed live net PnL: approximately -11.33 USDT (-1.13% on 1000 USDT)
- Completed round trips: 7
- Win rate: 57.1%
- Profit factor: approximately 0.73
- Fees: approximately 9.06 USDT
- Peak-to-trough drawdown during the run: approximately 41.44 USDT

The no-lookahead 90-day walk-forward research also rejected the strategy:

- Training return after costs: -14.63%
- Final 30-day out-of-sample return after costs: -7.16%
- Zero-cost out-of-sample return: -3.14%

Research artifacts:

- `tradekit/research/return_first_walkforward.py`
- `.run/research/return_first_result.json`
- `.run/research/return_first_zero_cost.json`

## Position boundary at deletion

The strategy had no attributed active position. The exchange returned active
MET-USDT-SWAP and ZBT-USDT-SWAP positions with `strategy_id=null`; these were
created after strategy 7 stopped and were deliberately left untouched.
