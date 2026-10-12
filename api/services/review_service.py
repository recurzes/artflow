from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.commissions import service as commission_service
from shared.errors import Conflict, Forbidden, InvalidState
from shared.models.artist import Artist
from shared.models.commission import CommissionStatus
from shared.models.review import Review
from shared.schemas.review import ReviewCreate


async def create_review(
        db: AsyncSession,
        commission_id: uuid.UUID,
        data: ReviewCreate
) -> Review:
    # The row lock makes "is there a review yet?" and the insert one step.
    comm = await commission_service.get_commission_for_update(db, commission_id)
    if comm.status != CommissionStatus.COMPLETED:
        raise InvalidState("A commission can be reviewed once it is completed")

    if data.reviewer_id != comm.client_id:
        raise Forbidden("Only the commissioning client can review this commission")

    existing = await db.scalar(select(Review).where(Review.commission_id == commission_id))
    if existing is not None:
        raise Conflict("This commission has already been reviewed")

    review = Review(
        commission_id=commission_id,
        reviewer_id=data.reviewer_id,
        artist_id=comm.artist_id,
        rating=data.rating,
        body=data.body,
        is_public=data.is_public
    )
    db.add(review)
    await db.flush()

    # Recompute from the reviews themselves instead of adjusting a running
    # average, so concurrent reviews cannot make the stored figure drift.
    artist = await db.scalar(
        select(Artist).where(Artist.id == comm.artist_id).with_for_update()
    )
    average, count = (
        await db.execute(
            select(func.avg(Review.rating), func.count(Review.id))
            .where(Review.artist_id == comm.artist_id)
        )
    ).one()
    artist.rating_avg = float(Decimal(str(average)).quantize(Decimal("0.01")))
    artist.rating_count = int(count)

    await db.flush()
    return review
