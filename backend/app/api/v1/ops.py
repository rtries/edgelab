"""Ops API — deployments, paper trading, monitoring, patterns, and
continuous research.

Filesystem-backed, mirroring research.py's conventions, and namespaced
per-user for a multi-tenant test: every deployment, paper log, pattern,
and the emergency stop itself live under
`EDGELAB_OPS_ROOT/{user_id}/...`. Two testers on the same server never
see each other's deployments, and one person's kill switch never
touches anyone else's trading.

Roots resolve from env at request time:
  EDGELAB_OPS_ROOT       (default backend/ops_data)
Reuses EDGELAB_RESEARCH_ROOT and EDGELAB_DATA_ROOT from research.py.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from engine.data.schema_types import Timeframe
from engine.data.store import ParquetStore
from ops.assistant import generate_hypotheses
from ops.deployments import (
    Deployment,
    DeploymentStore,
    RiskPolicy,
    TransitionError,
    deployment_from_experiment,
    transition,
)
from ops.drift import detect_drift, health_status
from ops.events import ReplayFeed
from ops.execution import EventLog, Ledger, PaperBroker
from ops.health import health_table, observed_metrics
from ops.loop import LiveLoop
from ops.nightly import run_nightly, write_report
from ops.patterns import PatternRecorder, PatternStore
from ops.similarity import find_similar

from app.api.v1.research import data_root, experiment_store, research_root
from app.core.auth import AuthUser, get_current_user

router = APIRouter()

CurrentUser = Depends(get_current_user)


def ops_root(user_id: str) -> Path:
    base = Path(os.environ.get("EDGELAB_OPS_ROOT", "ops_data"))
    return base / user_id


def deployment_store(user_id: str) -> DeploymentStore:
    return DeploymentStore(ops_root(user_id) / "deployments")


def pattern_store(user_id: str) -> PatternStore:
    return PatternStore(ops_root(user_id) / "patterns")


def _emergency_stop_path(user_id: str) -> Path:
    return ops_root(user_id) / "emergency_stop.flag"


def emergency_stop_active(user_id: str) -> bool:
    return _emergency_stop_path(user_id).exists()


def _get_deployment(user_id: str, dep_id: str) -> Deployment:
    try:
        return deployment_store(user_id).get(dep_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ── deployments ──────────────────────────────────────────────────────
class DeployRequest(BaseModel):
    experiment_id: str
    risk: dict | None = None
    session: str = "rth"


@router.post("/ops/deployments")
def create_deployment(req: DeployRequest, user: AuthUser = CurrentUser) -> dict:
    try:
        exp = experiment_store(user.id).get(req.experiment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    risk = RiskPolicy(**req.risk) if req.risk else RiskPolicy()
    dep = deployment_from_experiment(exp, risk=risk, session=req.session)
    deployment_store(user.id).save(dep)
    return dep.to_dict()


@router.get("/ops/deployments")
def list_deployments(user: AuthUser = CurrentUser) -> list[dict]:
    return deployment_store(user.id).list()


@router.get("/ops/deployments/{dep_id}")
def get_deployment(dep_id: str, user: AuthUser = CurrentUser) -> dict:
    return _get_deployment(user.id, dep_id).to_dict()


class TransitionRequest(BaseModel):
    to: str
    reason: str
    paper_evidence: dict | None = None


@router.post("/ops/deployments/{dep_id}/transition")
def transition_deployment(
    dep_id: str, req: TransitionRequest, user: AuthUser = CurrentUser
) -> dict:
    dep = _get_deployment(user.id, dep_id)
    try:
        transition(dep, req.to, req.reason, paper_evidence=req.paper_evidence)
    except TransitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    deployment_store(user.id).save(dep)
    return dep.to_dict()


# ── paper trading ────────────────────────────────────────────────────
class PaperRunRequest(BaseModel):
    start: str | None = None
    end: str | None = None
    checkpoint: bool = True


@router.post("/ops/deployments/{dep_id}/paper/run")
def run_paper_segment(
    dep_id: str, req: PaperRunRequest, user: AuthUser = CurrentUser
) -> dict:
    dep = _get_deployment(user.id, dep_id)
    if dep.status not in ("paper", "live"):
        raise HTTPException(
            status_code=422,
            detail=f"deployment status is '{dep.status}' — paper runs "
                   "require 'paper' or 'live'",
        )
    data_store = ParquetStore(data_root())
    start = datetime.fromisoformat(req.start) if req.start else None
    end = datetime.fromisoformat(req.end) if req.end else None
    feed = ReplayFeed(data_store, dep.symbols, Timeframe(dep.timeframe),
                      start=start, end=end)

    dep_ops_dir = ops_root(user.id) / "deployments" / dep_id
    ledger_path = dep_ops_dir / "ledger.json"
    log = EventLog(dep_ops_dir / "paper.jsonl", stream="paper")
    ckpt = dep_ops_dir / "checkpoint.json" if req.checkpoint else None
    stop_flag = lambda: emergency_stop_active(user.id)  # noqa: E731

    if ckpt is not None and ckpt.exists():
        loop = LiveLoop.resume(
            dep, feed, log, ckpt,
            pattern_recorder=PatternRecorder(pattern_store(user.id)),
            emergency_stop_flag=stop_flag,
        )
        summary = loop.run_resumed()
    else:
        ledger = Ledger(initial_cash=100_000.0)
        broker = PaperBroker(ledger, log)
        loop = LiveLoop(
            dep, feed, ledger, broker, log,
            pattern_recorder=PatternRecorder(pattern_store(user.id)),
            checkpoint_path=ckpt,
            emergency_stop_flag=stop_flag,
        )
        summary = loop.run()

    dep_ops_dir.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(summary["ledger"]))
    return summary


@router.get("/ops/deployments/{dep_id}/paper/logs")
def paper_logs(
    dep_id: str, limit: int = 200, user: AuthUser = CurrentUser
) -> list[dict]:
    log_path = ops_root(user.id) / "deployments" / dep_id / "paper.jsonl"
    log = EventLog(log_path, stream="paper")
    records = log.records()
    return records[-limit:]


# ── health & drift ───────────────────────────────────────────────────
def _load_ledger_and_bars(user_id: str, dep_id: str) -> tuple[Ledger, int, list[dict]]:
    log_path = ops_root(user_id) / "deployments" / dep_id / "paper.jsonl"
    log = EventLog(log_path, stream="paper")
    records = log.records()
    fill_records = [r for r in records if r["kind"] == "fill"]
    from engine.types import Fill, Side

    ledger = Ledger(initial_cash=100_000.0)
    for r in fill_records:
        ledger.apply_fill(Fill(
            order_id=r["order_id"], symbol=r["symbol"],
            side=Side(r["side"]), qty=r["qty"], price=r["price"],
            fees=r["fees"], ts=datetime.fromisoformat(r["ts"]),
        ))
        ledger.mark(r["symbol"], r["price"], datetime.fromisoformat(r["ts"]))
    bars_seen = len({r["ts"] for r in records if r["kind"] == "fill"})
    return ledger, bars_seen, fill_records


@router.get("/ops/deployments/{dep_id}/health")
def deployment_health(dep_id: str, user: AuthUser = CurrentUser) -> dict:
    dep = _get_deployment(user.id, dep_id)
    try:
        exp = experiment_store(user.id).get(dep.experiment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    ledger, bars_seen, fill_records = _load_ledger_and_bars(user.id, dep_id)
    rows = health_table(exp, ledger, bars_seen, fill_records)
    return {"deployment_id": dep_id, "rows": [r.to_dict() for r in rows]}


@router.get("/ops/deployments/{dep_id}/drift")
def deployment_drift(
    dep_id: str, regime: str | None = None, user: AuthUser = CurrentUser
) -> dict:
    dep = _get_deployment(user.id, dep_id)
    try:
        exp = experiment_store(user.id).get(dep.experiment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    ledger, bars_seen, fill_records = _load_ledger_and_bars(user.id, dep_id)
    observed = observed_metrics(ledger, bars_seen)
    live_pnls = [rt.net_pnl for rt in ledger.round_trips]
    triggers = detect_drift(exp, observed, live_pnls, current_regime=regime)
    status = health_status(triggers)
    return {
        "deployment_id": dep_id,
        "status": status,
        "triggers": [t.to_dict() for t in triggers],
    }


# ── emergency stop (per-user: your kill switch, your deployments) ────
@router.post("/ops/emergency-stop/on")
def emergency_stop_on(user: AuthUser = CurrentUser) -> dict:
    path = _emergency_stop_path(user.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.now(UTC).isoformat())
    return {"emergency_stop": True}


@router.post("/ops/emergency-stop/off")
def emergency_stop_off(user: AuthUser = CurrentUser) -> dict:
    path = _emergency_stop_path(user.id)
    if path.exists():
        path.unlink()
    return {"emergency_stop": False}


@router.get("/ops/emergency-stop")
def emergency_stop_status(user: AuthUser = CurrentUser) -> dict:
    return {"emergency_stop": emergency_stop_active(user.id)}


# ── patterns ─────────────────────────────────────────────────────────
@router.get("/ops/patterns")
def search_patterns(
    strategy: str | None = None,
    symbol: str | None = None,
    vol_regime: str | None = None,
    trend_regime: str | None = None,
    outcome: str | None = None,
    user: AuthUser = CurrentUser,
) -> list[dict]:
    records = pattern_store(user.id).search(
        strategy=strategy, symbol=symbol, vol_regime=vol_regime,
        trend_regime=trend_regime, outcome=outcome,
    )
    return [r.to_dict() for r in records]


class SimilarityRequest(BaseModel):
    features: dict
    k: int = 10


@router.post("/ops/patterns/similar")
def similar_patterns(req: SimilarityRequest, user: AuthUser = CurrentUser) -> dict:
    library = pattern_store(user.id).all()
    result = find_similar(library, req.features, k=req.k)
    return result.to_dict()


# ── continuous research ─────────────────────────────────────────────
class NightlyRequest(BaseModel):
    symbols: list[str] = Field(min_length=1)
    budget: int = 20
    seed: int | None = None


@router.post("/ops/research/nightly")
def trigger_nightly(req: NightlyRequest, user: AuthUser = CurrentUser) -> dict:
    store = ParquetStore(data_root())
    registry = research_root(user.id) / "registry.json"
    tested_index = ops_root(user.id) / "research" / "tested.json"
    result = run_nightly(store, req.symbols, registry, tested_index,
                         budget=req.budget, seed=req.seed)
    write_report(result, ops_root(user.id) / "research" / "reports")
    return result.to_dict()


@router.get("/ops/research/queue")
def research_queue(
    symbols: list[str] | None = None, user: AuthUser = CurrentUser
) -> list[dict]:
    """Preview of hypotheses that would run next, without executing them."""
    store = ParquetStore(data_root())
    symbols = symbols or [
        key.split("/", 1)[1] for key in getattr(store, "_manifest", {})
    ]
    if not symbols:
        return []
    hyps = generate_hypotheses(store, sorted(set(symbols)))
    tested = set()
    tested_path = ops_root(user.id) / "research" / "tested.json"
    if tested_path.exists():
        tested = set(json.loads(tested_path.read_text()))
    return [h.to_dict() for h in hyps if h.fingerprint not in tested][:50]


@router.get("/ops/research/reports")
def list_reports(user: AuthUser = CurrentUser) -> list[dict]:
    reports_dir = ops_root(user.id) / "research" / "reports"
    if not reports_dir.exists():
        return []
    out = []
    for path in sorted(reports_dir.glob("*.json"), reverse=True):
        payload = json.loads(path.read_text())
        out.append({"date": payload["date"], "tallies": payload["tallies"]})
    return out


@router.get("/ops/research/reports/latest")
def latest_report(user: AuthUser = CurrentUser) -> dict:
    reports_dir = ops_root(user.id) / "research" / "reports"
    files = sorted(reports_dir.glob("*.json")) if reports_dir.exists() else []
    if not files:
        raise HTTPException(status_code=404, detail="no reports yet")
    return json.loads(files[-1].read_text())


# ── morning dashboard aggregate ──────────────────────────────────────
@router.get("/ops/morning")
def morning_dashboard(user: AuthUser = CurrentUser) -> dict:
    deployments = deployment_store(user.id).list()
    alerts = []
    for row in deployments:
        if row["status"] not in ("paper", "live"):
            continue
        try:
            drift = deployment_drift(row["id"], user=user)
        except HTTPException:
            continue
        if drift["status"] != "healthy":
            alerts.append(drift)
    latest = None
    reports_dir = ops_root(user.id) / "research" / "reports"
    files = sorted(reports_dir.glob("*.json")) if reports_dir.exists() else []
    if files:
        latest = json.loads(files[-1].read_text())
    return {
        "deployments": deployments,
        "deployment_alerts": alerts,
        "latest_research": latest,
        "emergency_stop": emergency_stop_active(user.id),
    }
