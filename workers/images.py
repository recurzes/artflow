import logging

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)

@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="images.apply_watermark"
)
def apply_watermark(self, commission_id: str, image_url: str) -> dict:
    logger.info("Watermark task queued for commission %s, image %s", commission_id, image_url)
    try:
        # TODO: download image_url, apply Pillow watermark, upload to Supabase
        return {"original_url": image_url, "watermarked_url": None}
    except Exception as exc:
        logger.error(
            "Watermark failed for commission %s (attempt %d): %s",
            commission_id, self.request.retries + 1, exc
        )
        raise self.retry(exc=exc)