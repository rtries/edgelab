"""Example strategies: deterministic behavior on hand-designed fixtures.
No profitability is asserted anywhere — only that orders fire exactly
where the math says they must."""
import pytest

from engine.backtest import Backtester
from engine.data.feeds import InMemoryFeed
from engine.execution.costs import ZeroCostModel
from engine.params import resolve_params
from engine.sdk import SDKAdapter
from engine.strategies.examples import (
    BuyAndHold,
    MACrossover,
    RSIMeanReversion,
    VolatilityBreakout,
)
from engine.types import Side

from tests.helpers import bar


def run(strategy_cls, bars, params=None, cash=100_000.0):
    strat = strategy_cls()
    adapter = SDKAdapter(strat, resolve_params(strategy_cls.params, params))
    bt = Backtester(InMemoryFeed(bars), adapter, ZeroCostModel(),
                    initial_cash=cash, max_participation=None)
    return bt.run(), bt


def test_buy_and_hold_enters_once():
    bars = [bar(d, 100, 101, 99, 100) for d in range(1, 6)]
    result, bt = run(BuyAndHold, bars, {"invest_pct": 0.5}, cash=10_000)
    buys = [o for o in result.orders if o.side is Side.BUY]
    assert len(buys) == 1
    # 0.5 * 10000 / 100 = 50 shares, submitted bar 1, filled bar 2 open.
    assert buys[0].qty == pytest.approx(50.0)
    assert bt.portfolio.position_qty("X") == pytest.approx(50.0)


def test_ma_crossover_fires_at_hand_designed_cross():
    # fast=2, slow=3. Closes: 10, 10, 10, 16, 16 ...
    #   idx2: fast SMA(10,10)=10, slow SMA(10,10,10)=10 -> not above (10 > 10 False)
    #   idx3: fast (10+16)/2 = 13, slow (10+10+16)/3 = 12 -> above=True: CROSS UP
    # Then closes drop to 4:
    #   idx4: closes ...16,16: fast 16, slow 14 -> still above, no action
    #   idx5 close 4: fast (16+4)/2 = 10, slow (16+16+4)/3 = 12 -> CROSS DOWN
    closes = [10, 10, 10, 16, 16, 4, 4]
    bars = [bar(d + 1, c, c + 0.5, c - 0.5, c) for d, c in enumerate(closes)]
    result, bt = run(MACrossover, bars, {"fast": 2, "slow": 3, "invest_pct": 0.5})
    sides = [(o.side, o.qty) for o in result.orders]
    assert len(result.orders) == 2
    assert result.orders[0].side is Side.BUY     # submitted on idx3 bar
    assert result.orders[1].side is Side.SELL    # submitted on idx5 bar
    assert bt.portfolio.position_qty("X") == pytest.approx(0.0)


def test_ma_crossover_rejects_bad_params():
    with pytest.raises(ValueError, match="fast must be < slow"):
        run(MACrossover, [bar(1, 10, 11, 9, 10)], {"fast": 5, "slow": 5})


def test_rsi_mean_reversion_enters_below_entry_level():
    # period=3. Falling closes make RSI 0 once defined (all losses).
    # Closes: 20, 19, 18, 17, 16 -> first defined RSI at idx3 = 0 < entry 30 -> BUY.
    closes = [20, 19, 18, 17, 16]
    bars = [bar(d + 1, c, c + 0.2, c - 0.2, c) for d, c in enumerate(closes)]
    result, _ = run(RSIMeanReversion, bars, {"period": 3, "entry": 30.0, "exit": 55.0, "invest_pct": 0.2})
    buys = [o for o in result.orders if o.side is Side.BUY]
    assert len(buys) == 1


def test_volatility_breakout_enters_on_new_high():
    # lookback=2, atr_period=2. Highs: 10.5, 10.5, 10.5, then close 12 > max(prior highs 10.5) -> enter.
    rows = [
        (1, 10, 10.5, 9.5, 10),
        (2, 10, 10.5, 9.5, 10),
        (3, 10, 10.5, 9.5, 10),
        (4, 11.8, 12.2, 11.5, 12.0),   # close 12 > 10.5 breakout
        (5, 12, 12.4, 11.8, 12.2),
    ]
    bars = [bar(*r) for r in rows]
    result, bt = run(VolatilityBreakout, bars, {"lookback": 2, "atr_period": 2, "atr_mult": 2.0, "invest_pct": 0.3})
    buys = [o for o in result.orders if o.side is Side.BUY]
    assert len(buys) == 1
    assert bt.portfolio.position_qty("X") > 0


def test_examples_are_deterministic():
    closes = [10, 10, 10, 16, 16, 4, 4, 9, 12, 12]
    bars = [bar(d + 1, c, c + 0.5, c - 0.5, c) for d, c in enumerate(closes)]
    for cls, params in [
        (BuyAndHold, None),
        (MACrossover, {"fast": 2, "slow": 3}),
        (RSIMeanReversion, {"period": 3}),
        (VolatilityBreakout, {"lookback": 2, "atr_period": 2}),
    ]:
        r1, _ = run(cls, bars, params)
        r2, _ = run(cls, bars, params)
        assert r1.equity_curve.equals(r2.equity_curve), cls.__name__
        assert [f.price for f in r1.fills] == [f.price for f in r2.fills], cls.__name__
