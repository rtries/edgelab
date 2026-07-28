"""Portfolio ledger: cash, equity, margin, buying power. Hand-calculated."""
import pytest

from engine.portfolio.accounting import Portfolio
from engine.types import Fill, Side

from tests.helpers import ts


def fill(side: Side, qty: float, price: float, fees: float = 0.0, day: int = 1, sym: str = "X") -> Fill:
    return Fill(order_id=1, symbol=sym, side=side, qty=qty, price=price, fees=fees, ts=ts(day))


def test_long_buy_cash_and_equity():
    # Cash 10,000. Buy 50 @ 100.20, fee 1.
    # cash = 10000 - 5010 - 1 = 4989.
    # Mark @ 101: long_value = 5050, equity = 4989 + 5050 = 10039.
    # Identity check: 10000 + 0 realized + (101 - 100.2)*50 unrealized - 1 fee
    #               = 10000 + 40 - 1 = 10039.
    p = Portfolio(initial_cash=10_000)
    p.apply_fill(fill(Side.BUY, 50, 100.20, fees=1.0))
    assert p.cash == pytest.approx(4989.0)
    p.mark("X", 101.0)
    assert p.long_value == pytest.approx(5050.0)
    assert p.equity == pytest.approx(10_039.0)
    assert p.unrealized_pnl == pytest.approx(40.0)
    assert p.equity == pytest.approx(
        p.initial_cash + p.realized_pnl + p.unrealized_pnl - p.total_fees
    )


def test_short_sale_credits_cash():
    # Cash 10,000. Short 10 @ 49.90, fee 1 -> cash = 10000 + 499 - 1 = 10498.
    # Mark @ 51: short_value = 510, equity = 10498 - 510 = 9988.
    # Identity: 10000 + (49.9 - 51)*10 - 1 = 10000 - 11 - 1 = 9988.
    p = Portfolio(initial_cash=10_000)
    p.apply_fill(fill(Side.SELL, 10, 49.90, fees=1.0))
    assert p.cash == pytest.approx(10_498.0)
    p.mark("X", 51.0)
    assert p.short_value == pytest.approx(510.0)
    assert p.equity == pytest.approx(9_988.0)
    assert p.unrealized_pnl == pytest.approx(-11.0)


def test_short_cover_realizes_pnl():
    # Continue: cover 10 @ 48.096, fee 1.
    # cash = 10498 - 480.96 - 1 = 10016.04
    # realized = (49.9 - 48.096) * 10 = 18.04; equity = cash (flat).
    # Identity: 10000 + 18.04 - 2 fees = 10016.04.
    p = Portfolio(initial_cash=10_000)
    p.apply_fill(fill(Side.SELL, 10, 49.90, fees=1.0))
    p.apply_fill(fill(Side.BUY, 10, 48.096, fees=1.0, day=2))
    assert p.cash == pytest.approx(10_016.04)
    assert p.realized_pnl == pytest.approx(18.04)
    assert p.total_fees == pytest.approx(2.0)
    assert not p.has_open_positions()
    assert p.equity == pytest.approx(10_016.04)


def test_buying_power_cash_account():
    # Cash account (multiplier 1): equity 10,000, no positions -> BP 10,000.
    # After buying 50 @ 100 (mark 100): gross = 5000, BP = 10000 - 5000 = 5000.
    p = Portfolio(initial_cash=10_000, margin_multiplier=1.0)
    assert p.buying_power == pytest.approx(10_000.0)
    p.apply_fill(fill(Side.BUY, 50, 100.0))
    p.mark("X", 100.0)
    assert p.buying_power == pytest.approx(5_000.0)


def test_buying_power_margin_account():
    # 2x margin: BP = 2*10000 - 0 = 20000; after 50 @ 100: 2*10000 - 5000 = 15000.
    p = Portfolio(initial_cash=10_000, margin_multiplier=2.0)
    assert p.buying_power == pytest.approx(20_000.0)
    p.apply_fill(fill(Side.BUY, 50, 100.0))
    p.mark("X", 100.0)
    assert p.buying_power == pytest.approx(15_000.0)


def test_check_order_rejects_oversized():
    # Cash 1,000; market buy 100 @ est 50 needs 5,000 > 1,000 -> rejected.
    p = Portfolio(initial_cash=1_000)
    p.mark("X", 50.0)
    reason = p.check_order("X", Side.BUY, 100, 50.0)
    assert reason is not None and "insufficient buying power" in reason


def test_check_order_allows_reducing_position():
    # Long 100 @ 100 with tiny remaining BP: SELLING those 100 must be allowed
    # (it reduces exposure), even though 100 * 100 > buying power.
    p = Portfolio(initial_cash=10_000)
    p.apply_fill(fill(Side.BUY, 100, 100.0))  # cash now 0, BP ~0
    p.mark("X", 100.0)
    assert p.buying_power == pytest.approx(0.0)
    assert p.check_order("X", Side.SELL, 100, 100.0) is None
    # But flipping 100 -> short 150 must check the 50 increasing shares.
    reason = p.check_order("X", Side.SELL, 150, 100.0)
    assert reason is not None


def test_large_commission_exceeds_proceeds():
    # Edge case: fee larger than the trade's gross profit.
    # Buy 1 @ 100 fee 50; sell 1 @ 101 fee 50.
    # gross realized = +1, fees = 100 -> equity = 10000 + 1 - 100 = 9901.
    p = Portfolio(initial_cash=10_000)
    p.apply_fill(fill(Side.BUY, 1, 100.0, fees=50.0))
    p.apply_fill(fill(Side.SELL, 1, 101.0, fees=50.0, day=2))
    assert p.realized_pnl == pytest.approx(1.0)
    assert p.total_fees == pytest.approx(100.0)
    assert p.equity == pytest.approx(9_901.0)


def test_multi_asset_valuation():
    # Long 10 X @ 100 (mark 110) and short 5 Y @ 200 (mark 190). No fees.
    # cash = 10000 - 1000 + 1000 = 10000
    # long_value = 1100, short_value = 950
    # equity = 10000 + 1100 - 950 = 10150
    # unrealized = (110-100)*10 + (200-190)*5 = 100 + 50 = 150. Identity holds.
    p = Portfolio(initial_cash=10_000)
    p.apply_fill(fill(Side.BUY, 10, 100.0, sym="X"))
    p.apply_fill(fill(Side.SELL, 5, 200.0, sym="Y"))
    p.mark("X", 110.0)
    p.mark("Y", 190.0)
    assert p.cash == pytest.approx(10_000.0)
    assert p.long_value == pytest.approx(1_100.0)
    assert p.short_value == pytest.approx(950.0)
    assert p.equity == pytest.approx(10_150.0)
    assert p.unrealized_pnl == pytest.approx(150.0)
    assert p.equity == pytest.approx(
        p.initial_cash + p.realized_pnl + p.unrealized_pnl - p.total_fees
    )


def test_snapshot_reports_positions():
    p = Portfolio(initial_cash=10_000)
    p.apply_fill(fill(Side.BUY, 10, 100.0))
    p.mark("X", 105.0)
    snap = p.snapshot(ts(2))
    assert snap.positions["X"].qty == 10
    assert snap.positions["X"].avg_price == pytest.approx(100.0)
    assert snap.positions["X"].unrealized_pnl == pytest.approx(50.0)
    assert snap.gross_exposure == pytest.approx(1_050.0)
