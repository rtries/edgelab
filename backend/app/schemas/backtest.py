"""Pydantic schemas for backtest endpoints."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class CostModelIn(BaseModel):
    commission_per_share: float = 0.005
    slippage_bps: float = 1.0
    spread_bps: float = 0.5


class BacktestConfigIn(BaseModel):
    symbols: list[str] = Field(min_length=1)
    start: date
    end: date
    timeframe: str = "1d"  # "1m" | "1h" | "1d"
    initial_cash: float = 100_000.0
    params: dict = {}
    costs: CostModelIn = CostModelIn()


class BacktestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_id: uuid.UUID
    status: str
    config: dict
    metrics: dict | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None
