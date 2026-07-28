"""Edge drift detection — the module that keeps deployments honest.

Every deployment gets a health status from deterministic triggers:

  slippage_excess        realized slippage > modeled × SLIPPAGE_MULT
  frequency_shift        observed trade frequency outside
                         [1/FREQ_RATIO, FREQ_RATIO] × research frequency
  distribution_change    two-sample KS statistic between research trade
                         P&Ls and live trade P&Ls above KS_THRESHOLD
                         (needs MIN_TRADES_FOR_KS on the live side)
  win_rate_collapse      observed win rate below research win rate minus
                         2·sqrt(p(1-p)/n) — a two-sigma binomial cushion
  drawdown_breach        observed max drawdown deeper than the research
                         Monte Carlo q2.5 drawdown (the modeled bad case)
  regime_shift           the current market regime had non-positive
                         research sharpe in the experiment's regime table

Status:  0 triggers -> healthy, 1 -> weakening, 2 -> unstable,
         >= 3 or any critical (drawdown_breach) -> retire_recommended.

These thresholds are pinned heuristics, documented here, and the module
NEVER disables anything. It produces evidence and sets review_required;
retirement is a recorded human/API transition. A strategy is a
hypothesis under continuous testing — this is the test.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SLIPPAGE_MULT = 2.0
FREQ_RATIO = 2.0
KS_THRESHOLD = 0.5
MIN_TRADES_FOR_KS = 8
WIN_RATE_SIGMAS = 2.0

CRITICAL_TRIGGERS = {"drawdown_breach"}

STATUS_ORDER = ["healthy", "weakening", "unstable", "retire_recommended"]


@dataclass(frozen=True, slots=True)
class DriftTrigger:
    code: str
    severity: str          # "warning" | "critical"
    message: str
    evidence: dict

    def to_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity,
                "message": self.message, "evidence": self.evidence}


def ks_statistic(a: list[float], b: list[float]) -> float:
    """Two-sample Kolmogorov–Smirnov statistic (no p-value — used as a
    pinned-threshold heuristic, stated as such)."""
    xs = np.sort(np.asarray(a, dtype=float))
    ys = np.sort(np.asarray(b, dtype=float))
    grid = np.concatenate([xs, ys])
    cdf_a = np.searchsorted(xs, grid, side="right") / len(xs)
    cdf_b = np.searchsorted(ys, grid, side="right") / len(ys)
    return float(np.max(np.abs(cdf_a - cdf_b)))


def detect_drift(
    exp: dict,
    observed: dict,
    live_pnls: list[float],
    observed_slippage: float | None = None,
    modeled_slippage_bps: float | None = None,
    current_regime: str | None = None,
) -> list[DriftTrigger]:
    triggers: list[DriftTrigger] = []
    dev = exp["development"]["metrics"]

    # slippage
    if (
        observed_slippage is not None
        and modeled_slippage_bps is not None
        and modeled_slippage_bps > 0
        and observed_slippage > SLIPPAGE_MULT * modeled_slippage_bps
    ):
        triggers.append(DriftTrigger(
            "slippage_excess", "warning",
            f"realized slippage {observed_slippage:.1f}bps exceeds "
            f"{SLIPPAGE_MULT}x the modeled {modeled_slippage_bps:.1f}bps",
            {"observed_bps": observed_slippage,
             "modeled_bps": modeled_slippage_bps},
        ))

    # trade frequency
    research_freq = (dev.get("n_trades") or 0) / max(
        len(exp["development"]["equity"]), 1)
    observed_freq = observed.get("trade_frequency")
    if observed_freq is not None and research_freq > 0:
        ratio = observed_freq / research_freq
        if ratio > FREQ_RATIO or ratio < 1 / FREQ_RATIO:
            triggers.append(DriftTrigger(
                "frequency_shift", "warning",
                f"trade frequency changed {ratio:.2f}x vs research",
                {"observed": observed_freq, "research": research_freq,
                 "ratio": ratio},
            ))

    # return distribution
    research_pnls = exp["development"].get("trade_pnls", [])
    if len(live_pnls) >= MIN_TRADES_FOR_KS and len(research_pnls) >= MIN_TRADES_FOR_KS:
        ks = ks_statistic(research_pnls, live_pnls)
        if ks > KS_THRESHOLD:
            triggers.append(DriftTrigger(
                "distribution_change", "warning",
                f"trade P&L distribution KS={ks:.2f} vs research "
                f"(threshold {KS_THRESHOLD})",
                {"ks": ks, "n_live": len(live_pnls),
                 "n_research": len(research_pnls)},
            ))

    # win rate
    p = dev.get("win_rate")
    observed_wr = observed.get("win_rate")
    n = observed.get("n_trades", 0)
    if p is not None and observed_wr is not None and n >= 5 and 0 < p < 1:
        cushion = WIN_RATE_SIGMAS * (p * (1 - p) / n) ** 0.5
        if observed_wr < p - cushion:
            triggers.append(DriftTrigger(
                "win_rate_collapse", "warning",
                f"win rate {observed_wr:.0%} below research {p:.0%} minus "
                f"{WIN_RATE_SIGMAS}σ cushion ({cushion:.0%})",
                {"observed": observed_wr, "research": p, "cushion": cushion,
                 "n": n},
            ))

    # drawdown vs the modeled bad case
    mc_dd = None
    for method in ("reshuffle", "bootstrap"):
        block = exp.get("montecarlo", {}).get("cis", {}).get(method, {})
        q = block.get("max_drawdown", {}).get("q0.025")
        if q is not None:
            mc_dd = q if mc_dd is None else min(mc_dd, q)
    observed_dd = observed.get("max_drawdown")
    if mc_dd is not None and observed_dd is not None and observed_dd < mc_dd:
        triggers.append(DriftTrigger(
            "drawdown_breach", "critical",
            f"drawdown {observed_dd:.1%} deeper than the research Monte "
            f"Carlo bad case {mc_dd:.1%}",
            {"observed": observed_dd, "mc_q025": mc_dd},
        ))

    # regime shift
    if current_regime:
        regime_table = exp.get("regimes", {}).get("trend_regime", {})
        row = regime_table.get(current_regime)
        if row is not None and row.get("sharpe", 0.0) <= 0:
            triggers.append(DriftTrigger(
                "regime_shift", "warning",
                f"current regime '{current_regime}' had research sharpe "
                f"{row.get('sharpe', 0):.2f} <= 0",
                {"regime": current_regime, "research_sharpe": row.get("sharpe")},
            ))

    return triggers


def health_status(triggers: list[DriftTrigger]) -> str:
    if any(t.severity == "critical" for t in triggers) or len(triggers) >= 3:
        return "retire_recommended"
    if len(triggers) == 2:
        return "unstable"
    if len(triggers) == 1:
        return "weakening"
    return "healthy"
