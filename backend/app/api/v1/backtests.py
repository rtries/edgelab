"""Launch and inspect backtest runs. Execution happens in Celery workers."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.backtest import BacktestRun
from app.models.strategy import Strategy
from app.schemas.backtest import BacktestConfigIn, BacktestRunOut
from app.workers.tasks import run_backtest

router = APIRouter()


@router.post("/{strategy_id}", response_model=BacktestRunOut, status_code=202)
async def launch_backtest(
    strategy_id: uuid.UUID,
    config: BacktestConfigIn,
    db: AsyncSession = Depends(get_db),
) -> BacktestRun:
    if await db.get(Strategy, strategy_id) is None:
        raise HTTPException(404, "Strategy not found")

    run = BacktestRun(strategy_id=strategy_id, config=config.model_dump(mode="json"))
    db.add(run)
    await db.commit()
    await db.refresh(run)

    task = run_backtest.delay(str(run.id))
    run.celery_task_id = task.id
    await db.commit()
    await db.refresh(run)
    return run


@router.get("/{run_id}", response_model=BacktestRunOut)
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> BacktestRun:
    run = await db.get(BacktestRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run
