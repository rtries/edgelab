"""Tester feedback — structured, append-only, shared across all testers.

Deliberately NOT per-user (unlike research/ops): the whole point is a
single place to review what every tester reported, not siloed. Written
to a flat JSONL file under EDGELAB_OPS_ROOT — no dashboard, no roles,
just a durable record for the person running the MVP test to read.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.auth import AuthUser, get_current_user

router = APIRouter()

CurrentUser = Depends(get_current_user)

CATEGORIES = ("bug", "confusing_ui", "missing_feature", "suggestion", "general")


def _feedback_path() -> Path:
    base = Path(os.environ.get("EDGELAB_OPS_ROOT", "ops_data"))
    path = base / "_feedback"
    path.mkdir(parents=True, exist_ok=True)
    return path / "feedback.jsonl"


class FeedbackRequest(BaseModel):
    category: str = Field(pattern="^(" + "|".join(CATEGORIES) + ")$")
    message: str = Field(min_length=1, max_length=4000)
    page: str
    symbol: str | None = None
    browser: str | None = None
    client_timestamp: str | None = None


@router.post("/feedback")
def submit_feedback(req: FeedbackRequest, user: AuthUser = CurrentUser) -> dict:
    entry = {
        "id": uuid4().hex[:12],
        "received_at": datetime.now(UTC).isoformat(),
        "client_timestamp": req.client_timestamp,
        "user_id": user.id,
        "user_email": user.email,
        "category": req.category,
        "message": req.message,
        "page": req.page,
        "symbol": req.symbol,
        "browser": req.browser,
    }
    with _feedback_path().open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


@router.get("/feedback")
def list_feedback(limit: int = 200, user: AuthUser = CurrentUser) -> list[dict]:
    path = _feedback_path()
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    return [json.loads(line) for line in lines[-limit:]][::-1]
