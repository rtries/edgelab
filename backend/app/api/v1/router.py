from fastapi import APIRouter

from app.api.v1 import backtests, health, ops, research, strategies

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(strategies.router, prefix="/strategies", tags=["strategies"])
api_router.include_router(backtests.router, prefix="/backtests", tags=["backtests"])
api_router.include_router(research.router, tags=["research"])
api_router.include_router(ops.router, tags=["ops"])
