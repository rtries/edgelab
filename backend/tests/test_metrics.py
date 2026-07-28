"""Metrics: every value hand-computed in the comments."""
import math

import numpy as np
import pandas as pd
import pytest

from engine.metrics import performance as m

from tests.helpers import ts


def eq(values, start_day=1):
    idx = pd.DatetimeIndex([ts(start_day + i) for i in range(len(values))])
    return pd.Series(values, index=idx, dtype=float)


def test_returns_from_equity():
    r = m.returns_from_equity(eq([100, 110, 99]))
    assert list(r.round(10)) == [0.1, -0.1]


def test_sharpe_hand_computed():
    # equity [100, 110, 99, 108.9] -> returns [0.10, -0.10, 0.10]
    # mean = 0.0333333...; deviations [0.0666667, -0.1333333, 0.0666667]
    # sum sq = 0.00444444 + 0.01777778 + 0.00444444 = 0.02666667
    # var(ddof=1) = 0.01333333 ; std = 0.11547005
    # sharpe = 0.03333333 / 0.11547005 * sqrt(252)
    #        = 0.28867513 * 15.87450787 = 4.58257569
    r = m.returns_from_equity(eq([100, 110, 99, 108.9]))
    assert m.sharpe(r) == pytest.approx(4.58257569, rel=1e-6)


def test_sortino_hand_computed():
    # Same returns. downside = sqrt((0 + 0.01 + 0)/3) = sqrt(0.00333333)
    #          = 0.05773503
    # sortino = 0.03333333 / 0.05773503 * 15.87450787
    #         = 0.57735027 * 15.87450787 = 9.16515139
    r = m.returns_from_equity(eq([100, 110, 99, 108.9]))
    assert m.sortino(r) == pytest.approx(9.16515139, rel=1e-6)


def test_sortino_no_downside_is_inf():
    r = pd.Series([0.01, 0.02, 0.01])
    assert m.sortino(r) == math.inf


def test_max_drawdown_hand_computed():
    # equity [100, 110, 99, 108.9]; cummax [100, 110, 110, 110]
    # dd = [0, 0, -0.1, -0.01] -> max drawdown = -0.1
    assert m.max_drawdown(eq([100, 110, 99, 108.9])) == pytest.approx(-0.1)


def test_max_drawdown_monotonic_up_is_zero():
    assert m.max_drawdown(eq([100, 101, 102])) == 0.0


def test_ulcer_index_hand_computed():
    # dd_pct = [0, 0, -10, -1] -> mean sq = (0+0+100+1)/4 = 25.25
    # ulcer = sqrt(25.25) = 5.02493781
    assert m.ulcer_index(eq([100, 110, 99, 108.9])) == pytest.approx(5.02493781, rel=1e-6)


def test_cagr_hand_computed():
    # 3 periods, 100 -> 108.9: (1.089)^(252/3) - 1 = 1.089^84 - 1
    expected = 1.089 ** 84 - 1
    assert m.cagr(eq([100, 110, 99, 108.9])) == pytest.approx(expected, rel=1e-9)


def test_calmar_is_cagr_over_mdd():
    e = eq([100, 110, 99, 108.9])
    assert m.calmar(e) == pytest.approx(m.cagr(e) / 0.1, rel=1e-9)


def test_trade_stats_hand_computed():
    # pnls [10, -5, 15, -10, 20]:
    # wins sum 45, losses sum 15 -> profit factor 3.0
    # win rate 3/5 = 0.6 ; expectancy 30/5 = 6.0
    # avg win 45/3 = 15 ; avg loss -15/2 = -7.5
    pnls = pd.Series([10.0, -5.0, 15.0, -10.0, 20.0])
    assert m.profit_factor(pnls) == pytest.approx(3.0)
    assert m.win_rate(pnls) == pytest.approx(0.6)
    assert m.expectancy(pnls) == pytest.approx(6.0)
    assert m.avg_win(pnls) == pytest.approx(15.0)
    assert m.avg_loss(pnls) == pytest.approx(-7.5)


def test_trade_stats_degenerate_cases():
    empty = pd.Series(dtype=float)
    assert m.profit_factor(empty) == 0.0
    assert m.win_rate(empty) == 0.0
    assert m.expectancy(empty) == 0.0
    all_wins = pd.Series([5.0, 3.0])
    assert m.profit_factor(all_wins) == math.inf
    assert m.avg_loss(all_wins) == 0.0
    # Breakeven trades are NOT wins.
    assert m.win_rate(pd.Series([0.0, 1.0])) == pytest.approx(0.5)


def test_exposure():
    flags = pd.Series([0.0, 1.0, 1.0, 0.0])
    assert m.exposure(flags) == pytest.approx(0.5)


def test_rolling_returns():
    # window 2 on [100, 110, 121, 133.1]: [21%, 21%]
    rr = m.rolling_returns(eq([100, 110, 121, 133.1]), window=2)
    assert list(rr.round(10)) == [0.21, 0.21]


def test_monthly_returns():
    # Jan: 100 -> 110 (+10%). Feb: 110 -> 99 (-10%).
    idx = pd.DatetimeIndex([ts(2, month=1), ts(31, month=1), ts(15, month=2), ts(28, month=2)])
    e = pd.Series([100.0, 110.0, 105.0, 99.0], index=idx)
    mr = m.monthly_returns(e)
    assert len(mr) == 2
    assert mr.iloc[0] == pytest.approx(0.10)
    assert mr.iloc[1] == pytest.approx(-0.10)


def test_full_report_keys_and_values():
    e = eq([100, 110, 99, 108.9])
    pnls = pd.Series([10.0, -1.1])
    flags = pd.Series([1.0, 1.0, 0.0, 0.0])
    report = m.full_report(e, pnls, flags)
    assert report["start_equity"] == 100.0
    assert report["end_equity"] == pytest.approx(108.9)
    assert report["total_return"] == pytest.approx(0.089)
    assert report["max_drawdown"] == pytest.approx(-0.1)
    assert report["n_trades"] == 2.0
    assert report["exposure"] == pytest.approx(0.5)
    assert report["sharpe"] == pytest.approx(4.58257569, rel=1e-6)


def test_sharpe_zero_variance_is_zero():
    assert m.sharpe(pd.Series([0.01, 0.01, 0.01])) == 0.0
    assert m.sharpe(pd.Series([0.01])) == 0.0
