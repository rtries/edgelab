"""Indicators vs hand-computed fixtures; warm-up NaNs; no leakage;
incremental == vectorized."""
import math

import numpy as np
import pandas as pd
import pytest

from engine.indicators import core as ind
from engine.indicators.incremental import (
    IncrementalATR,
    IncrementalEMA,
    IncrementalRSI,
    IncrementalSMA,
)


def s(values):
    return pd.Series([float(v) for v in values])


def assert_nan_prefix(series, n_nan):
    assert series.iloc[:n_nan].isna().all(), f"expected {n_nan} warm-up NaNs"
    assert series.iloc[n_nan:].notna().all()


def test_sma_fixture():
    # SMA(3) of [1,2,3,4,5] = [nan, nan, 2, 3, 4]
    out = ind.sma(s([1, 2, 3, 4, 5]), 3)
    assert_nan_prefix(out, 2)
    assert list(out.iloc[2:]) == pytest.approx([2.0, 3.0, 4.0])


def test_ema_fixture():
    # EMA(3), alpha = 0.5, seed = SMA(first 3) of [2,4,6] = 4 at idx 2.
    # idx3 = 4 + 0.5*(8-4) = 6 ; idx4 = 6 + 0.5*(10-6) = 8.
    out = ind.ema(s([2, 4, 6, 8, 10]), 3)
    assert_nan_prefix(out, 2)
    assert list(out.iloc[2:]) == pytest.approx([4.0, 6.0, 8.0])


def test_rsi_fixture_hand_computed():
    # Closes [10, 11, 10.5, 11.5, 12.5, 12], n=3.
    # Changes: [+1, -0.5, +1, +1, -0.5]
    # Seed (first 3): avg_gain = (1+0+1)/3 = 2/3 ; avg_loss = 0.5/3 = 1/6
    #   -> RS = 4, RSI = 100 - 100/5 = 80          (index 3)
    # Next (+1): ag = (2/3*2 + 1)/3 = 7/9 ; al = (1/6*2)/3 = 1/9
    #   -> RS = 7, RSI = 87.5                       (index 4)
    # Next (-0.5): ag = (7/9*2)/3 = 14/27 ; al = (1/9*2 + 0.5)/3 = 0.24074074
    #   -> RS = 2.15384615, RSI = 68.29268293       (index 5)
    out = ind.rsi(s([10, 11, 10.5, 11.5, 12.5, 12]), 3)
    assert_nan_prefix(out, 3)
    assert out.iloc[3] == pytest.approx(80.0)
    assert out.iloc[4] == pytest.approx(87.5)
    assert out.iloc[5] == pytest.approx(68.29268293, rel=1e-8)


def test_atr_fixture_hand_computed():
    # Bars (h, l, c):
    #   b0 (10, 9, 9.5)      TR undefined (no prev close)
    #   b1 (10.5, 9.8, 10.2) TR = max(0.7, |10.5-9.5|=1.0, |9.8-9.5|=0.3) = 1.0
    #   b2 (10.4, 10.0, 10.1) TR = max(0.4, 0.3, 0.5)... hand-check:
    #        h-l = 0.4 ; |h-pc| = |10.4-10.2| = 0.2 ; |l-pc| = |10.0-10.2| = 0.2 -> 0.4
    #   b3 (11, 10, 10.8)    TR = max(1.0, |11-10.1|=0.9, |10-10.1|=0.1) = 1.0
    # ATR(2): seed at idx2 = (1.0 + 0.4)/2 = 0.7 ; idx3 = (0.7*1 + 1.0)/2 = 0.85
    h, lo, c = s([10, 10.5, 10.4, 11]), s([9, 9.8, 10.0, 10]), s([9.5, 10.2, 10.1, 10.8])
    out = ind.atr(h, lo, c, 2)
    assert_nan_prefix(out, 2)
    assert out.iloc[2] == pytest.approx(0.7)
    assert out.iloc[3] == pytest.approx(0.85)


def test_macd_fixture():
    # Series [2,4,6,8,10], fast=2, slow=3, signal=2.
    # ema2: seed idx1 = 3; alpha=2/3: idx2 = 3+2/3*3 = 5; idx3 = 7; idx4 = 9.
    # ema3: [nan, nan, 4, 6, 8]  (from EMA fixture logic)
    # macd = ema2-ema3: [nan, nan, 1, 1, 1]
    # signal = ema2 over defined macd values: seed at 2nd defined = mean(1,1) = 1 (idx3); idx4 = 1.
    out = ind.macd(s([2, 4, 6, 8, 10]), fast=2, slow=3, signal=2)
    assert out["macd"].iloc[:2].isna().all()
    assert list(out["macd"].iloc[2:]) == pytest.approx([1.0, 1.0, 1.0])
    assert out["signal"].iloc[:3].isna().all()
    assert list(out["signal"].iloc[3:]) == pytest.approx([1.0, 1.0])
    assert list(out["hist"].iloc[3:]) == pytest.approx([0.0, 0.0])


