"""
Read-only reporting queries for a server's administrators.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.artist import Artist
from shared.models.commission import Commission, CommissionStatus
from shared.models.user import User

_FINISHED = (CommissionStatus.COMPLETED, CommissionStatus.CANCELLED)


async def count_active_commissions(db: AsyncSession, server_id: uuid.UUID) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(Commission)
        .where(Commission.server_id == server_id, Commission.status.notin_(_FINISHED))
    )
    return int(count or 0)


async def count_completed_since(db: AsyncSession, server_id: uuid.UUID, since: datetime) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(Commission)
        .where(
            Commission.server_id == server_id,
            Commission.status == CommissionStatus.COMPLETED,
            Commission.completed_at >= since
        )
    )
    return int(count or 0)


async def sum_platform_fees_since(
        db: AsyncSession,
        server_id: uuid.UUID,
        since: datetime
) -> Decimal:
    total = await db.scalar(
        select(func.coalesce(func.sum(Commission.platform_fee_php), 0))
        .where(
            Commission.server_id == server_id,
            Commission.status == CommissionStatus.COMPLETED,
            Commission.completed_at >= since
        )
    )
    return Decimal(str(total or 0))


async def count_commissions_by_status(
        db: AsyncSession,
        server_id: uuid.UUID
) -> dict[CommissionStatus, int]:
    rows = await db.execute(
        select(Commission.status, func.count(Commission.id))
        .where(Commission.server_id == server_id)
        .group_by(Commission.status)
    )
    return {status: int(count) for status, count in rows.all()}


async def list_artists_with_active_counts(
        db: AsyncSession,
        server_id: uuid.UUID,
        *,
        limit: int,
        offset: int
) -> list[tuple[Artist, str, int]]:
    """(artist, their Discord ID, active commissions) in one query, every status."""
    active = func.count(Commission.id)
    rows = await db.execute(
        select(Artist, User.discord_user_id, active)
        .join(User, Artist.user_id == User.id)
        .outerjoin(
            Commission,
            and_(Commission.artist_id == Artist.id, Commission.status.notin_(_FINISHED))
        )
        .where(Artist.server_id == server_id)
        .group_by(Artist.id, User.discord_user_id)
        .order_by(Artist.display_name)
        .limit(limit)
        .offset(offset)
    )
    return [(artist, discord_id, int(count)) for artist, discord_id, count in rows.all()]
