"""Research report: structure, confidence rubric, reproducibility,
measured-vs-interpretation separation."""
import pytest

from engine.validation.overfitting import ValidationWarning
from engine.validation.report import (
    DISCLAIMER,
    build_report,
    confidence_assessment,
    to_markdown,
)


def w(code, severity):
    return ValidationWarning(code=code, severity=severity, message="m", evidence={})


GOOD_WF = {
    "n_folds": 4,
    "sharpe_mean": 1.2,
    "fraction_positive_objective": 1.0,
}


# ── confidence rubric: every branch fixtured ──────────────────────────
def test_confidence_insufficient_on_critical_warning():
    level, rationale = confidence_assessment(GOOD_WF, 0.5, [w("few_trades", "critical")])
    assert level == "insufficient"
    assert "critical" in rationale[0]


def test_confidence_insufficient_on_too_few_folds():
    level, _ = confidence_assessment({"n_folds": 1, "sharpe_mean": 2.0}, 0.5, [])
    assert level == "insufficient"


def test_confidence_weak_on_nonpositive_oos():
    level, _ = confidence_assessment(
        {"n_folds": 4, "sharpe_mean": -0.2, "fraction_positive_objective": 0.25},
        0.5, [])
    assert level == "weak"


def test_confidence_weak_on_low_fold_hit_rate():
    level, _ = confidence_assessment(
        {"n_folds": 4, "sharpe_mean": 0.3, "fraction_positive_objective": 0.25},
        0.5, [])
    assert level == "weak"


def test_confidence_moderate_when_mc_lower_ci_nonpositive():
    level, rationale = confidence_assessment(GOOD_WF, -0.1, [])
    assert level == "moderate"
    assert any("Monte Carlo" in r for r in rationale)


def test_confidence_moderate_with_noncritical_warnings():
    level, _ = confidence_assessment(GOOD_WF, 0.5, [w("narrow_peak", "warning")])
    assert level == "moderate"


def test_confidence_strong_requires_everything():
    level, _ = confidence_assessment(GOOD_WF, 0.5, [])
    assert level == "strong"
    # 60% folds positive -> not strong even with no warnings
    level2, _ = confidence_assessment(
        {"n_folds": 5, "sharpe_mean": 0.8, "fraction_positive_objective": 0.6},
        0.5, [])
    assert level2 == "moderate"


# ── report assembly ───────────────────────────────────────────────────
def make_report(warnings=None):
    return build_report(
        strategy_name="MACrossover",
        strategy_description="verification example",
        parameters={"fast": 2, "slow": 5},
        dataset_fingerprint="f" * 64,
        optimization_summary={"n_evals": 9, "best_score": 1.1},
        walkforward_aggregate=GOOD_WF,
        validation_summary={"consistency_std": 0.2},
        regime_table={"bull": {"sharpe": 1.4}},
        mc_cis={"reshuffle": {"sharpe": {"q0.025": 0.4, "q0.5": 1.0, "q0.975": 1.6}}},
        sensitivity={"robustness_score": 0.8},
        warnings=warnings or [],
    )


def test_report_contains_all_sections():
    report = make_report()
    d = report.to_dict()
    assert d["strategy_name"] == "MACrossover"
    assert d["dataset_fingerprint"] == "f" * 64
    for section in [
        "optimization_summary", "walkforward_summary", "validation_summary",
        "regime_analysis", "monte_carlo_confidence_intervals",
        "sensitivity_analysis", "final_test",
    ]:
        assert section in d["measured"]
    assert d["interpretation"]["confidence"]["level"] == "strong"
    assert d["disclaimer"] == DISCLAIMER


def test_report_separates_measured_from_interpretation():
    d = make_report(warnings=[w("narrow_peak", "warning")]).to_dict()
    # warnings and confidence live ONLY under interpretation
    assert "warnings" in d["interpretation"]
    assert "confidence" in d["interpretation"]
    assert "warnings" not in d["measured"]
    assert "confidence" not in d["measured"]
    # measured contains numbers, not judgments
    assert d["measured"]["sensitivity_analysis"] == {"robustness_score": 0.8}


def test_mc_lower_ci_feeds_confidence():
    report = build_report(
        strategy_name="S", strategy_description="d", parameters={},
        dataset_fingerprint="x",
        walkforward_aggregate=GOOD_WF,
        mc_cis={"reshuffle": {"sharpe": {"q0.025": -0.3, "q0.5": 0.6, "q0.975": 1.2}}},
    )
    assert report.interpretation["confidence"]["level"] == "moderate"


def test_markdown_rendering():
    md = to_markdown(make_report(warnings=[w("few_trades", "warning")]))
    assert "# Research report: MACrossover" in md
    assert "## MEASURED" in md
    assert "## INTERPRETATION" in md
    assert "not measurement" in md
    assert "few_trades" in md
    assert "No claim of future profitability" in md
    assert "`" + "f" * 64 + "`" in md


def test_report_reproducible_except_timestamp():
    r1, r2 = make_report(), make_report()
    d1, d2 = r1.to_dict(), r2.to_dict()
    d1.pop("generated_at"), d2.pop("generated_at")
    assert d1 == d2
