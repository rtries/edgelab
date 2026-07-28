"""Continuous research — the nightly job.

Generate hypotheses -> skip anything already tested -> run each through
full validation -> tally results -> write the morning report (JSON +
markdown). Also folds in deployment health/drift alerts and current
regimes so the morning report is one stop, per the mission brief.

Failures in one hypothesis never abort the batch — each run is wrapped
and recorded as an error entry, and the report says so explicitly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from engine.data.store import ParquetStore

from ops.assistant import (
    filter_novel,
    generate_hypotheses,
    load_tested,
    mark_tested,
    run_hypothesis,
)
from ops.deployments import Deployment, DeploymentStore
from ops.drift import detect_drift, health_status
from ops.health import expectation_from_experiment, observed_metrics


@dataclass(slots=True)
class NightlyResult:
    date: str
    tallies: dict
    tested: list[dict]
    skipped_novelty: int
    errors: list[dict]
    deployment_alerts: list[dict]

    def to_dict(self) -> dict:
        return {
            "date": self.date, "tallies": self.tallies,
            "tested": self.tested, "skipped_novelty": self.skipped_novelty,
            "errors": self.errors,
            "deployment_alerts": self.deployment_alerts,
        }


def run_nightly(
    store: ParquetStore,
    symbols: list[str],
    registry_path: Path,
    tested_index_path: Path,
    budget: int = 20,
    seed: int | None = None,
) -> NightlyResult:
    seed = seed if seed is not None else int(datetime.now(UTC).timestamp())
    tested = load_tested(tested_index_path)
    hypotheses = generate_hypotheses(store, symbols, seed=seed)
    novel, skipped = filter_novel(hypotheses, tested)
    batch = novel[:budget]

    tallies = {"tested": 0, "rejected": 0, "needs_more_data": 0, "passed": 0}
    results, errors = [], []
    newly_tested = set(tested)
    for hypothesis in batch:
        try:
            result = run_hypothesis(hypothesis, store, registry_path, seed=seed)
        except Exception as exc:  # noqa: BLE001 — one bad hypothesis can't sink the batch
            errors.append({"hypothesis_id": hypothesis.id,
                           "strategy": hypothesis.strategy,
                           "symbols": hypothesis.symbols,
                           "error": str(exc)})
            newly_tested.add(hypothesis.fingerprint)
            continue
        results.append(result)
        tallies["tested"] += 1
        tallies[result["classification"]] += 1
        newly_tested.add(hypothesis.fingerprint)
    mark_tested(tested_index_path, newly_tested)

    return NightlyResult(
        date=datetime.now(UTC).date().isoformat(),
        tallies=tallies,
        tested=results,
        skipped_novelty=len(skipped),
        errors=errors,
        deployment_alerts=[],
    )


def deployment_alerts(
    deployment_store: DeploymentStore,
    experiments_by_id: dict[str, dict],
    ledgers_by_deployment: dict[str, tuple],   # id -> (ledger, bars_seen, live_pnls, regime)
) -> list[dict]:
    """Runs drift detection for every paper/live deployment that has an
    associated live ledger. Deployments with no live activity yet are
    skipped (nothing to compare)."""
    alerts = []
    for row in deployment_store.list():
        if row["status"] not in ("paper", "live"):
            continue
        dep_id = row["id"]
        if dep_id not in ledgers_by_deployment:
            continue
        exp = experiments_by_id.get(row["experiment_id"])
        if exp is None:
            continue
        ledger, bars_seen, live_pnls, regime = ledgers_by_deployment[dep_id]
        observed = observed_metrics(ledger, bars_seen)
        triggers = detect_drift(exp, observed, live_pnls,
                                current_regime=regime)
        status = health_status(triggers)
        if status != "healthy":
            alerts.append({
                "deployment_id": dep_id,
                "strategy": row["strategy"],
                "status": status,
                "triggers": [t.to_dict() for t in triggers],
            })
    return alerts


def write_report(result: NightlyResult, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{result.date}.json"
    json_path.write_text(json.dumps(result.to_dict(), indent=1))

    lines = [
        f"# Morning Research Report — {result.date}", "",
        "## Ideas Tested", "",
        f"- Tested: {result.tallies['tested']}",
        f"- Rejected: {result.tallies['rejected']}",
        f"- Need More Data: {result.tallies['needs_more_data']}",
        f"- Passed Validation: {result.tallies['passed']}",
        f"- Skipped (already tested): {result.skipped_novelty}",
        f"- Errors: {len(result.errors)}", "",
    ]
    passed = [t for t in result.tested if t["classification"] == "passed"]
    if passed:
        lines += ["## Passed Validation", ""]
        for t in passed:
            h = t["hypothesis"]
            lines.append(
                f"- **{h['strategy']}** on {', '.join(h['symbols'])} — "
                f"confidence: {t['confidence']}, sharpe: "
                f"{t['headline']['sharpe']:.2f}, experiment `{t['experiment_id']}`"
            )
        lines.append("")
    if result.deployment_alerts:
        lines += ["## Deployment Health Alerts", ""]
        for a in result.deployment_alerts:
            codes = ", ".join(tr["code"] for tr in a["triggers"])
            lines.append(f"- `{a['deployment_id']}` ({a['strategy']}): "
                         f"{a['status']} — {codes}")
        lines.append("")
    if result.errors:
        lines += ["## Errors", ""]
        for e in result.errors:
            lines.append(f"- {e['strategy']} on {e['symbols']}: {e['error']}")
        lines.append("")
    lines.append(
        "_EdgeLab cannot predict future prices. This report estimates "
        "whether current conditions resemble previously validated "
        "historical conditions. Strategies remain hypotheses under "
        "continuous testing._"
    )
    md_path = out_dir / f"{result.date}.md"
    md_path.write_text("\n".join(lines))
    return json_path, md_path
