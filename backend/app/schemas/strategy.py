"""Pydantic schemas for strategy endpoints."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class StrategyCreate(BaseModel):
    name: str
    kind: Literal["visual", "python"]
    definition: dict | None = None
    source_code: str | None = None
    default_params: dict = {}


class StrategyOut(StrategyCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    created_at: datetime
