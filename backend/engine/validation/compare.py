"""Multi-strategy comparison and ranked reports.

Ranking method (documented, direction-aware):
- Each RANKED metric gets rank 1..N (1 = best). Direction:
    higher better: sharpe, sortino, calmar, profit_factor, expectancy,
                   mc_sharpe_lower (Monte Carlo robustness)
    lower better:  ulcer_index, validation_consistency (std of fold
                   objectives), and max_drawdown ranked by |drawdown|
                   (closer to zero = better).
- overall_rank = mean of available metric ranks (missing metrics simply
  don't contribute for that strategy).
- n_trades and exposure are reported as CONTEXT, not ranked: more trades
  or more exposure is not intrinsically better.
Ties share the same (average) rank; final ordering ties break by name.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

HIGHER_BETTER = ["sharpe", "sortino", "calmar", "profit_factor", "expectancy",
                 "mc_sharpe_lower"]
LOWER_BETTER = ["ulcer_index", "validation_consistency"]
CONTEXT_ONLY = ["n_trades", "exposure"]


@dataclass(slots=True)
class StrategyRecord:
    name: str
    metrics: dict                      # from BacktestResult.metrics
    validation_consistency: float | None = None
    mc_sharpe_lower: float | None = None
    extra: dict = field(default_factory=dict)

    def row(self) -> dict:
        row = {"name": self.name, **self.metrics}
        if self.validation_consistency is not None:
            row["validation_consistency"] = self.validation_consistency
        if self.mc_sharpe_lower is not None:
            row["mc_sharpe_lower"] = self.mc_sharpe_lower
        row.update(self.extra)
        return row


def rank_strategies(records: list[StrategyRecord]) -> pd.DataFrame:
    if not records:
        raise ValueError("no strategies to compare")
    table = pd.DataFrame([r.row() for r in records]).set_index("name")

    rank_cols = {}
    for col in HIGHER_BETTER:
        if col in table.columns:
            rank_cols[f"rank_{col}"] = table[col].rank(ascending=False)
    for col in LOWER_BETTER:
        if col in table.columns:
            rank_cols[f"rank_{col}"] = table[col].rank(ascending=True)
    if "max_drawdown" in table.columns:
        rank_cols["rank_max_drawdown"] = table["max_drawdown"].abs().rank(ascending=True)

    ranks = pd.DataFrame(rank_cols, index=table.index)
    table = pd.concat([table, ranks], axis=1)
    table["overall_rank"] = ranks.mean(axis=1)
    return table.sort_values(["overall_rank", "name"], kind="stable")
