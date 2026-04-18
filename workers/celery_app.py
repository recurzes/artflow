from celery import Celery

from shared.config import settings

celery_app = Celery(
    "artflow",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "workers.notifications",
        "workers.images"
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Manila",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True
)