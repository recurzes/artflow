from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from api.artists import service as artist_service
from api.commissions import service as commission_service
from api.reviews import repository
from api.reviews.schemas import ReviewCreate
from shared.errors import Conflict, Forbidden, InvalidState
from shared.models.commission import CommissionStatus
from shared.models.review import Review


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

    if await repository.get_by_commission_id(db, commission_id) is not None:
        raise Conflict("This commission has already been reviewed")

    review = await repository.add(
        db,
        Review(
            commission_id=commission_id,
            reviewer_id=data.reviewer_id,
            artist_id=comm.artist_id,
            rating=data.rating,
            body=data.body,
            is_public=data.is_public
        )
    )

    # Recompute from the reviews themselves instead of adjusting a running
    # average, so concurrent reviews cannot make the stored figure drift.
    artist = await artist_service.get_artist_for_update(db, comm.artist_id)
    average, count = await repository.rating_summary_for_artist(db, comm.artist_id)
    artist.rating_avg = float((average or Decimal(0)).quantize(Decimal("0.01")))
    artist.rating_count = count

    await db.flush()
    return review
