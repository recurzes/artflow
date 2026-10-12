import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from shared.models.artist import Artist
from shared.models.commission import Commission, CommissionStatus
from shared.models.wip_update import WipUpdate

TERMINAL_STATUSES = (CommissionStatus.COMPLETED, CommissionStatus.CANCELLED)

# Every commission handed to a caller carries its client and its artist's user,
# so the Discord IDs of both parties are always available.
_WITH_PARTIES = (
    joinedload(Commission.client, innerjoin=True),
    joinedload(Commission.artist, innerjoin=True).joinedload(Artist.user, innerjoin=True),
)


async def get_by_id(
        db: AsyncSession,
        commission_id: uuid.UUID,
        *,
        for_update: bool = False
) -> Commission | None:
    query = select(Commission).options(*_WITH_PARTIES).where(Commission.id == commission_id)
    if for_update:
        query = query.with_for_update(of=Commission)
    return await db.scalar(query)


async def get_by_ticket_channel(db: AsyncSession, discord_channel_id: str) -> Commission | None:
    return await db.scalar(
        select(Commission)
        .options(*_WITH_PARTIES)
        .where(Commission.discord_ticket_channel_id == discord_channel_id)
    )


async def ticket_channel_in_use(db: AsyncSession, discord_channel_id: str) -> bool:
    found = await db.scalar(
        select(Commission.id).where(Commission.discord_ticket_channel_id == discord_channel_id)
    )
    return found is not None


async def count_active_for_artist(db: AsyncSession, artist_id: uuid.UUID) -> int:
    """Commissions that occupy one of the artist's slots: everything not finished."""
    count = await db.scalar(
        select(func.count())
        .select_from(Commission)
        .where(
            Commission.artist_id == artist_id,
            Commission.status.notin_(TERMINAL_STATUSES)
        )
    )
    return int(count or 0)


async def add(db: AsyncSession, commission: Commission) -> Commission:
    db.add(commission)
    await db.flush()
    return commission


async def add_wip_update(db: AsyncSession, wip_update: WipUpdate) -> WipUpdate:
    db.add(wip_update)
    await db.flush()
    return wip_update


# What the scheduled sweeps look for. IDs only: the service re-reads each
# commission under a row lock before changing it.

async def list_unpaid_past_deadline(db: AsyncSession, now: datetime) -> list[uuid.UUID]:
    result = await db.scalars(
        select(Commission.id).where(
            Commission.status == CommissionStatus.PAYMENT_PENDING,
            Commission.payment_deadline_at < now,
            Commission.payment_receipt_key.is_(None),
        )
    )
    return list(result.all())


async def list_deliveries_past_auto_accept(db: AsyncSession, now: datetime) -> list[uuid.UUID]:
    result = await db.scalars(
        select(Commission.id).where(
            Commission.status == CommissionStatus.DELIVERED,
            Commission.delivery_auto_accept_at < now,
        )
    )
    return list(result.all())


async def list_unreminded_with_deadline_between(
        db: AsyncSession,
        start: datetime,
        end: datetime
) -> list[uuid.UUID]:
    result = await db.scalars(
        select(Commission.id).where(
            Commission.status == CommissionStatus.PAYMENT_PENDING,
            Commission.payment_reminder_sent.is_(False),
            Commission.payment_receipt_key.is_(None),
            Commission.payment_deadline_at > start,
            Commission.payment_deadline_at <= end,
        )
    )
    return list(result.all())
