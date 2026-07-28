"""Structured research report.

The report separates two things that must never blur:
- MEASURED: numbers computed from data by pinned definitions.
- INTERPRETATION: heuristic reading of those numbers (warnings,
  confidence level). Explicitly labeled as interpretation.

The confidence rubric is a deterministic function (fixtured) of the
walk-forward aggregate, Monte Carlo CIs, and warnings:

    insufficient  any critical warning, or < 2 validation folds
    weak          mean validation objective <= 0, or < 50% of folds
                  positive
    moderate      positive OOS but MC lower CI of sharpe <= 0, or any
                  warnings present
    strong        >= 75% folds positive, MC lower CI > 0, no warnings

"strong" means "the evidence gathered here did not kill the strategy" —
nothing more. The report never claims future profitability, and says so.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

DISCLAIMER = (
    "All statistics are measurements of historical simulation under the "
    "stated assumptions. They are not predictions. No claim of future "
    "profitability is made or implied; a strategy surviving these tests "
    "has merely not yet been shown to be luck."
)

LEVELS = ["insufficient", "weak", "moderate", "strong"]


def confidence_assessment(
    wf_aggregate: dict,
    mc_sharpe_lower: float | None,
    warnings: list,
) -> tuple[str, list[str]]:
    """Returns (level, rationale lines). Deterministic."""
    rationale: list[str] = []
    n_folds = int(wf_aggregate.get("n_folds", 0))
    mean_obj = wf_aggregate.get("sharpe_mean")
    frac_pos = wf_aggregate.get("fraction_positive_objective")

    has_critical = any(w.severity == "critical" for w in warnings)
    if has_critical:
        rationale.append("critical warnings present")
        return "insufficient", rationale
    if n_folds < 2:
        rationale.append(f"only {n_folds} validation fold(s)")
        return "insufficient", rationale

    if mean_obj is not None and mean_obj <= 0:
        rationale.append(f"mean validation sharpe {mean_obj:.2f} <= 0")
        return "weak", rationale
    if frac_pos is not None and frac_pos < 0.5:
        rationale.append(f"only {frac_pos:.0%} of folds positive")
        return "weak", rationale

    caps: list[str] = []
    if mc_sharpe_lower is not None and mc_sharpe_lower <= 0:
        caps.append(f"Monte Carlo sharpe lower CI {mc_sharpe_lower:.2f} <= 0")
    if warnings:
        caps.append(f"{len(warnings)} non-critical warning(s)")
    if caps:
        rationale.extend(caps)
        return "moderate", rationale

    if frac_pos is not None and frac_pos >= 0.75:
        rationale.append(
            f"{frac_pos:.0%} folds positive, MC lower CI > 0, no warnings"
        )
        return "strong", rationale
    rationale.append("positive but fold consistency below the strong bar (75%)")
    return "moderate", rationale


@dataclass(slots=True)
class ResearchReport:
    strategy_name: str
    strategy_description: str
    parameters: dict
    dataset_fingerprint: str
    measured: dict = field(default_factory=dict)      # numbers only
    interpretation: dict = field(default_factory=dict)  # warnings, confidence
    generated_at: str = ""

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "strategy_description": self.strategy_description,
            "parameters": self.parameters,
            "dataset_fingerprint": self.dataset_fingerprint,
            "measured": self.measured,
            "interpretation": self.interpretation,
            "disclaimer": DISCLAIMER,
            "generated_at": self.generated_at,
        }


def build_report(
    *,
    strategy_name: str,
    strategy_description: str,
    parameters: dict,
    dataset_fingerprint: str,
    optimization_summary: dict | None = None,
    walkforward_aggregate: dict | None = None,
    validation_summary: dict | None = None,
    regime_table: dict | None = None,
    mc_cis: dict | None = None,
    sensitivity: dict | None = None,
    warnings: list | None = None,
    final_test: dict | None = None,
) -> ResearchReport:
    warnings = warnings or []
    mc_sharpe_lower = None
    if mc_cis:
        for _method, ci in mc_cis.items():
            lower = ci.get("sharpe", {}).get("q0.025")
            if lower is not None:
                mc_sharpe_lower = lower if mc_sharpe_lower is None else min(mc_sharpe_lower, lower)
    level, rationale = confidence_assessment(
        walkforward_aggregate or {}, mc_sharpe_lower, warnings
    )
    measured = {
        "optimization_summary": optimization_summary or {},
        "walkforward_summary": walkforward_aggregate or {},
        "validation_summary": validation_summary or {},
        "regime_analysis": regime_table or {},
        "monte_carlo_confidence_intervals": mc_cis or {},
        "sensitivity_analysis": sensitivity or {},
        "final_test": final_test or {},
    }
    interpretation = {
        "warnings": [w.to_dict() for w in warnings],
        "confidence": {"level": level, "rationale": rationale},
        "note": (
            "Everything in this section is heuristic reading of the measured "
            "section, not additional measurement."
        ),
    }
    return ResearchReport(
        strategy_name=strategy_name,
        strategy_description=strategy_description,
        parameters=parameters,
        dataset_fingerprint=dataset_fingerprint,
        measured=measured,
        interpretation=interpretation,
    )


def to_markdown(report: ResearchReport) -> str:
    d = report.to_dict()
    lines = [
        f"# Research report: {d['strategy_name']}",
        "",
        f"*Generated {d['generated_at']}*",
        "",
        f"**Dataset fingerprint:** `{d['dataset_fingerprint']}`",
        "",
        "## Strategy",
        d["strategy_description"],
        "",
        "## Parameters",
        "```",
        "\n".join(f"{k} = {v}" for k, v in d["parameters"].items()),
        "```",
        "",
        "## MEASURED",
        "_Numbers computed from data by pinned definitions._",
        "",
    ]
    for section, content in d["measured"].items():
        lines.append(f"### {section.replace('_', ' ')}")
        if not content:
            lines.append("_not run_")
        else:
            lines.append("```")
            lines.extend(f"{k}: {v}" for k, v in content.items())
            lines.append("```")
        lines.append("")
    lines += [
        "## INTERPRETATION",
        "_Heuristic reading of the measured section — not measurement._",
        "",
        f"**Confidence:** {d['interpretation']['confidence']['level']}",
        "",
        "Rationale: " + "; ".join(d["interpretation"]["confidence"]["rationale"]),
        "",
        "### Warnings",
    ]
    if d["interpretation"]["warnings"]:
        for w in d["interpretation"]["warnings"]:
            lines.append(f"- **[{w['severity']}] {w['code']}** — {w['message']}")
    else:
        lines.append("- none raised (absence of warnings is not evidence of edge)")
    lines += ["", "## Disclaimer", d["disclaimer"], ""]
    return "\n".join(lines)
