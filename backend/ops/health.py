"""Deployment health: research expectation vs paper vs live, on the same
metrics, with research Monte Carlo intervals as the acceptance bands.

The comparison is honest about sample size: observed metrics from a
handful of trades carry wide uncertainty, and every row says how many
observations it rests on. Health never proves an edge — it can only fail
to reject one so far.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from engine.types import RoundTrip

from ops.execution import Ledger


@dataclass(frozen=True, slots=True)
class HealthRow:
    metric: str
    expected: float | None            # research point estimate
    band: tuple[float | None, float | None]   # research MC q2.5 / q97.5
    observed: float | None
    n_observations: int
    within_band: bool | None          # None when band or observation missing

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "expected": self.expected,
            "band": list(self.band),
            "observed": self.observed,
            "n_observations": self.n_observations,
            "within_band": self.within_band,
        }


def observed_metrics(ledger: Ledger, bars_seen: int) -> dict:
    """Live-side measurements from round trips + equity marks."""
    trips = ledger.round_trips
    pnls = np.array([t.net_pnl for t in trips], dtype=float)
    out: dict = {"n_trades": len(trips), "bars_seen": bars_seen}
    if len(trips) == 0:
        return out
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    out["win_rate"] = float((pnls > 0).mean())
    out["profit_factor"] = (
        float(wins.sum() / abs(losses.sum())) if losses.sum() != 0
        else float("inf") if wins.sum() > 0 else 0.0
    )
    out["expectancy"] = float(pnls.mean())
    out["trade_frequency"] = len(trips) / max(bars_seen, 1)
    out["avg_holding_bars"] = float(np.mean([
        max((t.exit_ts - t.entry_ts).days, 1) for t in trips
    ]))
    if len(ledger.equity_points) >= 2:
        equity = np.array([v for _, v in ledger.equity_points])
        returns = np.diff(equity) / equity[:-1]
        std = returns.std(ddof=1) if len(returns) > 1 else 0.0
        out["sharpe"] = (
            float(returns.mean() / std * math.sqrt(252)) if std > 0 else 0.0
        )
        cummax = np.maximum.accumulate(equity)
        out["max_drawdown"] = float((equity / cummax - 1.0).min())
    return out


def observed_slippage_bps(ledger: Ledger, fill_records: list[dict]) -> float | None:
    """Realized slippage: fill price vs the decision close recorded in
    each fill log line, in bps, direction-aware."""
    samples = []
    for record in fill_records:
        decision = record.get("decision_price")
        if not decision:
            continue
        sign = 1 if record["side"] == "buy" else -1
        samples.append(sign * (record["price"] - decision) / decision * 1e4)
    return float(np.mean(samples)) if samples else None


def expectation_from_experiment(exp: dict) -> dict:
    """Research point estimates + MC bands, per metric."""
    dev = exp["development"]["metrics"]
    n_dev_bars = len(exp["development"]["equity"])
    cis = exp.get("montecarlo", {}).get("cis", {})

    def band(metric: str) -> tuple[float | None, float | None]:
        lows, highs = [], []
        for method in ("reshuffle", "bootstrap"):
            block = cis.get(method, {}).get(metric, {})
            if block.get("q0.025") is not None:
                lows.append(block["q0.025"])
            if block.get("q0.975") is not None:
                highs.append(block["q0.975"])
        return (min(lows) if lows else None, max(highs) if highs else None)

    return {
        "win_rate": {"point": dev.get("win_rate"), "band": (None, None)},
        "profit_factor": {"point": dev.get("profit_factor"),
                          "band": band("profit_factor")},
        "sharpe": {"point": dev.get("sharpe"), "band": band("sharpe")},
        "max_drawdown": {"point": dev.get("max_drawdown"),
                         "band": band("max_drawdown")},
        "expectancy": {"point": dev.get("expectancy"),
                       "band": band("expectancy")},
        "trade_frequency": {
            "point": (dev.get("n_trades") or 0) / max(n_dev_bars, 1),
            "band": (None, None),
        },
        "exposure": {"point": dev.get("exposure"), "band": (None, None)},
        "modeled_slippage_bps": {"point": None, "band": (None, None)},
    }


def health_table(
    exp: dict,
    ledger: Ledger,
    bars_seen: int,
    fill_records: list[dict] | None = None,
) -> list[HealthRow]:
    expectation = expectation_from_experiment(exp)
    observed = observed_metrics(ledger, bars_seen)
    n = observed.get("n_trades", 0)
    rows: list[HealthRow] = []
    for metric in ("sharpe", "max_drawdown", "profit_factor", "win_rate",
                   "expectancy", "trade_frequency"):
        expect = expectation.get(metric, {})
        obs = observed.get(metric)
        lo, hi = expect.get("band", (None, None))
        within = None
        if obs is not None and lo is not None and hi is not None:
            within = lo <= obs <= hi
        rows.append(HealthRow(
            metric=metric,
            expected=expect.get("point"),
            band=(lo, hi),
            observed=obs,
            n_observations=n if metric != "max_drawdown" else len(ledger.equity_points),
            within_band=within,
        ))
    if fill_records:
        slip = observed_slippage_bps(ledger, fill_records)
        rows.append(HealthRow(
            metric="slippage_bps", expected=None, band=(None, None),
            observed=slip,
            n_observations=len([r for r in fill_records if r.get("decision_price")]),
            within_band=None,
        ))
    return rows
