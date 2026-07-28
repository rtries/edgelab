"""Deployment health + edge drift: observed metrics from a constructed
ledger, MC bands as acceptance ranges, every trigger firing and silent,
hand-checkable KS statistic, and the never-auto-disable guarantee."""
import copy
import dataclasses
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from engine.types import Fill, Side
from ops.deployments import deployment_from_experiment, flag_for_review
from ops.drift import (
    KS_THRESHOLD,
    detect_drift,
    health_status,
    ks_statistic,
)
from ops.execution import Ledger
from ops.health import (
    expectation_from_experiment,
    health_table,
    observed_metrics,
    observed_slippage_bps,
)

from tests.ops_fixtures import ops_env  # noqa: F401

TS = datetime(2026, 1, 5, 21, 0, tzinfo=UTC)


def ledger_with_trades(pnls: list[float], price=100.0) -> Ledger:
    """Builds a ledger whose round trips net (approximately) the given
    P&Ls via long 10-share episodes with zero fees."""
    ledger = Ledger(initial_cash=100_000)
    ts = TS
    for i, pnl in enumerate(pnls):
        entry, exit_price = price, price + pnl / 10.0
        ledger.apply_fill(Fill(order_id=2 * i, symbol="DEMO", side=Side.BUY,
                               qty=10, price=entry, fees=0.0, ts=ts))
        ledger.mark("DEMO", entry, ts)
        ts += timedelta(days=1)
        ledger.apply_fill(Fill(order_id=2 * i + 1, symbol="DEMO",
                               side=Side.SELL, qty=10, price=exit_price,
                               fees=0.0, ts=ts))
        ledger.mark("DEMO", exit_price, ts)
        ts += timedelta(days=1)
    return ledger


def test_observed_metrics_hand_checked():
    ledger = ledger_with_trades([50.0, -20.0, 30.0, -10.0])
    m = observed_metrics(ledger, bars_seen=40)
    assert m["n_trades"] == 4
    assert m["win_rate"] == 0.5
    assert m["profit_factor"] == pytest.approx(80.0 / 30.0)
    assert m["expectancy"] == pytest.approx(12.5)
    assert m["trade_frequency"] == pytest.approx(4 / 40)
    assert m["avg_holding_bars"] == pytest.approx(1.0)
    assert "sharpe" in m and "max_drawdown" in m
    assert m["max_drawdown"] <= 0


def test_observed_slippage_direction_aware():
    ledger = Ledger(initial_cash=1000)
    records = [
        {"kind": "fill", "side": "buy", "price": 100.1, "decision_price": 100.0},
        {"kind": "fill", "side": "sell", "price": 99.9, "decision_price": 100.0},
    ]
    slip = observed_slippage_bps(ledger, records)
    # both fills are 10bps adverse -> mean 10bps
    assert slip == pytest.approx(10.0, rel=1e-6)


def test_expectation_extraction(ops_env):
    exp = ops_env["experiment"]
    expectation = expectation_from_experiment(exp)
    assert expectation["sharpe"]["point"] == exp["development"]["metrics"]["sharpe"]
    lo, hi = expectation["sharpe"]["band"]
    assert lo is not None and hi is not None and lo <= hi


def test_health_table_bands(ops_env):
    exp = ops_env["experiment"]
    ledger = ledger_with_trades([50.0, -20.0, 30.0, -10.0, 5.0])
    rows = health_table(exp, ledger, bars_seen=50,
                        fill_records=[{"kind": "fill", "side": "buy",
                                       "price": 100.05,
                                       "decision_price": 100.0}])
    by_metric = {r.metric: r for r in rows}
    assert set(by_metric) >= {"sharpe", "max_drawdown", "win_rate",
                              "slippage_bps"}
    sharpe_row = by_metric["sharpe"]
    assert sharpe_row.n_observations == 5
    assert sharpe_row.within_band in (True, False)   # band exists -> judged
    assert by_metric["slippage_bps"].observed == pytest.approx(5.0)


# ── KS statistic ──────────────────────────────────────────────────────
def test_ks_identical_and_disjoint():
    assert ks_statistic([1, 2, 3, 4], [1, 2, 3, 4]) == 0.0
    assert ks_statistic([1, 2, 3, 4], [10, 11, 12, 13]) == 1.0
    mixed = ks_statistic([1, 2, 3, 4], [3, 4, 5, 6])
    assert 0.0 < mixed < 1.0


