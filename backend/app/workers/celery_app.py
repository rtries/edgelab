"""Celery application shared by all task modules."""
from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "edgelab",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_track_started=True,
    task_time_limit=60 * 30,        # hard cap: 30 min per backtest
    worker_prefetch_multiplier=1,   # long tasks — no prefetch hoarding
)
