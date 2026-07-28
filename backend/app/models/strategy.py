"""Strategy definitions.

A strategy row stores either a visual-builder definition (JSON) or raw
Python source, plus its default parameter set. Versioning is append-only:
edits create a new version so every backtest stays reproducible.
"""
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(20))  # "visual" | "python"
    definition: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # visual graph
    source_code: Mapped[str | None] = mapped_column(Text, nullable=True)  # python
    default_params: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
