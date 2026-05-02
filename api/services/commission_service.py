from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.artist import Artist
from shared.models.commission import Commission, CommissionStatus, PaymentMethod
from shared.models.server import Server
from shared.models.user import User
from shared.models.wip_update import WipUpdate
from shared.schemas.commission import (
    CommissionCreate,
    CommissionStatusUpdate,
    QuoteCreate,
    WipCreateBody,
)

PAYMENT_WINDOW_HOURS = 24
DELIVERY_AUTO_ACCEPT_HOURS = 48
PLATFORM_FEE_RATE = Decimal("0.03")

VALID_TRANSITIONS: dict[CommissionStatus, set[CommissionStatus]] = {
    CommissionStatus.INQUIRY: {CommissionStatus.INTAKE, CommissionStatus.CANCELLED},
    CommissionStatus.INTAKE: {CommissionStatus.QUOTED, CommissionStatus.CANCELLED},
    CommissionStatus.QUOTED: {CommissionStatus.TOS_PENDING, CommissionStatus.CANCELLED},
    CommissionStatus.TOS_PENDING: {CommissionStatus.PAYMENT_PENDING, CommissionStatus.CANCELLED},
    CommissionStatus.PAYMENT_PENDING: {CommissionStatus.IN_PROGRESS, CommissionStatus.CANCELLED},
    CommissionStatus.IN_PROGRESS: {CommissionStatus.WIP, CommissionStatus.DISPUTED},
    CommissionStatus.WIP: {CommissionStatus.DELIVERED, CommissionStatus.DISPUTED},
    CommissionStatus.DELIVERED: {CommissionStatus.COMPLETED, CommissionStatus.DISPUTED},
    CommissionStatus.COMPLETED: set(),
    CommissionStatus.DISPUTED: {CommissionStatus.COMPLETED, CommissionStatus.CANCELLED},
    CommissionStatus.CANCELLED: set(),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _tos_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _block_if_disputed(comm: Commission) -> None:
    if comm.status == CommissionStatus.DISPUTED:
        raise ValueError(
            "This commission is under dispute; this action is frozen until a moderator resolves it"
        )


async def get_commission(db: AsyncSession, commission_id: uuid.UUID) -> Commission | None:
    result = await db.execute(select(Commission).where(Commission.id == commission_id))
    return result.scalar_one_or_none()


async def get_commission_by_discord_channel_id(
        db: AsyncSession,
        discord_channel_id: str,
) -> Commission | None:
    result = await db.execute(
        select(Commission).where(Commission.discord_ticket_channel_id == discord_channel_id)
    )
    return result.scalar_one_or_none()


async def create_commission(db: AsyncSession, data: CommissionCreate) -> Commission:
    s = await db.execute(select(Server).where(Server.id == data.server_id))
    if s.scalar_one_or_none() is None:
        raise ValueError("Server not found")

    a = await db.execute(select(Artist).where(Artist.id) == data.artist_id)
    artist = a.scalar_one_or_none()
    if artist is None:
        raise ValueError("Artist now found")

    u = await db.execute(select(User).where(User.id == data.client_id))
    client_user = u.scalar_one_or_none()
    if client_user is None:
        raise ValueError("Client user not found")

    if data.is_nsfw:
        if not client_user.is_user_18_verified:
            raise ValueError(
                "Client must complete 18+ verification before NSFW commissions"
            )
        if not artist.nsfw_enabled:
            raise ValueError("This artist has not enabled NSFW commissions")

    comm = Commission(
        server_id=data.server_id,
        artist_id=data.artist_id,
        client_id=data.client_id,
        commission_type=data.commission_type,
        is_nsfw=data.is_nsfw,
        deadline_at=data.deadline_at,
        discord_ticket_channel_id=data.discord_ticket_channel_id,
        status=CommissionStatus.INQUIRY,
    )
    db.add(comm)
    await db.flush()
    return comm


def _can_transition(current: CommissionStatus, new: CommissionStatus) -> bool:
    return new in VALID_TRANSITIONS.get(current, set[CommissionStatus]())


async def transition_status(
        db: AsyncSession,
        commission_id: uuid.UUID,
        body: CommissionStatusUpdate
) -> Commission:
    comm = await get_commission(db, commission_id)
    if comm is None:
        raise ValueError("Commission not found")
    _block_if_disputed(comm)

    new_status = body.status
    if not _can_transition(comm.status, new_status):
        raise ValueError(
            f"Invalid transition from {comm.status.value} to {new_status.value}"
        )

    comm.status = new_status
    if body.payment_method is not None:
        comm.payment_method = body.payment_method
    if body.payment_receipt_url is not None:
        comm.payment_receipt_url = body.payment_receipt_url

    await db.flush()
    return comm


async def submit_intake(
        db: AsyncSession,
        commission_id: uuid.UUID,
        notes: str
) -> Commission:
    comm = await get_commission(db, commission_id)
    if comm is None:
        raise ValueError("Commission not found")
    _block_if_disputed(comm)
    if comm.status != CommissionStatus.INTAKE:
        raise ValueError("Intake can only be submitted while commission is in INTAKE status")
    comm.client_intake_notes = notes
    await db.flush()
    return comm


async def request_counter_offer(
        db: AsyncSession,
        commission_id: uuid.UUID,
        notes: str = ""
) -> Commission:
    comm = await get_commission(db, commission_id)
    if comm is None:
        raise ValueError("Commission not found")
    _block_if_disputed(comm)
    if comm.status != CommissionStatus.QUOTED:
        raise ValueError("Counter-offer is only valid while commission is QUOTED")

    if not _can_transition(comm.status, CommissionStatus.INTAKE):
        raise ValueError("Cannot return to INTAKE from current status")

    comm.quoted_price_php = None
    comm.quoted_price_usd = None
    comm.currency_used = None
    comm.deadline_at = None
    comm.status = CommissionStatus.INTAKE
    await db.flush()
    return comm


async def apply_quote(
        db: AsyncSession,
        commission_id: uuid.UUID,
        quote: QuoteCreate
) -> Commission:
    comm = await get_commission(db, commission_id)
    if comm is None:
        raise ValueError("Commission not found")
    _block_if_disputed(comm)
    if comm.status != CommissionStatus.INTAKE:
        raise ValueError("Quote can only be applied while commission is in INTAKE status")

    comm.quoted_price_php = float(quote.quoted_price_php)
    if quote.quoted_price_usd is not None:
        comm.quoted_price_usd = float(quote.quoted_price_usd)
    comm.currency_used = quote.currency_used
    comm.revisions_allowed = quote.revisions_allowed
    if quote.deadline_at is not None:
        comm.deadline_at = quote.deadline_at

    if not _can_transition(comm.status, CommissionStatus.QUOTED):
        raise ValueError("Cannot move to QUOTED from current status")
    comm.status = CommissionStatus.QUOTED
    await db.flush()
    return comm


async def confirm_tos_acceptance(
        db: AsyncSession,
        commission_id: uuid.UUID,
        tos_version_hash: str
) -> Commission:
    comm = await get_commission(db, commission_id)
    if comm is None:
        raise ValueError("Commission not found")
    _block_if_disputed(comm)
    if comm.status != CommissionStatus.TOS_PENDING:
        raise ValueError("TOS can only be accepted in TOS_PENDING status")

    result = await db.execute(
        select(Artist).where(Artist.id == comm.artist_id)
    )
    artist = result.scalar_one_or_none()
    if artist is None or not artist.tos_text:
        raise ValueError("Artist has no TOS text configured")

    expected = _tos_hash(artist.tos_text)
    if tos_version_hash != expected:
        raise ValueError("TOS hash does not match the artist's current TOS text")

    if not _can_transition(comm.status, CommissionStatus.PAYMENT_PENDING):
        raise ValueError("Invalid transition to PAYMENT_PENDING")

    now = _utcnow()
    comm.tos_accepted_at = now
    comm.tos_version_hash = tos_version_hash
    comm.status = CommissionStatus.PAYMENT_PENDING
    comm.payment_deadline_at = now + timedelta(hours=PAYMENT_WINDOW_HOURS)
    comm.payment_reminder_sent = False
    await db.flush()
    return comm


async def upload_receipt(
        db: AsyncSession,
        commission_id: uuid.UUID,
        payment_receipt_url: str
) -> Commission:
    comm = await get_commission(db, commission_id)
    if comm is None:
        raise ValueError("Commission not found")
    _block_if_disputed(comm)
    if comm.status != CommissionStatus.PAYMENT_PENDING:
        raise ValueError("Receipt can only be uploaded in PAYMENT_PENDING status")

    comm.payment_receipt_url = payment_receipt_url
    await db.flush()
    return comm


async def confirm_payment(
        db: AsyncSession,
        commission_id: uuid.UUID,
        *,
        payment_method: PaymentMethod | None = None
) -> Commission:
    comm = await get_commission(db, commission_id)
    if comm is None:
        raise ValueError("Commission not found")
    _block_if_disputed(comm)
    if comm.status != CommissionStatus.PAYMENT_PENDING:
        raise ValueError("Payment can only be confirmed in PAYMENT_PENDING status")

    if not _can_transition(comm.status, CommissionStatus.IN_PROGRESS):
        raise ValueError("Invalid transition to IN_PROGRESS")

    comm.payment_confirmed_at = _utcnow()
    comm.payment_method = payment_method or PaymentMethod.GCASH

    comm.status = CommissionStatus.IN_PROGRESS
    await db.flush()
    return comm


async def create_wip_update(
        db: AsyncSession,
        commission_id: uuid.UUID,
        body: WipCreateBody
) -> Commission:
    comm = await get_commission(db, commission_id)
    if comm is None:
        raise ValueError("Commission not found")
    _block_if_disputed(comm)
    if comm.status not in (CommissionStatus.IN_PROGRESS, CommissionStatus.WIP):
        raise ValueError("WIP updates are only allowed in IN_PROGRESS or WIP status")

    wip = WipUpdate(
        commission_id=comm.id,
        image_url=body.image_url,
        artist_note=body.artist_note
    )
    db.add(wip)

    if comm.status == CommissionStatus.IN_PROGRESS:
        if not _can_transition(comm.status, CommissionStatus.WIP):
            raise ValueError("Cannot transition to WIP")
        comm.status = CommissionStatus.WIP

    await db.flush()
    return comm


async def deliver(
        db: AsyncSession,
        commission_id: uuid.UUID,
        final_file_url: str
) -> Commission:
    comm = await get_commission(db, commission_id)
    if comm is None:
        raise ValueError("Commission not found")
    _block_if_disputed(comm)
    if comm.status != CommissionStatus.WIP:
        raise ValueError("Delivery is only allowed from WIP status")

    if not _can_transition(comm.status, CommissionStatus.DELIVERED):
        raise ValueError("Invalid transition to DELIVERED")

    now = _utcnow()
    comm.delivery_file_url = final_file_url
    comm.delivered_at = now
    comm.delivery_auto_accept_at = now + timedelta(hours=DELIVERY_AUTO_ACCEPT_HOURS)
    comm.status = CommissionStatus.DELIVERED
    await db.flush()
    return comm


async def complete_commission(db: AsyncSession, commission_id: uuid.UUID) -> Commission:
    comm = await get_commission(db, commission_id)
    if comm is None:
        raise ValueError("Commission not found")
    _block_if_disputed(comm)
    if comm.status != CommissionStatus.DELIVERED:
        raise ValueError("Complete is only valid from DELIVERED status")

    if not _can_transition(comm.status, CommissionStatus.COMPLETED):
        raise ValueError("Invalid transition to COMPLETED")

    now = _utcnow()
    comm.completed_at = now
    comm.status = CommissionStatus.COMPLETED

    quoted = comm.quoted_price_php
    if quoted is not None:
        fee = (Decimal(str(quoted)) * PLATFORM_FEE_RATE).quantize(Decimal("0.01"))
        comm.platform_fee_php = float(fee)
    else:
        comm.platform_fee_php = None

    await db.flush()
    return comm


async def cancel_commission_unpaid(db: AsyncSession, commission_id: uuid.UUID) -> Commission:
    comm = await get_commission(db, commission_id)
    if comm is None:
        return None
    if comm.status != CommissionStatus.PAYMENT_PENDING:
        return None
    if comm.payment_deadline_at is None or comm.payment_deadline_at > _utcnow():
        return None
    if not _can_transition(comm.status, CommissionStatus.CANCELLED):
        return None
    comm.status = CommissionStatus.CANCELLED
    await db.flush()
    return comm


async def list_payment_overdue_ids(db: AsyncSession) -> list[uuid.UUID]:
    now = _utcnow()
    result = await db.execute(
        select(Commission.id).where(
            Commission.status == CommissionStatus.PAYMENT_PENDING,
            Commission.payment_deadline_at.is_not(None),
            Commission.payment_deadline_at < now
        )
    )
    return [row[0] for row in result.all()]


async def list_delivery_auto_accept_ids(db: AsyncSession) -> list[uuid.UUID]:
    now = _utcnow()
    result = await db.execute(
        select(Commission.id).where(
            Commission.status == CommissionStatus.DELIVERED,
            Commission.delivery_auto_accept_at.is_not(None),
            Commission.delivery_auto_accept_at < now,
        )
    )
    return [row[0] for row in result.all()]


async def list_payment_reminder_candidates(db: AsyncSession) -> list[Commission]:
    now = _utcnow()
    window_end = now + timedelta(hours=12)
    result = await db.execute(
        select(Commission).where(
            Commission.status == CommissionStatus.PAYMENT_PENDING,
            Commission.payment_deadline_at.is_not(None),
            Commission.payment_reminder_sent.is_(False),
            Commission.payment_deadline_at > now,
            Commission.payment_deadline_at <= window_end,
        )
    )
    return list[Commission](result.scalars().all())


async def mark_payment_reminder_sent(db: AsyncSession, commission_id: uuid.UUID) -> None:
    comm = await get_commission(db, commission_id)
    if comm:
        comm.payment_reminder_sent = True
        await db.flush()