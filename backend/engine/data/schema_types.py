"""Shared small types for the data layer (kept import-cycle free)."""
from __future__ import annotations

import enum
from datetime import timedelta


class Timeframe(enum.StrEnum):
    M1 = "1m"
    H1 = "1h"
    D1 = "1d"

    @property
    def delta(self) -> timedelta:
        return {
            Timeframe.M1: timedelta(minutes=1),
            Timeframe.H1: timedelta(hours=1),
            Timeframe.D1: timedelta(days=1),
        }[self]


class AdjustmentMode(enum.StrEnum):
    RAW = "raw"
    SPLIT = "split"
    TOTAL_RETURN = "total_return"


class DataError(Exception):
    """Base for all data-layer errors."""


class DataValidationError(DataError):
    def __init__(self, message: str, issues: list[str] | None = None) -> None:
        self.issues = issues or []
        detail = message if not self.issues else message + "\n  - " + "\n  - ".join(self.issues)
        super().__init__(detail)


class DataIntegrityError(DataError):
    pass


class MissingCredentialsError(DataError):
    pass
