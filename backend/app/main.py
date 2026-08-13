"""EdgeLab API entrypoint."""
import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from ops.auto_trader import auto_trade_loop


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    if settings.auth_disabled and not settings.is_dev:
        raise RuntimeError(
            "AUTH_DISABLED=true is not allowed outside api_env=development"
        )
    # Paper-only unattended auto-trade loop — see ops/auto_trader.py for
    # every safety constraint (kill switch, per-user opt-in, cooldown,
    # fixed sizing, no live-money path). Runs in-process; cancelled
    # cleanly on shutdown rather than left dangling.
    task = asyncio.create_task(auto_trade_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(
    title="EdgeLab API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.is_dev else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")
