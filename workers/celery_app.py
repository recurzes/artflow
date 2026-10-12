import sentry_sdk
from celery import Celery
from sentry_sdk.integrations.celery import CeleryIntegration

from shared.config import settings

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0.1,
        integrations=[CeleryIntegration()],
        send_default_pii=False,
    )

celery_app = Celery(
    "artflow",
    broker=settings.redis_url,
    backend=settings.redis_url,
    # Commission timers are not Celery tasks: the bot runs them on a schedule
    # (bot/cogs/sweeps.py), because only the bot can post the result in a ticket.
    include=[
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