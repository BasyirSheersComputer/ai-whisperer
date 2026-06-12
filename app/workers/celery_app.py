"""Celery application instance."""
from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "reactivation",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    timezone=settings.timezone,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "dispatch-outbound-every-minute": {"task": "dispatch_outbound", "schedule": 60.0},
        "booking-reminders-every-5-min": {"task": "send_booking_reminders", "schedule": 300.0},
    },
)
