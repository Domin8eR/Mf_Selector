"""AltStreet Celery application and beat schedule."""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "altstreet",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.jobs.tasks.metrics",
        "app.jobs.tasks.rankings",
        "app.jobs.tasks.insights_precompute",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    worker_hijack_root_logger=False,
    # Daily refresh at 09:30 IST (04:00 UTC) — after AMFI publishes NAVs
    beat_schedule={
        "daily-metrics-large-cap": {
            "task": "tasks.recalculate_metrics",
            "schedule": crontab(hour=4, minute=0),
            "kwargs": {
                "category_id": "LARGE_CAP",
                "evaluation_date_iso": "dynamic",  # overridden by trigger
                "data_version_id": 1,
            },
        },
        "daily-rankings-large-cap": {
            "task": "tasks.generate_ranking_snapshot",
            "schedule": crontab(hour=4, minute=30),
            "kwargs": {
                "category_id": "LARGE_CAP",
                "rule_version_id": "RV-LC-V32",
                "evaluation_date_iso": "dynamic",
                "data_version_id": 1,
            },
        },
        "daily-insights-precompute": {
            "task": "tasks.precompute_daily_insights",
            "schedule": crontab(hour=13, minute=0),  # 18:30 IST = 13:00 UTC
        },
    },
)
