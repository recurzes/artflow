from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services import commission_service
from api.users import service as user_service
from shared.errors import Conflict, Forbidden, InvalidState, NotFound
from shared.models.artist import Artist
from shared.models.commission import CommissionStatus
from shared.models.dispute import Dispute, DisputeStatus
from shared.schemas.dispute import DisputeCreate, DisputeResolve


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_dispute(db: AsyncSession, dispute_id: uuid.UUID) -> Dispute:
    dispute = await db.scalar(
        select(Dispute).where(Dispute.id == dispute_id).with_for_update()
    )
    if dispute is None:
        raise NotFound("Dispute not found")
    return dispute


async def get_dispute_by_commission_id(
        db: AsyncSession,
        commission_id: uuid.UUID
) -> Dispute | None:
    return await db.scalar(select(Dispute).where(Dispute.commission_id == commission_id))


async def require_dispute_for_commission(
        db: AsyncSession,
        commission_id: uuid.UUID
) -> Dispute:
    dispute = await get_dispute_by_commission_id(db, commission_id)
    if dispute is None:
        raise NotFound("There is no dispute on this commission")
    return dispute


async def open_dispute(
        db: AsyncSession,
        body: DisputeCreate
) -> Dispute:
    raiser = await user_service.get_user_by_discord_id(db, body.raised_by_discord_user_id)
    if raiser is None:
        raise NotFound("Accept the server terms before raising a dispute")

    comm = await commission_service.get_commission_for_update(db, body.commission_id)
    artist = await db.scalar(select(Artist).where(Artist.id == comm.artist_id))
    is_client = comm.client_id == raiser.id
    is_artist = artist is not None and artist.user_id == raiser.id
    if not is_client and not is_artist:
        raise Forbidden("Only the client or the artist can open a dispute")

    existing = await get_dispute_by_commission_id(db, body.commission_id)
    if existing is not None:
        if existing.status == DisputeStatus.RESOLVED:
            raise Conflict("A dispute for this commission was already resolved")
        return existing

    if comm.status == CommissionStatus.PAYMENT_PENDING and not comm.payment_receipt_key:
        raise InvalidState(
            "Nothing has been paid yet, so there is nothing to dispute; "
            "upload the payment receipt first"
        )
    commission_service.mark_disputed(comm)

    dispute = Dispute(
        commission_id=body.commission_id,
        raised_by=raiser.id,
        reason=body.reason,
        status=DisputeStatus.OPEN
    )
    db.add(dispute)
    await db.flush()
    return dispute


async def resolve_dispute(
        db: AsyncSession,
        dispute_id: uuid.UUID,
        body: DisputeResolve
) -> Dispute:
    dispute = await get_dispute(db, dispute_id)
    if dispute.status == DisputeStatus.RESOLVED:
        raise Conflict("This dispute was already resolved")

    # A moderator may never have gone through member verification; register them.
    moderator = await user_service.upsert_user(
        db,
        discord_user_id=body.resolved_by_discord_user_id
    )

    comm = await commission_service.get_commission_for_update(db, dispute.commission_id)
    if body.set_commission_status == "COMPLETED":
        commission_service.mark_completed(comm)
    else:
        commission_service.mark_cancelled(comm)

    dispute.status = DisputeStatus.RESOLVED
    dispute.resolution = body.resolution
    dispute.resolved_by = moderator.id
    dispute.resolved_at = _utcnow()
    await db.flush()
    return dispute
