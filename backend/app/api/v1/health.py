"""Liveness + dependency health, used by the frontend status panel."""
from fastapi import APIRouter
from redis import asyncio as aioredis
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    checks: dict[str, str] = {"api": "ok"}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001 — health checks report, never raise
        checks["postgres"] = f"error: {type(exc).__name__}"

    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {type(exc).__name__}"

    return checks