# ── drift triggers, one by one ────────────────────────────────────────
def clean_observed(exp):
    dev = exp["development"]["metrics"]
    n_bars = len(exp["development"]["equity"])
    return {
        "n_trades": 20,
        "win_rate": dev["win_rate"],
        "trade_frequency": (dev["n_trades"] or 1) / max(n_bars, 1),
        "max_drawdown": -0.001,
    }


def test_no_drift_on_matching_behavior(ops_env):
    exp = ops_env["experiment"]
    triggers = detect_drift(exp, clean_observed(exp),
                            live_pnls=exp["development"]["trade_pnls"])
    codes = {t.code for t in triggers}
    assert "frequency_shift" not in codes
    assert "distribution_change" not in codes
    assert "win_rate_collapse" not in codes
    assert "drawdown_breach" not in codes
    assert health_status([]) == "healthy"


def test_slippage_excess_trigger(ops_env):
    exp = ops_env["experiment"]
    triggers = detect_drift(exp, clean_observed(exp), live_pnls=[],
                            observed_slippage=5.0, modeled_slippage_bps=1.0)
    assert any(t.code == "slippage_excess" for t in triggers)
    silent = detect_drift(exp, clean_observed(exp), live_pnls=[],
                          observed_slippage=1.5, modeled_slippage_bps=1.0)
    assert not any(t.code == "slippage_excess" for t in silent)


def test_frequency_shift_trigger(ops_env):
    exp = ops_env["experiment"]
    observed = clean_observed(exp)
    observed["trade_frequency"] *= 5.0
    triggers = detect_drift(exp, observed, live_pnls=[])
    trig = next(t for t in triggers if t.code == "frequency_shift")
    assert trig.evidence["ratio"] == pytest.approx(5.0)


def test_distribution_change_trigger(ops_env):
    exp = ops_env["experiment"]
    research = exp["development"]["trade_pnls"]
    shifted = [p + 10 * (max(research) - min(research) + 1) for p in research]
    triggers = detect_drift(exp, clean_observed(exp), live_pnls=shifted)
    trig = next(t for t in triggers if t.code == "distribution_change")
    assert trig.evidence["ks"] > KS_THRESHOLD


def test_win_rate_collapse_trigger(ops_env):
    exp = ops_env["experiment"]
    observed = clean_observed(exp)
    observed["win_rate"] = 0.0
    observed["n_trades"] = 30
    triggers = detect_drift(exp, observed, live_pnls=[])
    assert any(t.code == "win_rate_collapse" for t in triggers)


def test_drawdown_breach_is_critical(ops_env):
    exp = ops_env["experiment"]
    observed = clean_observed(exp)
    observed["max_drawdown"] = -0.99
    triggers = detect_drift(exp, observed, live_pnls=[])
    trig = next(t for t in triggers if t.code == "drawdown_breach")
    assert trig.severity == "critical"
    assert health_status(triggers) == "retire_recommended"


def test_regime_shift_trigger(ops_env):
    exp = copy.deepcopy(ops_env["experiment"])
    regimes = exp.get("regimes", {}).get("trend_regime", {})
    if not regimes:
        pytest.skip("fixture experiment produced no regime table")
    name = next(iter(regimes))
    regimes[name]["sharpe"] = -1.0
    triggers = detect_drift(exp, clean_observed(exp), live_pnls=[],
                            current_regime=name)
    assert any(t.code == "regime_shift" for t in triggers)


def test_status_ladder(ops_env):
    exp = ops_env["experiment"]
    base = clean_observed(exp)
    one = dict(base); one["trade_frequency"] *= 5
    triggers = detect_drift(exp, one, live_pnls=[])
    assert health_status(triggers) == "weakening"
    two = dict(one); two["win_rate"] = 0.0; two["n_trades"] = 30
    triggers = detect_drift(exp, two, live_pnls=[])
    assert health_status(triggers) == "unstable"


def test_drift_flags_review_never_disables(ops_env):
    exp = ops_env["experiment"]
    dep = deployment_from_experiment(exp)
    dep = dataclasses.replace(dep, confidence="strong", id="")
    from ops.deployments import transition
    transition(dep, "paper", "validated")
    observed = clean_observed(exp)
    observed["max_drawdown"] = -0.99
    triggers = detect_drift(exp, observed, live_pnls=[])
    flag_for_review(dep, [t.to_dict() for t in triggers])
    assert dep.status == "paper"               # STILL TRADING PAPER
    assert dep.review_required
    assert any(e["code"] == "drawdown_breach" for e in dep.review_evidence)
