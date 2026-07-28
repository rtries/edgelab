"""Background tasks. Workers use sync DB access (separate from API's asyncpg)."""
from datetime import UTC, datetime

from celery.utils.log import get_task_logger
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)

_sync_engine = None


def _get_engine():  # noqa: ANN202 — lazy singleton; created on first task, not import
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(
            settings.database_url.replace("+asyncpg", ""), pool_pre_ping=True
        )
    return _sync_engine


@celery_app.task(bind=True, name="backtests.run")
def run_backtest(self, run_id: str) -> str:  # noqa: ANN001
    """Execute a backtest run end-to-end.

    Phase 1 wires this to engine.backtest.Backtester. For now it marks the
    run completed with a placeholder so the queue plumbing is verifiable.
    """
    from app.models.backtest import BacktestRun  # local import: worker boot speed

    with Session(_get_engine()) as db:
        run = db.get(BacktestRun, run_id)
        if run is None:
            logger.error("run %s not found", run_id)
            return "missing"

        run.status = "running"
        db.commit()

        try:
            # TODO(phase-1): load data feed, build strategy, run engine, persist
            # trades + equity curve, compute engine.metrics report.
            run.metrics = {"note": "engine not implemented yet — Phase 1"}
            run.status = "completed"
        except Exception as exc:  # noqa: BLE001 — status must always be recorded
            logger.exception("backtest failed")
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"
        finally:
            run.completed_at = datetime.now(UTC)
            db.commit()

    return run.status
