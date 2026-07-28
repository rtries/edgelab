"""Declarative base + model registry.

Import every model module here so Alembic autogenerate sees the full schema.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# noqa: E402  — imported for side effects (metadata registration)
from app.models import backtest, strategy, trade  # noqa: F401,E402
