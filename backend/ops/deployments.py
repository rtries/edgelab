"""Deployment manager.

A deployment is an APPROVED, IMMUTABLE claim: "experiment X validated
strategy Y with parameters P on data D — trade exactly that, under this
risk policy, until the evidence says stop."

Immutability is enforced by construction: the deployment id is the hash
of its config block, and verify_integrity() recomputes it. Changing any
config field yields a different id — i.e. a NEW deployment. Operational
state (status, review flags, history) lives outside the hashed block.

Lifecycle (gates encode the mission — reject weak strategies early):

    proposed ──► rejected
    proposed ──► paper        requires confidence ∈ {moderate, strong}
    paper    ──► review | retired
    paper    ──► live         requires confidence == strong AND paper
                              evidence: ≥ MIN_LIVE_TRADES trades and a
                              'healthy' health status, supplied by the
                              health module and recorded on the
                              transition
    live     ──► review | retired
    review   ──► paper | live | retired

Nothing here ever auto-disables a strategy: drift detection sets
review_required + evidence; a human (or an explicit API call) moves the
status.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

MIN_LIVE_TRADES = 20

STATUS_FLOW: dict[str, set[str]] = {
    "proposed": {"paper", "rejected"},
    "paper": {"live", "review", "retired"},
    "live": {"review", "retired"},
    "review": {"paper", "live", "retired"},
    "rejected": set(),
    "retired": set(),
}

PAPER_CONFIDENCE = {"moderate", "strong"}
LIVE_CONFIDENCE = {"strong"}


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    sizing_mode: str = "pct_equity"        # "pct_equity" | "fixed_qty"
    sizing_value: float = 0.1              # fraction of equity, or shares
    max_position_pct: float = 0.25         # |position notional| / equity cap
    max_gross_exposure_pct: float = 1.0    # gross notional / equity cap
    daily_loss_limit_pct: float = 0.03     # halt for the day beyond this
    max_spread_bps: float = 25.0
    min_dollar_volume: float = 1_000_000.0
    max_bar_age_bars: int = 2              # data-quality staleness gate
    duplicate_cooldown_bars: int = 1
    allow_short: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _config_hash(config: dict) -> str:
    return hashlib.sha256(_canonical(config).encode()).hexdigest()[:12]


@dataclass(slots=True)
class Deployment:
    # ── immutable config block (hashed into id) ───────────────────────
    experiment_id: str
    strategy: str
    strategy_code_hash: str
    engine_version: str
    dataset_fingerprint: str
    params: dict
    confidence: str
    validation_warnings: list[dict]
    symbols: list[str]
    timeframe: str
    session: str                           # "rth" — regular trading hours
    risk: RiskPolicy
    created_at: str
    # ── derived / operational ─────────────────────────────────────────
    id: str = ""
    status: str = "proposed"
    status_history: list[dict] = field(default_factory=list)
    review_required: bool = False
    review_evidence: list[dict] = field(default_factory=list)

    def config_block(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "strategy": self.strategy,
            "strategy_code_hash": self.strategy_code_hash,
            "engine_version": self.engine_version,
            "dataset_fingerprint": self.dataset_fingerprint,
            "params": self.params,
            "confidence": self.confidence,
            "validation_warnings": self.validation_warnings,
            "symbols": self.symbols,
            "timeframe": self.timeframe,
            "session": self.session,
            "risk": self.risk.to_dict(),
            "created_at": self.created_at,
        }

    def __post_init__(self) -> None:
        expected = _config_hash(self.config_block())
        if not self.id:
            self.id = expected

    def verify_integrity(self) -> bool:
        return self.id == _config_hash(self.config_block())

    def to_dict(self) -> dict:
        d = self.config_block()
        d.update(
            id=self.id,
            status=self.status,
            status_history=self.status_history,
            review_required=self.review_required,
            review_evidence=self.review_evidence,
        )
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Deployment":
        dep = cls(
            experiment_id=d["experiment_id"],
            strategy=d["strategy"],
            strategy_code_hash=d["strategy_code_hash"],
            engine_version=d["engine_version"],
            dataset_fingerprint=d["dataset_fingerprint"],
            params=d["params"],
            confidence=d["confidence"],
            validation_warnings=d["validation_warnings"],
            symbols=d["symbols"],
            timeframe=d["timeframe"],
            session=d["session"],
            risk=RiskPolicy(**d["risk"]),
            created_at=d["created_at"],
            id=d["id"],
            status=d.get("status", "proposed"),
            status_history=d.get("status_history", []),
            review_required=d.get("review_required", False),
            review_evidence=d.get("review_evidence", []),
        )
        return dep


def deployment_from_experiment(
    exp: dict,
    risk: RiskPolicy | None = None,
    session: str = "rth",
) -> Deployment:
    """Builds a PROPOSED deployment carrying the experiment's full
    provenance. No gate here — gates live on transitions, so weak
    experiments can be proposed (and promptly rejected on the record)."""
    return Deployment(
        experiment_id=exp["id"],
        strategy=exp["strategy"],
        strategy_code_hash=exp["strategy_code_hash"],
        engine_version=exp["engine_version"],
        dataset_fingerprint=exp["dataset"]["fingerprint"],
        params=dict(exp["selected_params"]),
        confidence=exp["confidence"]["level"],
        validation_warnings=[
            {"code": w["code"], "severity": w["severity"]} for w in exp["warnings"]
        ],
        symbols=list(exp["symbols"]),
        timeframe=exp["timeframe"],
        session=session,
        risk=risk or RiskPolicy(),
        created_at=datetime.now(UTC).isoformat(),
    )


class TransitionError(ValueError):
    """Illegal or gate-blocked lifecycle transition."""


def transition(
    dep: Deployment,
    to: str,
    reason: str,
    paper_evidence: dict | None = None,
) -> Deployment:
    """Mutates status (the ONE mutable thing) after checking flow + gates."""
    if to not in STATUS_FLOW.get(dep.status, set()):
        raise TransitionError(f"cannot go {dep.status} -> {to}")
    if to == "paper" and dep.status == "proposed" and dep.confidence not in PAPER_CONFIDENCE:
        raise TransitionError(
            f"confidence '{dep.confidence}' cannot enter paper trading — "
            f"requires one of {sorted(PAPER_CONFIDENCE)}. Improve the "
            "research, don't lower the bar."
        )
    if to == "live":
        if dep.confidence not in LIVE_CONFIDENCE:
            raise TransitionError(
                f"confidence '{dep.confidence}' cannot go live — requires "
                f"{sorted(LIVE_CONFIDENCE)}"
            )
        ev = paper_evidence or {}
        if ev.get("n_trades", 0) < MIN_LIVE_TRADES or ev.get("health") != "healthy":
            raise TransitionError(
                f"live requires paper evidence: >= {MIN_LIVE_TRADES} trades "
                "and health == 'healthy' "
                f"(got {ev.get('n_trades', 0)} trades, health="
                f"{ev.get('health')!r})"
            )
    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "from": dep.status,
        "to": to,
        "reason": reason,
    }
    if paper_evidence:
        entry["paper_evidence"] = paper_evidence
    dep.status = to
    dep.status_history.append(entry)
    if to in ("paper", "live"):
        dep.review_required = False
    return dep


def flag_for_review(dep: Deployment, evidence: list[dict]) -> Deployment:
    """Drift detection lands here: NEVER auto-disables, only raises the
    flag and attaches the evidence trail."""
    dep.review_required = True
    dep.review_evidence.extend(evidence)
    return dep


class DeploymentStore:
    """ops_data/deployments/{id}.json + index.json, mirroring the
    research store conventions."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        (self.root / "deployments").mkdir(parents=True, exist_ok=True)

    def _index_path(self) -> Path:
        return self.root / "index.json"

    def save(self, dep: Deployment) -> str:
        if not dep.verify_integrity():
            raise ValueError(
                f"deployment {dep.id} failed integrity check — config was "
                "mutated after creation; create a new deployment instead"
            )
        (self.root / "deployments" / f"{dep.id}.json").write_text(
            json.dumps(dep.to_dict(), indent=1)
        )
        rows = [r for r in self.list() if r["id"] != dep.id]
        rows.append({
            "id": dep.id,
            "experiment_id": dep.experiment_id,
            "strategy": dep.strategy,
            "symbols": dep.symbols,
            "timeframe": dep.timeframe,
            "confidence": dep.confidence,
            "status": dep.status,
            "review_required": dep.review_required,
            "created_at": dep.created_at,
        })
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        self._index_path().write_text(json.dumps(rows, indent=1))
        return dep.id

    def get(self, dep_id: str) -> Deployment:
        path = self.root / "deployments" / f"{dep_id}.json"
        if not path.exists():
            raise KeyError(f"no deployment {dep_id}")
        dep = Deployment.from_dict(json.loads(path.read_text()))
        if not dep.verify_integrity():
            raise ValueError(f"deployment {dep_id} config tampered on disk")
        return dep

    def list(self) -> list[dict]:
        path = self._index_path()
        return json.loads(path.read_text()) if path.exists() else []
