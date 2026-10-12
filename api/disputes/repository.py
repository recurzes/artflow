import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.dispute import Dispute


async def get_by_id_for_update(db: AsyncSession, dispute_id: uuid.UUID) -> Dispute | None:
    return await db.scalar(select(Dispute).where(Dispute.id == dispute_id).with_for_update())


async def get_by_commission_id(db: AsyncSession, commission_id: uuid.UUID) -> Dispute | None:
    return await db.scalar(select(Dispute).where(Dispute.commission_id == commission_id))


async def add(db: AsyncSession, dispute: Dispute) -> Dispute:
    db.add(dispute)
    await db.flush()
    return dispute
