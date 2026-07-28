"""Regime classification and per-regime performance attribution.

DESCRIPTIVE, IN-SAMPLE analysis: regimes are labeled using the full price
history (median vol split), which is fine for attribution ("where did the
P&L come from?") and NOT a tradable signal. That distinction is stated in
the report; do not quietly turn these labels into features.

Definitions (hand-fixtured):
- volatility regime: rolling std (window w) of benchmark simple returns;
  high_vol where vol >= full-sample median of defined vols, else low_vol.
- trend regime: rolling cumulative return over window w:
    bull      if trailing return >= +threshold
    bear      if trailing return <= -threshold
    sideways  otherwise
  trending = bull or bear.
- Warm-up bars (undefined rolling stats) are labeled "undefined" and
  excluded from attribution.
- regime_metrics: strategy per-bar equity returns joined to same-ts
  labels; per regime: n_bars, total_return (compounded), mean/std of
  per-bar returns, and annualized sharpe (ddof=1, sqrt(periods)).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

UNDEFINED = "undefined"


@dataclass(frozen=True, slots=True)
class RegimeConfig:
    vol_window: int = 20
    trend_window: int = 20
    trend_threshold: float = 0.05     # +/-5% trailing return over the window
    periods_per_year: int = 252


def classify(benchmark_close: pd.Series, cfg: RegimeConfig = RegimeConfig()) -> pd.DataFrame:
    """Returns a frame indexed like the input with columns:
    vol_regime, trend_regime, trending (bool as 'trending'/'sideways')."""
    returns = benchmark_close.pct_change()
    vol = returns.rolling(cfg.vol_window).std(ddof=1)
    vol_median = vol.dropna().median()
    vol_regime = pd.Series(UNDEFINED, index=benchmark_close.index, dtype=object)
    defined = vol.notna()
    vol_regime[defined & (vol >= vol_median)] = "high_vol"
    vol_regime[defined & (vol < vol_median)] = "low_vol"

    trailing = benchmark_close.pct_change(cfg.trend_window)
    trend_regime = pd.Series(UNDEFINED, index=benchmark_close.index, dtype=object)
    tdef = trailing.notna()
    trend_regime[tdef & (trailing >= cfg.trend_threshold)] = "bull"
    trend_regime[tdef & (trailing <= -cfg.trend_threshold)] = "bear"
    trend_regime[tdef & (trailing.abs() < cfg.trend_threshold)] = "sideways"

    trending = pd.Series(UNDEFINED, index=benchmark_close.index, dtype=object)
    trending[trend_regime.isin(["bull", "bear"])] = "trending"
    trending[trend_regime == "sideways"] = "sideways"

    return pd.DataFrame(
        {"vol_regime": vol_regime, "trend_regime": trend_regime, "trending": trending}
    )


def regime_metrics(
    equity: pd.Series,
    labels: pd.Series,
    periods_per_year: int = 252,
) -> pd.DataFrame:
    """Per-regime attribution of the STRATEGY's per-bar returns. Rows are
    regime labels (undefined excluded); columns: n_bars, total_return,
    mean_return, std_return, sharpe."""
    returns = equity.pct_change().dropna()
    aligned = pd.concat([returns.rename("r"), labels.rename("label")], axis=1, join="inner")
    aligned = aligned.dropna()
    aligned = aligned[aligned["label"] != UNDEFINED]
    rows = {}
    for label, group in aligned.groupby("label", sort=True):
        r = group["r"]
        std = r.std(ddof=1)
        sharpe = float(r.mean() / std * np.sqrt(periods_per_year)) if std and std > 0 else 0.0
        rows[label] = {
            "n_bars": int(len(r)),
            "total_return": float((1.0 + r).prod() - 1.0),
            "mean_return": float(r.mean()),
            "std_return": float(std) if std == std else 0.0,
            "sharpe": sharpe,
        }
    return pd.DataFrame(rows).T.sort_index()
