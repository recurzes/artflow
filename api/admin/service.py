import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import repository
from api.admin.schemas import AdminArtist, AdminArtistList, AdminStats, CommissionSummary


async def get_stats(db: AsyncSession, server_id: uuid.UUID) -> AdminStats:
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_month = start_of_day.replace(day=1)
    return AdminStats(
        active_commissions=await repository.count_active_commissions(db, server_id),
        completed_today=await repository.count_completed_since(db, server_id, start_of_day),
        revenue_php_this_month=await repository.sum_platform_fees_since(
            db,
            server_id,
            start_of_month
        ),
    )


async def list_artists(
        db: AsyncSession,
        server_id: uuid.UUID,
        *,
        limit: int,
        offset: int
) -> AdminArtistList:
    rows = await repository.list_artists_with_active_counts(
        db,
        server_id,
        limit=limit,
        offset=offset
    )
    return AdminArtistList(
        artists=[
            AdminArtist(
                id=artist.id,
                display_name=artist.display_name,
                discord_user_id=discord_user_id,
                status=artist.status,
                nsfw_enabled=artist.nsfw_enabled,
                active_commission_count=active
            )
            for artist, discord_user_id, active in rows
        ],
        limit=limit,
        offset=offset
    )


async def get_commission_summary(db: AsyncSession, server_id: uuid.UUID) -> CommissionSummary:
    counts = await repository.count_commissions_by_status(db, server_id)
    return CommissionSummary(by_status={status.value: count for status, count in counts.items()})
