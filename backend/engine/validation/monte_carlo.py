"""Monte Carlo robustness tests (Phase 2).

- Trade-order reshuffling: distribution of drawdowns under permuted trade
  sequences (drawdown you saw is one draw, not the worst case).
- Bootstrap resampling of returns with confidence intervals on Sharpe/CAGR.
- Skip-trade simulation: randomly drop N% of trades; edges that need every
  trade are not edges.

All samplers take an explicit numpy Generator seed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def reshuffle_drawdowns(
    trade_pnls: pd.Series, n_sims: int = 5_000, seed: int = 42
) -> np.ndarray:
    raise NotImplementedError


def bootstrap_sharpe_ci(
    returns: pd.Series, n_sims: int = 5_000, ci: float = 0.95, seed: int = 42
) -> tuple[float, float]:
    raise NotImplementedError
