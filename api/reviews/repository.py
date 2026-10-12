import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.review import Review


async def get_by_commission_id(db: AsyncSession, commission_id: uuid.UUID) -> Review | None:
    return await db.scalar(select(Review).where(Review.commission_id == commission_id))


async def add(db: AsyncSession, review: Review) -> Review:
    db.add(review)
    await db.flush()
    return review


async def rating_summary_for_artist(
        db: AsyncSession,
        artist_id: uuid.UUID
) -> tuple[Decimal | None, int]:
    """(average rating, number of reviews) across everything the artist has received."""
    average, count = (
        await db.execute(
            select(func.avg(Review.rating), func.count(Review.id))
            .where(Review.artist_id == artist_id)
        )
    ).one()
    return (Decimal(str(average)) if average is not None else None), int(count)
