import logging

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="notifications.payment_reminder"
)
def send_payment_reminder(self, commission_id: str) -> None:
    logger.info("Payment reminder queued for commission %s", commission_id)
    try:
        # TODO: fetch commission, DM client with payment reminder embed
        pass
    except Exception as exc:
        logger.error(
            "Payment reminder failed for commission %s (attempt %d): %s",
            commission_id, self.request.retries + 1, exc
        )
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="notifications.payment_expired"
)
def cancel_unpaid_commission(self, commission_id: str) -> None:
    logger.info("Payment expiry check for commission %s", commission_id)
    try:
        # TODO: fetch commission, update status to CANCELLED, notify both parties
        pass
    except Exception as exc:
        logger.error(
            "Payment expiry handler failed for commission %s (attempt %d): %s",
            commission_id, self.request.retries + 1, exc
        )
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="notifications.delivery_auto_accept"
)
def auto_accept_delivery(self, commission_id: str) -> None:
    logger.info("Delivery auto-accept check for commission %s", commission_id)
    try:
        # TODO: if 48h elapsed + client hasn't responded, mark commission COMPLETED
        pass
    except Exception as exc:
        logger.error(
            "Delivery auto-accept failed for commission %s (attempt %d): %s",
            commission_id, self.request.retries + 1, exc
        )
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="notifications.trial_expiry_reminder"
)
def send_trial_expiry_reminder(self, guild_id: str) -> None:
    logger.info("Trial expiry reminder for guild %s", guild_id)
    try:
        # TODO: DM server owner with upgrade prompt + expiry date
        pass
    except Exception as exc:
        logger.error(
            "Trial expiry reminder failed for guild %s (attempt %d): %s",
            guild_id, self.request.retries + 1, exc
        )
        raise self.retry(exc=exc)