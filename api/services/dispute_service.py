from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.services.commission_service import PLATFORM_FEE_RATE
from shared.models.commission import Commission, CommissionStatus
from shared.models.dispute import Dispute, DisputeStatus
from shared.models.user import User
from shared.schemas.dispute import DisputeCreate, DisputeResolve


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_dispute_by_id(db: AsyncSession, dispute_id: uuid.UUID) -> Dispute | None:
    r = await db.execute(select(Dispute).where(Dispute.id == dispute_id))
    return r.scalar_one_or_none()


async def get_dispute_by_commission_id(
        db: AsyncSession,
        commission_id: uuid.UUID
) -> Dispute | None:
    r = await db.execute(select(Dispute).where(Dispute.commission_id == commission_id))
    return r.scalar_one_or_none()


async def open_dispute(
        db: AsyncSession,
        body: DisputeCreate
) -> Dispute:
    ruser = await db.execute(
        select(User).where(User.discord_user_id == body.raised_by_discord_user_id)
    )
    raiser = ruser.scalar_one_or_none()
    if raiser is None:
        raise ValueError("Raising user not found. Complete server join / verification first")

    rcomm = await db.execute(
        select(Commission)
        .options(joinedload(Commission.artist))
        .where(Commission.id == body.commission_id)
    )
    comm = rcomm.unique().scalar_one_or_none()
    if comm is None:
        raise ValueError("Commission not found")

    is_client = comm.client_id == raiser.id
    is_artist = comm.artist is not None and comm.artist.user_id == raiser.id
    if not is_client and not is_artist:
        raise ValueError("Only the client or the artist can open a dispute")

    existing = await get_dispute_by_commission_id(db, body.commission_id)
    if existing is not None:
        if existing.status == DisputeStatus.RESOLVED:
            raise ValueError("A dispute for this commission was already resolved")
        if comm.status != CommissionStatus.DISPUTED:
            comm.status = CommissionStatus.DISPUTED
            await db.flush()
        return existing

    row = Dispute(
        commission_id=body.commission_id,
        raised_by=raiser.id,
        reason=body.reason,
        status=DisputeStatus.OPEN
    )
    db.add(row)
    comm.status = CommissionStatus.DISPUTED
    await db.flush()
    return row


async def resolve_dispute(
        db: AsyncSession,
        dispute_id: uuid.UUID,
        body: DisputeResolve
) -> Dispute:
    drow = await get_dispute_by_id(db, dispute_id)
    if drow is None:
        raise ValueError("Dispute not found")

    if drow.status != DisputeStatus.OPEN:
        raise ValueError("Dispute is not open")

    rmod = await db.execute(
        select(User).where(User.discord_user_id == body.resolved_by_discord_user_id)
    )
    moderator = rmod.scalar_one_or_none()
    if moderator is None:
        raise ValueError("Moderator not found in database")

    rcomm = await db.execute(
        select(Commission).where(Commission.id == drow.commission_id)
    )
    comm_obj = rcomm.scalar_one_or_none()
    if comm_obj is None:
        raise ValueError("Commission missing")

    if comm_obj.status != CommissionStatus.DISPUTED:
        raise ValueError("Commission is not in DISPUTED status")

    target = (
        CommissionStatus.COMPLETED
        if body.set_commission_status == "COMPLETED"
        else CommissionStatus.CANCELLED
    )

    comm_obj.status = target
    if target == CommissionStatus.COMPLETED:
        now = _utcnow()
        comm_obj.completed_at = now
        quoted = comm_obj.quoted_price_php
        if quoted is not None:
            fee = (Decimal(str(quoted)) * PLATFORM_FEE_RATE).quantize(Decimal("0.01"))
            comm_obj.platform_fee_php = float(fee)
        else:
            comm_obj.platform_fee_php = None

    drow.status = DisputeStatus.RESOLVED
    drow.resolution = body.resolution
    drow.resolved_by = moderator.id
    drow.resolved_at = _utcnow()
    await db.flush()
    return drow