# Architecture notes

## Why the engine is a separate framework-free package

Backtest correctness is the whole product. Keeping `engine/` free of FastAPI/
Celery/SQLAlchemy means it can be exercised from pytest and notebooks with
zero infrastructure, and the API layer stays a thin adapter around it.

## Request flow for a backtest

1. `POST /api/v1/backtests/{strategy_id}` inserts an immutable `backtest_runs`
   row (config snapshot included) and enqueues `backtests.run`.
2. Worker loads the strategy version + config, builds a `DataFeed`,
   `CostModel`, `RiskModel`, runs `Backtester.run()`.
3. Results persist as: metrics JSON on the run row, trades in `trades`,
   equity curve as an artifact (parquet on disk/object storage — Phase 3).
4. Frontend polls the run (later: Redis pub/sub → SSE for live progress).

## Async vs sync database access

API uses asyncpg (async sessions). Workers use psycopg2 (sync sessions) —
Celery tasks are synchronous and mixing event loops inside workers is a
known footgun. Alembic also uses the sync driver.

## Live trading gate

The broker abstraction (Phase 5) exposes one interface for sim/paper/live.
Live mode requires: env flag AND per-account explicit enablement AND passing
risk-limit configuration. Kill switch is a Redis flag checked before every
order route.
