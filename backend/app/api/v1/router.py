from fastapi import APIRouter

from app.api.v1 import agent, backtests, decision, feedback, health, market, ops, research, strategies, telegram, tradingview

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(strategies.router, prefix="/strategies", tags=["strategies"])
api_router.include_router(backtests.router, prefix="/backtests", tags=["backtests"])
api_router.include_router(research.router, tags=["research"])
api_router.include_router(market.router, tags=["market"])
api_router.include_router(ops.router, tags=["ops"])
api_router.include_router(feedback.router, tags=["feedback"])
api_router.include_router(decision.router, tags=["decision"])
api_router.include_router(telegram.router, tags=["telegram"])
api_router.include_router(tradingview.router, tags=["tradingview"])
api_router.include_router(agent.router, tags=["agent"])
