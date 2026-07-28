"""Research terminal API.

Filesystem-backed (ExperimentStore + ParquetStore) so the workspace runs
with zero external services. Roots resolve from env at request time:
  EDGELAB_RESEARCH_ROOT   (default backend/research_data)
  EDGELAB_DATA_ROOT       (default backend/data/store)
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from engine.calendar import WeekdayCalendar
from engine.data.schema import validate
from engine.data.schema_types import DataError, Timeframe
from engine.data.store import ParquetStore
from engine.params import Param
from engine.strategies import examples as example_strategies
from research.store import ExperimentStore

from app.core.auth import AuthUser, get_current_user

router = APIRouter()

STRATEGY_REGISTRY = {
    cls.__name__: cls
    for cls in (
        example_strategies.BuyAndHold,
        example_strategies.MACrossover,
        example_strategies.RSIMeanReversion,
        example_strategies.VolatilityBreakout,
    )
}

CurrentUser = Depends(get_current_user)


def research_root(user_id: str) -> Path:
    """Per-user: experiments and notes are private to whoever ran them."""
    base = Path(os.environ.get("EDGELAB_RESEARCH_ROOT", "research_data"))
    return base / user_id


def data_root() -> Path:
    """Shared: raw market data has no reason to be duplicated per user."""
    return Path(os.environ.get("EDGELAB_DATA_ROOT", "data/store"))


def experiment_store(user_id: str) -> ExperimentStore:
    return ExperimentStore(research_root(user_id))


# ── strategies ────────────────────────────────────────────────────────
def _param_dict(p: Param) -> dict:
    return {"name": p.name, "type": p.type, "default": p.default,
            "min": p.min, "max": p.max, "step": p.step,
            "description": p.description}


@router.get("/research/strategies")
def list_strategies(user: AuthUser = CurrentUser) -> list[dict]:
    return [
        {
            "name": name,
            "description": (cls.__doc__ or "").strip(),
            "params": [_param_dict(p) for p in cls.params],
        }
        for name, cls in STRATEGY_REGISTRY.items()
    ]


# ── experiments ───────────────────────────────────────────────────────
@router.get("/research/experiments")
def search_experiments(
    text: str | None = None,
    strategy: str | None = None,
    symbol: str | None = None,
    tag: str | None = None,
    engine_version: str | None = None,
    fingerprint: str | None = None,
    confidence: str | None = None,
    filters: str | None = Query(
        None, description="comma-separated metric expressions, e.g. sharpe>1.5"
    ),
    user: AuthUser = CurrentUser,
) -> list[dict]:
    expressions = [f.strip() for f in filters.split(",") if f.strip()] if filters else []
    try:
        return experiment_store(user.id).search(
            text=text, strategy=strategy, symbol=symbol, tag=tag,
            engine_version=engine_version, fingerprint=fingerprint,
            confidence=confidence, filters=expressions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/research/experiments/{exp_id}")
def get_experiment(exp_id: str, user: AuthUser = CurrentUser) -> dict:
    try:
        return experiment_store(user.id).get(exp_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/research/experiments/{exp_id}/report.pdf")
def experiment_pdf(exp_id: str, user: AuthUser = CurrentUser) -> StreamingResponse:
    from research.pdf import build_pdf

    try:
        exp = experiment_store(user.id).get(exp_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    buffer = io.BytesIO()
    build_pdf(exp, buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="edgelab-{exp_id}.pdf"'
        },
    )


class RunRequest(BaseModel):
    strategy: str
    symbols: list[str] = Field(min_length=1)
    timeframe: str = "1d"
    param_values: dict[str, list] | None = None
    train_size: int = 60
    val_size: int = 20
    test_size: int = 25
    mc_iters: int = 300
    seed: int = 7
    tags: list[str] = []


@router.post("/research/experiments")
def launch_experiment(req: RunRequest, user: AuthUser = CurrentUser) -> dict:
    """Runs the full pipeline synchronously (research runs on local data
    complete in seconds; Celery offload can arrive with live data)."""
    from research.pipeline import run_experiment

    if req.strategy not in STRATEGY_REGISTRY:
        raise HTTPException(status_code=422, detail=f"unknown strategy {req.strategy}")
    store = ParquetStore(data_root())
    try:
        exp = run_experiment(
            data_store=store,
            strategy_cls=STRATEGY_REGISTRY[req.strategy],
            symbols=req.symbols,
            timeframe=Timeframe(req.timeframe),
            param_values=req.param_values,
            train_size=req.train_size,
            val_size=req.val_size,
            test_size=req.test_size,
            mc_iters=req.mc_iters,
            seed=req.seed,
            tags=req.tags,
            registry_path=research_root(user.id) / "registry.json",
        )
    except (FileNotFoundError, DataError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    experiment_store(user.id).save(exp)
    return {"id": exp["id"], "confidence": exp["confidence"]}


# ── datasets ──────────────────────────────────────────────────────────
@router.get("/research/datasets")
def list_datasets(user: AuthUser = CurrentUser) -> list[dict]:
    store = ParquetStore(data_root())
    out = []
    for key, meta in store._manifest.items():  # noqa: SLF001 (read-only view)
        timeframe, symbol = key.split("/", 1)
        out.append({"symbol": symbol, "timeframe": timeframe, **meta})
    return sorted(out, key=lambda r: (r["timeframe"], r["symbol"]))


@router.get("/research/datasets/{timeframe}/{symbol}")
def dataset_detail(timeframe: str, symbol: str, user: AuthUser = CurrentUser) -> dict:
    store = ParquetStore(data_root())
    try:
        df = store.read(symbol, timeframe)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    integrity = "verified"
    try:
        store.verify(symbol, timeframe)
    except DataError as exc:
        integrity = f"FAILED: {exc}"

    calendar = WeekdayCalendar()
    report = validate(df, calendar=calendar, on_missing="report")
    meta = store._manifest.get(f"{timeframe}/{symbol}", {})  # noqa: SLF001
    closes = df.set_index("ts")["close"]
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "fingerprint": meta.get("checksum"),
        "sources": meta.get("sources", []),
        "adjustment": "raw (store holds raw prices only; adjustments are "
                      "applied per run and recorded in each manifest)",
        "calendar": "WeekdayCalendar (Mon-Fri, fixed UTC sessions)",
        "coverage": {
            "start": str(df["ts"].iloc[0]) if len(df) else None,
            "end": str(df["ts"].iloc[-1]) if len(df) else None,
            "rows": int(len(df)),
        },
        "missing_sessions": [str(d) for d in report.missing_sessions],
        "missing_intraday_bars": report.missing_intraday_bars,
        "integrity": integrity,
        "corporate_actions": "none recorded — supplied per run "
                             "(see run manifests)",
        "preview_close": [
            [ts.isoformat(), float(v)] for ts, v in closes.tail(300).items()
        ],
    }


# ── notes ─────────────────────────────────────────────────────────────
class NoteRequest(BaseModel):
    title: str
    body: str = ""
    tags: list[str] = []


@router.get("/research/notes")
def list_notes(user: AuthUser = CurrentUser) -> list[dict]:
    return experiment_store(user.id).notes()


@router.post("/research/notes")
def create_note(req: NoteRequest, user: AuthUser = CurrentUser) -> dict:
    return experiment_store(user.id).add_note(req.title, req.body, req.tags)


@router.delete("/research/notes/{note_id}")
def delete_note(note_id: str, user: AuthUser = CurrentUser) -> dict:
    if not experiment_store(user.id).delete_note(note_id):
        raise HTTPException(status_code=404, detail=f"no note {note_id}")
    return {"deleted": note_id}
