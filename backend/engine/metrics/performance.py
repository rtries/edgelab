"""Performance metrics. Pure functions: pandas in, numbers out.

Definitions are pinned here so fixtures can be hand-computed. If you change
a definition, the corresponding hand-calculated test MUST change with it.

- returns:        simple returns, equity.pct_change().dropna()
- sharpe:         mean(r) / std(r, ddof=1) * sqrt(periods_per_year)
- sortino:        mean(r) / downside * sqrt(periods_per_year), where
                  downside = sqrt(mean(min(r, 0)^2))  (full-sample mean)
- max_drawdown:   min(equity / cummax(equity) - 1)   (a negative number)
- cagr:           (end/start)^(periods_per_year / n_periods) - 1
- calmar:         cagr / |max_drawdown|
- ulcer_index:    sqrt(mean(drawdown_pct^2)), drawdown_pct in percent
- profit_factor:  gross wins / |gross losses|
- expectancy:     mean(net trade P&L)
- win_rate:       count(pnl > 0) / count(all)   (breakeven trades count
                  against you — they cost commissions)
- exposure:       mean of the per-bar in-market flag from the engine

Degenerate inputs return 0.0/inf explicitly rather than raising — see each
function. All are covered by edge-case tests.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def returns_from_equity(equity: pd.Series) -> pd.Series:
    return equity.pct_change().dropna()


def sharpe(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    if len(returns) < 2:
        return 0.0
    std = returns.std(ddof=1)
    if std == 0 or math.isnan(std):
        return 0.0
    return float(returns.mean() / std * math.sqrt(periods_per_year))


def sortino(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    if len(returns) < 2:
        return 0.0
    downside = float(np.sqrt(np.mean(np.square(np.minimum(returns.values, 0.0)))))
    mean = float(returns.mean())
    if downside == 0.0:
        return math.inf if mean > 0 else 0.0
    return mean / downside * math.sqrt(periods_per_year)


def max_drawdown(equity: pd.Series) -> float:
    if len(equity) == 0:
        return 0.0
    dd = equity / equity.cummax() - 1.0
    return float(dd.min())


def drawdown_series(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1.0


def cagr(equity: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    n_periods = len(equity) - 1
    return float((equity.iloc[-1] / equity.iloc[0]) ** (periods_per_year / n_periods) - 1.0)


def calmar(equity: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    mdd = max_drawdown(equity)
    if mdd == 0.0:
        return 0.0
    return cagr(equity, periods_per_year) / abs(mdd)


def ulcer_index(equity: pd.Series) -> float:
    if len(equity) == 0:
        return 0.0
    dd_pct = (equity / equity.cummax() - 1.0) * 100.0
    return float(np.sqrt(np.mean(np.square(dd_pct.values))))


def profit_factor(trade_pnls: pd.Series) -> float:
    wins = trade_pnls[trade_pnls > 0].sum()
    losses = abs(trade_pnls[trade_pnls < 0].sum())
    if losses == 0:
        return math.inf if wins > 0 else 0.0
    return float(wins / losses)


def expectancy(trade_pnls: pd.Series) -> float:
    if len(trade_pnls) == 0:
        return 0.0
    return float(trade_pnls.mean())


def win_rate(trade_pnls: pd.Series) -> float:
    if len(trade_pnls) == 0:
        return 0.0
    return float((trade_pnls > 0).sum() / len(trade_pnls))


def avg_win(trade_pnls: pd.Series) -> float:
    wins = trade_pnls[trade_pnls > 0]
    return float(wins.mean()) if len(wins) else 0.0


def avg_loss(trade_pnls: pd.Series) -> float:
    losses = trade_pnls[trade_pnls < 0]
    return float(losses.mean()) if len(losses) else 0.0


def exposure(exposure_flags: pd.Series) -> float:
    if len(exposure_flags) == 0:
        return 0.0
    return float(exposure_flags.mean())


def rolling_returns(equity: pd.Series, window: int) -> pd.Series:
    """Trailing simple return over `window` periods."""
    return equity.pct_change(periods=window).dropna()


def monthly_returns(equity: pd.Series) -> pd.Series:
    """Calendar-month returns from month-end equity values. The first
    month's return is measured from the first observation."""
    if len(equity) == 0:
        return pd.Series(dtype=float)
    month_end = equity.resample("ME").last()
    prior = month_end.shift(1)
    prior.iloc[0] = equity.iloc[0]
    return month_end / prior - 1.0


def full_report(
    equity: pd.Series,
    trade_pnls: pd.Series,
    exposure_flags: pd.Series | None = None,
    periods_per_year: int = TRADING_DAYS,
) -> dict[str, float]:
    r = returns_from_equity(equity)
    report = {
        "start_equity": float(equity.iloc[0]) if len(equity) else 0.0,
        "end_equity": float(equity.iloc[-1]) if len(equity) else 0.0,
        "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1.0)
        if len(equity) >= 2
        else 0.0,
        "cagr": cagr(equity, periods_per_year),
        "sharpe": sharpe(r, periods_per_year),
        "sortino": sortino(r, periods_per_year),
        "calmar": calmar(equity, periods_per_year),
        "max_drawdown": max_drawdown(equity),
        "ulcer_index": ulcer_index(equity),
        "profit_factor": profit_factor(trade_pnls),
        "expectancy": expectancy(trade_pnls),
        "win_rate": win_rate(trade_pnls),
        "avg_win": avg_win(trade_pnls),
        "avg_loss": avg_loss(trade_pnls),
        "n_trades": float(len(trade_pnls)),
    }
    if exposure_flags is not None:
        report["exposure"] = exposure(exposure_flags)
    return report
