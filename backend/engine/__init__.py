"""EdgeLab engine — pure-Python backtesting, validation, and risk library.

Design rules:
- No FastAPI, Celery, or SQLAlchemy imports anywhere in this package.
  The engine takes dataframes/objects in and returns results out, so it is
  unit-testable in isolation and reusable from notebooks.
- Event-driven simulation: signals computed on bar close execute on the
  NEXT bar (no look-ahead), fills pass through an explicit cost model.
- Every stochastic component takes an explicit seed for reproducibility.
"""

__version__ = "0.2.0"
