from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.errors import Conflict, Forbidden, InvalidState, NotFound
from shared.models.artist import Artist
from shared.models.commission import Commission, CommissionStatus
from shared.models.review import Review
from shared.schemas.review import ReviewCreate


async def create_review(
        db: AsyncSession,
        commission_id: uuid.UUID,
        data: ReviewCreate
) -> Review:
    result = await db.execute(select(Commission).where(Commission.id == commission_id))
    comm = result.scalar_one_or_none()
    if comm is None:
        raise NotFound("Commission not found")
    if comm.status != CommissionStatus.COMPLETED:
        raise InvalidState("Commission must be completed before leaving a review")

    if data.reviewer_id != comm.client_id:
        raise Forbidden("Only the commissioning client can review this commission")

    existing = await db.execute(
        select(Review).where(Review.commission_id == commission_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise Conflict("A review already exists for this commission")

    review = Review(
        commission_id=commission_id,
        reviewer_id=data.reviewer_id,
        artist_id=comm.artist_id,
        rating=data.rating,
        body=data.body,
        is_public=data.is_public
    )
    db.add(review)

    artist_result = await db.execute(select(Artist).where(Artist.id == comm.artist_id))
    artist = artist_result.scalar_one()
    old_count = artist.rating_count
    old_avg = Decimal(str(artist.rating_avg))
    new_rating = Decimal(data.rating)
    if old_count == 0:
        new_avg = new_rating
    else:
        new_avg = (old_avg * old_count + new_rating) / (old_count + 1)
    artist.rating_avg = float(new_avg.quantize(Decimal("0.01")))
    artist.rating_count = old_count + 1

    await db.flush()
    return review