"""
Image work that is too slow for a request: watermarking WIP previews.

Not built yet. The task below is a placeholder so the worker has a registered
task and the queue name is settled; nothing enqueues it. When it is built, the
API (not the bot) should enqueue it after storing a WIP image, and the result
belongs in wip_updates.watermarked_key.
"""
import logging

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="images.apply_watermark")
def apply_watermark(commission_id: str, image_key: str) -> dict:
    logger.warning(
        "images.apply_watermark is not implemented (commission %s, image %s)",
        commission_id,
        image_key
    )
    return {"image_key": image_key, "watermarked_key": None}
