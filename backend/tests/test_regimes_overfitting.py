"""Regime classification + overfitting warnings on constructed inputs."""
import numpy as np
import pandas as pd
import pytest

from engine.validation.overfitting import (
    OptimizationRegistry,
    check_complexity,
    check_few_trades,
    check_narrow_peak,
    check_surface_stability,
    check_train_val_divergence,
)
from engine.validation.regimes import RegimeConfig, classify, regime_metrics

from tests.helpers import ts


def make_series(values, start_day=1):
    idx = pd.date_range(ts(start_day), periods=len(values), freq="D")
    return pd.Series([float(v) for v in values], index=idx)


# ── regimes ───────────────────────────────────────────────────────────
def test_trend_classification_hand_built():
    # window 2, threshold 5%. Prices chosen so trailing 2-bar returns are
    # unambiguous:
    #   [100, 100, 112, 125, 124, 112, 100, 100.5]
    # trailing2: idx2: 112/100-1 = +12% bull ; idx3: +25% bull
    # idx4: 124/112-1 = +10.7% bull ; idx5: 112/125-1 = -10.4% bear
    # idx6: 100/124-1 = -19.4% bear ; idx7: 100.5/112-1 = -10.3% bear
    prices = make_series([100, 100, 112, 125, 124, 112, 100, 100.5])
    cfg = RegimeConfig(vol_window=3, trend_window=2, trend_threshold=0.05)
    labels = classify(prices, cfg)
    assert list(labels["trend_regime"].iloc[:2]) == ["undefined", "undefined"]
    assert list(labels["trend_regime"].iloc[2:5]) == ["bull", "bull", "bull"]
    assert list(labels["trend_regime"].iloc[5:]) == ["bear", "bear", "bear"]
    assert list(labels["trending"].iloc[2:5]) == ["trending"] * 3


def test_sideways_classification():
    # Flat prices: every trailing return 0 -> sideways once defined.
    prices = make_series([100] * 6)
    labels = classify(prices, RegimeConfig(vol_window=3, trend_window=2))
    assert set(labels["trend_regime"].iloc[2:]) == {"sideways"}
    assert set(labels["trending"].iloc[2:]) == {"sideways"}


def test_vol_split_high_vs_low():
    # First half tiny moves, second half big moves; median split must put
    # early bars in low_vol and late bars in high_vol.
    rng = np.random.default_rng(3)
    calm = 100 + np.cumsum(rng.normal(0, 0.05, 30))
    wild = calm[-1] + np.cumsum(rng.normal(0, 3.0, 30))
    prices = make_series(np.concatenate([calm, wild]))
    labels = classify(prices, RegimeConfig(vol_window=5, trend_window=5))
    vol = labels["vol_regime"]
    assert (vol.iloc[10:30] == "low_vol").all()
    assert (vol.iloc[40:] == "high_vol").all()


def test_regime_metrics_attribution_hand_computed():
    # Strategy equity: +1% on bars labeled A, -2% on bars labeled B.
    # 3 bars A then 2 bars B after a base bar.
    equity = make_series([100, 101, 102.01, 103.0301, 100.969498, 98.950108])
    labels = pd.Series(
        ["undefined", "A", "A", "A", "B", "B"], index=equity.index
    )
    table = regime_metrics(equity, labels, periods_per_year=252)
    assert table.loc["A", "n_bars"] == 3
    assert table.loc["A", "mean_return"] == pytest.approx(0.01, rel=1e-6)
    assert table.loc["A", "total_return"] == pytest.approx(1.01**3 - 1, rel=1e-6)
    assert table.loc["B", "n_bars"] == 2
    assert table.loc["B", "mean_return"] == pytest.approx(-0.02, rel=1e-6)
    assert table.loc["B", "total_return"] == pytest.approx(0.98**2 - 1, rel=1e-6)
    assert "undefined" not in table.index


# ── overfitting warnings ──────────────────────────────────────────────
def test_narrow_peak_warning_levels():
    assert check_narrow_peak(0.8) is None
    w = check_narrow_peak(0.4)
    assert w is not None and w.severity == "warning" and w.code == "narrow_peak"
    w2 = check_narrow_peak(0.1)
    assert w2.severity == "critical"


def test_train_val_divergence():
    assert check_train_val_divergence(2.0, 1.5) is None       # retained 75%
    w = check_train_val_divergence(2.0, 0.6)                  # retained 30%
    assert w is not None and w.severity == "warning"
    w2 = check_train_val_divergence(2.0, -0.5)                # sign flip
    assert w2.severity == "critical"
    assert check_train_val_divergence(-1.0, -2.0) is None     # nothing to decay


def test_few_trades():
    assert check_few_trades(50) is None
    assert check_few_trades(20).severity == "warning"
    assert check_few_trades(5).severity == "critical"


def test_complexity():
    assert check_complexity(n_combos_tested=20, n_trades=100) is None
    w = check_complexity(n_combos_tested=200, n_trades=100)
    assert w is not None and w.code == "excessive_complexity"
    assert check_complexity(10, 0) is not None                # no trades at all


def test_surface_stability():
    ranges = {"fast": (2, 50), "slow": (5, 100)}
    stable = [{"fast": 10, "slow": 40}, {"fast": 11, "slow": 42},
              {"fast": 10, "slow": 41}]
    assert check_surface_stability(stable, ranges) is None
    # fast jumping 2 -> 48 across folds: pstdev([2, 48, 25]) ~ 18.8 over
    # range 48 -> dispersion ~0.39 > 0.25 -> warning.
    unstable = [{"fast": 2, "slow": 40}, {"fast": 48, "slow": 41},
                {"fast": 25, "slow": 40}]
    w = check_surface_stability(unstable, ranges)
    assert w is not None and w.code == "unstable_surface"
    assert check_surface_stability([{"fast": 3, "slow": 6}], ranges) is None  # 1 fold: n/a


def test_registry_counts_and_warns(tmp_path):
    reg = OptimizationRegistry()
    for i in range(3):
        assert reg.register("fp1", "hash1") == i + 1
    assert reg.check("fp1", "hash1", max_runs=3) is None
    reg.register("fp1", "hash1")
    w = reg.check("fp1", "hash1", max_runs=3)
    assert w is not None and w.code == "repeated_optimization"
    assert reg.check("fp2", "hash1", max_runs=3) is None      # different data

    # persistence roundtrip
    path = tmp_path / "registry.json"
    reg2 = OptimizationRegistry(path=path)
    reg2.register("fpX", "h")
    reg3 = OptimizationRegistry(path=path)
    assert reg3.counts == {"fpX:h": 1}
