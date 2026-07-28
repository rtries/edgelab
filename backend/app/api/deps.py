"""Shared FastAPI dependencies. Auth lands here in a later phase."""
from app.db.session import get_db  # noqa: F401  — re-exported for endpoints
