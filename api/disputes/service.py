from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from api.artists import service as artist_service
from api.commissions import service as commission_service
from api.disputes import repository
from api.disputes.schemas import DisputeCreate, DisputeResolve
from api.users import service as user_service
from shared.errors import Conflict, Forbidden, InvalidState, NotFound
from shared.models.commission import CommissionStatus
from shared.models.dispute import Dispute, DisputeStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_dispute(db: AsyncSession, dispute_id: uuid.UUID) -> Dispute:
    dispute = await repository.get_by_id_for_update(db, dispute_id)
    if dispute is None:
        raise NotFound("Dispute not found")
    return dispute


async def require_dispute_for_commission(
        db: AsyncSession,
        commission_id: uuid.UUID
) -> Dispute:
    dispute = await repository.get_by_commission_id(db, commission_id)
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
    artist = await artist_service.get_artist(db, comm.artist_id)
    if raiser.id not in (comm.client_id, artist.user_id):
        raise Forbidden("Only the client or the artist can open a dispute")

    existing = await repository.get_by_commission_id(db, body.commission_id)
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

    return await repository.add(
        db,
        Dispute(
            commission_id=body.commission_id,
            raised_by=raiser.id,
            reason=body.reason,
            status=DisputeStatus.OPEN
        )
    )


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
