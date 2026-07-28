"""Technical indicators — vectorized, pure pandas, independently tested.

Conventions (fixtures depend on these; change together or not at all):
- Input is a pd.Series aligned to bar order; output aligns 1:1 to input.
- WARM-UP: every indicator emits NaN until it has a full window. The
  first defined value's index is stated per function below. NaN is the
  honest answer during warm-up — never a partial-window estimate.
- NO FUTURE LEAKAGE: value at index i uses rows [0..i] only. Enforced by
  a prefix-equality property test (indicator(prefix)[i] == indicator(full)[i]).
- EMA family seeds with the SMA of the first n values (classic Wilder /
  charting convention): defined from index n-1.
- RSI/ATR use Wilder smoothing: seed = simple mean of the first n
  changes/true-ranges, then s_t = (s_{t-1}*(n-1) + x_t) / n.
  RSI first defined at index n (needs n price CHANGES).
  ATR first defined at index n (bar 0 has no previous close; TR starts
  at index 1; seed averages TR[1..n]).
- Bollinger uses POPULATION std (ddof=0), matching common charting
  platforms; rolling_std exposes ddof explicitly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    """Simple moving average. First defined at index n-1."""
    return s.rolling(n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    """Exponential MA, alpha = 2/(n+1), seeded with SMA of first n values.
    First defined at index n-1."""
    if len(s) < n:
        return pd.Series(np.nan, index=s.index)
    alpha = 2.0 / (n + 1.0)
    out = np.full(len(s), np.nan)
    values = s.to_numpy(dtype=float)
    out[n - 1] = values[:n].mean()
    for i in range(n, len(values)):
        out[i] = out[i - 1] + alpha * (values[i] - out[i - 1])
    return pd.Series(out, index=s.index)


def rsi(s: pd.Series, n: int) -> pd.Series:
    """Wilder RSI. First defined at index n."""
    delta = s.diff()
    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)
    avg_gain = _wilder(gains.iloc[1:], n)
    avg_loss = _wilder(losses.iloc[1:], n)
    out = pd.Series(np.nan, index=s.index)
    ag = avg_gain.reindex(s.index)
    al = avg_loss.reindex(s.index)
    both = ag.notna() & al.notna()
    zero_loss = both & (al == 0.0)
    normal = both & (al > 0.0)
    out[normal] = 100.0 - 100.0 / (1.0 + ag[normal] / al[normal])
    out[zero_loss] = 100.0
    return out


def _wilder(x: pd.Series, n: int) -> pd.Series:
    """Wilder smoothing over x: seed = mean of first n, then recursive."""
    values = x.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    if len(values) >= n:
        out[n - 1] = values[:n].mean()
        for i in range(n, len(values)):
            out[i] = (out[i - 1] * (n - 1) + values[i]) / n
    return pd.Series(out, index=x.index)


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """TR = max(h-l, |h-prev_close|, |l-prev_close|). NaN at index 0."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    tr.iloc[0] = np.nan
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int) -> pd.Series:
    """Wilder ATR over true range. First defined at index n."""
    tr = true_range(high, low, close)
    return _wilder(tr.iloc[1:], n).reindex(close.index)


def macd(
    s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """Returns columns macd, signal, hist. macd defined from index slow-1;
    signal seeds on the first `signal` defined macd values."""
    line = ema(s, fast) - ema(s, slow)
    valid = line.dropna()
    sig = ema(valid, signal).reindex(s.index)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def rolling_std(s: pd.Series, n: int, ddof: int = 0) -> pd.Series:
    """First defined at index n-1. ddof=0 (population) by default."""
    return s.rolling(n).std(ddof=ddof)


def rolling_max(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).max()


def rolling_min(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).min()


def roc(s: pd.Series, n: int) -> pd.Series:
    """Rate of change: s / s.shift(n) - 1. First defined at index n."""
    return s / s.shift(n) - 1.0


def bollinger(s: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    """Columns mid, upper, lower. Population std. Defined from index n-1."""
    mid = sma(s, n)
    sd = rolling_std(s, n, ddof=0)
    return pd.DataFrame({"mid": mid, "upper": mid + k * sd, "lower": mid - k * sd})
