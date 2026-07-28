"""CRUD for strategies."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.strategy import Strategy
from app.schemas.strategy import StrategyCreate, StrategyOut

router = APIRouter()


@router.post("", response_model=StrategyOut, status_code=201)
async def create_strategy(
    payload: StrategyCreate, db: AsyncSession = Depends(get_db)
) -> Strategy:
    strategy = Strategy(**payload.model_dump())
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    return strategy


@router.get("", response_model=list[StrategyOut])
async def list_strategies(db: AsyncSession = Depends(get_db)) -> list[Strategy]:
    result = await db.execute(select(Strategy).order_by(Strategy.created_at.desc()))
    return list(result.scalars())


@router.get("/{strategy_id}", response_model=StrategyOut)
async def get_strategy(
    strategy_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> Strategy:
    strategy = await db.get(Strategy, strategy_id)
    if strategy is None:
        raise HTTPException(404, "Strategy not found")
    return strategy