def test_bollinger_fixture():
    # n=3, k=2 on [1,2,3]: mid = 2, population std = sqrt(2/3) = 0.81649658
    # upper = 2 + 1.63299316 = 3.63299316 ; lower = 0.36700684
    out = ind.bollinger(s([1, 2, 3]), n=3, k=2.0)
    assert out["mid"].iloc[2] == pytest.approx(2.0)
    assert out["upper"].iloc[2] == pytest.approx(3.63299316, rel=1e-8)
    assert out["lower"].iloc[2] == pytest.approx(0.36700684, rel=1e-7)


def test_rolling_std_ddof():
    # [1,2,3]: population std = 0.81649658 ; sample std = 1.0
    x = s([1, 2, 3])
    assert ind.rolling_std(x, 3, ddof=0).iloc[2] == pytest.approx(0.81649658, rel=1e-8)
    assert ind.rolling_std(x, 3, ddof=1).iloc[2] == pytest.approx(1.0)


def test_rolling_max_min_roc():
    x = s([100, 110, 121, 133.1])
    assert list(ind.rolling_max(x, 2).iloc[1:]) == pytest.approx([110, 121, 133.1])
    assert list(ind.rolling_min(x, 2).iloc[1:]) == pytest.approx([100, 110, 121])
    # ROC(2): idx2 = 121/100 - 1 = 0.21 ; idx3 = 133.1/110 - 1 = 0.21
    out = ind.roc(x, 2)
    assert_nan_prefix(out, 2)
    assert list(out.iloc[2:]) == pytest.approx([0.21, 0.21])


def test_no_future_leakage_prefix_property():
    # For every indicator: value at index i computed on the [0..i] prefix
    # must equal the value at i computed on the full series.
    rng = np.random.default_rng(7)
    closes = pd.Series(100 + np.cumsum(rng.normal(0, 1, 40)))
    high = closes + rng.uniform(0.1, 1.0, 40)
    low = closes - rng.uniform(0.1, 1.0, 40)

    cases = {
        "sma": lambda x: ind.sma(x, 5),
        "ema": lambda x: ind.ema(x, 5),
        "rsi": lambda x: ind.rsi(x, 5),
        "roc": lambda x: ind.roc(x, 5),
        "boll_mid": lambda x: ind.bollinger(x, 5)["mid"],
        "macd": lambda x: ind.macd(x, 3, 6, 3)["macd"],
    }
    for name, fn in cases.items():
        full = fn(closes)
        for i in (10, 25, 39):
            prefix_val = fn(closes.iloc[: i + 1]).iloc[-1]
            full_val = full.iloc[i]
            if math.isnan(full_val):
                assert math.isnan(prefix_val), name
            else:
                assert prefix_val == pytest.approx(full_val, rel=1e-12), name

    full_atr = ind.atr(high, low, closes, 5)
    for i in (10, 25, 39):
        prefix_val = ind.atr(high.iloc[: i + 1], low.iloc[: i + 1], closes.iloc[: i + 1], 5).iloc[-1]
        assert prefix_val == pytest.approx(full_atr.iloc[i], rel=1e-12)


def test_incremental_matches_vectorized():
    rng = np.random.default_rng(11)
    closes = pd.Series(50 + np.cumsum(rng.normal(0, 0.5, 60)))
    high = closes + rng.uniform(0.05, 0.6, 60)
    low = closes - rng.uniform(0.05, 0.6, 60)

    v_sma, v_ema = ind.sma(closes, 7), ind.ema(closes, 7)
    v_rsi, v_atr = ind.rsi(closes, 7), ind.atr(high, low, closes, 7)
    i_sma, i_ema = IncrementalSMA(7), IncrementalEMA(7)
    i_rsi, i_atr = IncrementalRSI(7), IncrementalATR(7)

    for i in range(60):
        for stream, vec in [
            (i_sma.update(closes[i]), v_sma.iloc[i]),
            (i_ema.update(closes[i]), v_ema.iloc[i]),
            (i_rsi.update(closes[i]), v_rsi.iloc[i]),
            (i_atr.update(high[i], low[i], closes[i]), v_atr.iloc[i]),
        ]:
            if stream is None:
                assert math.isnan(vec)
            else:
                assert stream == pytest.approx(vec, rel=1e-12)
