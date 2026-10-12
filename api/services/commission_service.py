from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.services import artist_service
from shared import storage
from shared.errors import Conflict, Forbidden, InvalidState, NotFound
from shared.models.artist import Artist, ArtistStatus
from shared.models.commission import Commission, CommissionStatus, PaymentMethod
from shared.models.server import Server
from shared.models.user import User
from shared.models.wip_update import WipUpdate
from shared.schemas.commission import (
    CommissionCreate,
    QuoteCreate,
    WipCreateBody,
)

PAYMENT_WINDOW_HOURS = 24
DELIVERY_AUTO_ACCEPT_HOURS = 48
PLATFORM_FEE_RATE = Decimal("0.03")

# The whole lifecycle. Every status change in the codebase goes through _transition,
# so a move that is not listed here cannot happen.
VALID_TRANSITIONS: dict[CommissionStatus, set[CommissionStatus]] = {
    CommissionStatus.INQUIRY: {CommissionStatus.INTAKE, CommissionStatus.CANCELLED},
    CommissionStatus.INTAKE: {CommissionStatus.QUOTED, CommissionStatus.CANCELLED},
    CommissionStatus.QUOTED: {
        CommissionStatus.TOS_PENDING,
        CommissionStatus.INTAKE,  # counter-offer
        CommissionStatus.CANCELLED,
    },
    CommissionStatus.TOS_PENDING: {CommissionStatus.PAYMENT_PENDING, CommissionStatus.CANCELLED},
    CommissionStatus.PAYMENT_PENDING: {
        CommissionStatus.IN_PROGRESS,
        CommissionStatus.DISPUTED,
        CommissionStatus.CANCELLED,
    },
    CommissionStatus.IN_PROGRESS: {CommissionStatus.WIP, CommissionStatus.DISPUTED},
    CommissionStatus.WIP: {CommissionStatus.DELIVERED, CommissionStatus.DISPUTED},
    CommissionStatus.DELIVERED: {CommissionStatus.COMPLETED, CommissionStatus.DISPUTED},
    CommissionStatus.COMPLETED: set(),
    CommissionStatus.DISPUTED: {CommissionStatus.COMPLETED, CommissionStatus.CANCELLED},
    CommissionStatus.CANCELLED: set(),
}

TERMINAL_STATUSES = (CommissionStatus.COMPLETED, CommissionStatus.CANCELLED)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _label(status: CommissionStatus) -> str:
    return status.value.replace("_", " ").lower()


def _transition(comm: Commission, to: CommissionStatus) -> None:
    """The only place a commission's status is assigned."""
    if to not in VALID_TRANSITIONS[comm.status]:
        if comm.status == CommissionStatus.DISPUTED:
            raise InvalidState(
                "This commission is under dispute; it is frozen until a moderator resolves it"
            )
        raise InvalidState(
            f"A commission that is {_label(comm.status)} cannot move to {_label(to)}"
        )
    comm.status = to


def _require_status(comm: Commission, *allowed: CommissionStatus, action: str) -> None:
    if comm.status in allowed:
        return
    if comm.status == CommissionStatus.DISPUTED:
        raise InvalidState(
            "This commission is under dispute; it is frozen until a moderator resolves it"
        )
    expected = " or ".join(_label(s) for s in allowed)
    raise InvalidState(
        f"{action} is only possible while the commission is {expected} "
        f"(it is {_label(comm.status)})"
    )


def mark_completed(comm: Commission) -> None:
    """Move to COMPLETED and record the completion time and platform fee."""
    _transition(comm, CommissionStatus.COMPLETED)
    comm.completed_at = _utcnow()
    if comm.quoted_price_php is not None:
        fee = (Decimal(str(comm.quoted_price_php)) * PLATFORM_FEE_RATE).quantize(Decimal("0.01"))
        comm.platform_fee_php = float(fee)
    else:
        comm.platform_fee_php = None


def mark_disputed(comm: Commission) -> None:
    _transition(comm, CommissionStatus.DISPUTED)


def mark_cancelled(comm: Commission) -> None:
    _transition(comm, CommissionStatus.CANCELLED)


# Reads

# Every commission handed to a caller carries its client and its artist's user,
# so the Discord IDs of both parties are always available.
_WITH_PARTIES = (
    joinedload(Commission.client, innerjoin=True),
    joinedload(Commission.artist, innerjoin=True).joinedload(Artist.user, innerjoin=True),
)


async def get_commission(db: AsyncSession, commission_id: uuid.UUID) -> Commission:
    result = await db.execute(
        select(Commission).options(*_WITH_PARTIES).where(Commission.id == commission_id)
    )
    comm = result.scalar_one_or_none()
    if comm is None:
        raise NotFound("Commission not found")
    return comm


async def get_commission_for_update(db: AsyncSession, commission_id: uuid.UUID) -> Commission:
    """Load and row-lock a commission so concurrent actions (a double-clicked
    button, a sweep racing a user) are applied one after the other."""
    result = await db.execute(
        select(Commission)
        .options(*_WITH_PARTIES)
        .where(Commission.id == commission_id)
        .with_for_update(of=Commission)
    )
    comm = result.scalar_one_or_none()
    if comm is None:
        raise NotFound("Commission not found")
    return comm


async def get_commission_by_discord_channel_id(
        db: AsyncSession,
        discord_channel_id: str,
) -> Commission:
    result = await db.execute(
        select(Commission)
        .options(*_WITH_PARTIES)
        .where(Commission.discord_ticket_channel_id == discord_channel_id)
    )
    comm = result.scalar_one_or_none()
    if comm is None:
        raise NotFound("No commission for this channel")
    return comm


async def get_file_urls(db: AsyncSession, commission_id: uuid.UUID) -> dict[str, str | None]:
    """Fresh, short-lived links to the commission's receipt and final file."""
    comm = await get_commission(db, commission_id)
    return {
        "receipt_url": (
            await storage.signed_url_for(comm.payment_receipt_key)
            if comm.payment_receipt_key else None
        ),
        "delivery_url": (
            await storage.signed_url_for(comm.delivery_file_key)
            if comm.delivery_file_key else None
        ),
    }


# Use cases

async def create_commission(db: AsyncSession, data: CommissionCreate) -> Commission:
    server = await db.scalar(select(Server).where(Server.id == data.server_id))
    if server is None:
        raise NotFound("Server not found")

    # Lock the artist row: the capacity check below must not race another request.
    artist = await db.scalar(
        select(Artist).where(Artist.id == data.artist_id).with_for_update()
    )
    if artist is None or artist.server_id != data.server_id:
        raise NotFound("Artist not found on this server")

    client_user = await db.scalar(select(User).where(User.id == data.client_id))
    if client_user is None:
        raise NotFound("Client user not found")

    if artist.status != ArtistStatus.ACTIVE:
        raise InvalidState("This artist is not accepting commissions right now")
    if artist.user_id == client_user.id:
        raise Forbidden("You cannot open a commission with yourself")

    if data.is_nsfw:
        if not client_user.is_18_verified:
            raise Forbidden("Client must complete 18+ verification before NSFW commissions")
        if not artist.nsfw_enabled:
            raise InvalidState("This artist has not enabled NSFW commissions")

    active = await artist_service.count_active_commissions_for_artist(db, artist.id)
    if active >= artist.max_active_commissions:
        raise Conflict("This artist has reached their maximum number of active commissions")

    comm = Commission(
        server_id=data.server_id,
        artist_id=data.artist_id,
        client_id=data.client_id,
        commission_type=data.commission_type,
        is_nsfw=data.is_nsfw,
        deadline_at=data.deadline_at,
        status=CommissionStatus.INQUIRY,
    )
    db.add(comm)
    await db.flush()
    return await get_commission(db, comm.id)


async def open_ticket(
        db: AsyncSession,
        commission_id: uuid.UUID,
        discord_ticket_channel_id: str
) -> Commission:
    """Attach the Discord ticket channel; the commission is now waiting for the brief."""
    comm = await get_commission_for_update(db, commission_id)
    _require_status(comm, CommissionStatus.INQUIRY, action="Opening a ticket")
    taken = await db.scalar(
        select(Commission.id).where(
            Commission.discord_ticket_channel_id == discord_ticket_channel_id
        )
    )
    if taken is not None:
        raise Conflict("That channel is already the ticket of another commission")
    comm.discord_ticket_channel_id = discord_ticket_channel_id
    _transition(comm, CommissionStatus.INTAKE)
    await db.flush()
    return comm


async def submit_intake(
        db: AsyncSession,
        commission_id: uuid.UUID,
        notes: str
) -> Commission:
    comm = await get_commission_for_update(db, commission_id)
    _require_status(comm, CommissionStatus.INTAKE, action="Submitting the brief")
    comm.client_intake_notes = notes
    await db.flush()
    return comm


async def apply_quote(
        db: AsyncSession,
        commission_id: uuid.UUID,
        quote: QuoteCreate
) -> Commission:
    comm = await get_commission_for_update(db, commission_id)
    _require_status(comm, CommissionStatus.INTAKE, action="Quoting")

    comm.quoted_price_php = float(quote.quoted_price_php)
    comm.quoted_price_usd = (
        float(quote.quoted_price_usd) if quote.quoted_price_usd is not None else None
    )
    comm.currency_used = quote.currency_used
    comm.revisions_allowed = quote.revisions_allowed
    if quote.deadline_at is not None:
        comm.deadline_at = quote.deadline_at

    _transition(comm, CommissionStatus.QUOTED)
    await db.flush()
    return comm


async def request_counter_offer(
        db: AsyncSession,
        commission_id: uuid.UUID,
        notes: str = ""
) -> Commission:
    """The client declines the quote and asks for a new one."""
    comm = await get_commission_for_update(db, commission_id)
    _require_status(comm, CommissionStatus.QUOTED, action="A counter-offer")

    if notes.strip():
        previous = comm.client_intake_notes or ""
        comm.client_intake_notes = f"{previous}\n\nCounter-offer: {notes.strip()}".strip()
    comm.quoted_price_php = None
    comm.quoted_price_usd = None
    comm.currency_used = None
    _transition(comm, CommissionStatus.INTAKE)
    await db.flush()
    return comm


async def accept_quote(db: AsyncSession, commission_id: uuid.UUID) -> Commission:
    comm = await get_commission_for_update(db, commission_id)
    _require_status(comm, CommissionStatus.QUOTED, action="Accepting the quote")
    _transition(comm, CommissionStatus.TOS_PENDING)
    await db.flush()
    return comm


async def confirm_tos_acceptance(
        db: AsyncSession,
        commission_id: uuid.UUID,
        tos_version_hash: str
) -> Commission:
    comm = await get_commission_for_update(db, commission_id)
    _require_status(comm, CommissionStatus.TOS_PENDING, action="Accepting the terms")

    artist = await db.scalar(select(Artist).where(Artist.id == comm.artist_id))
    if artist is None or not artist.tos_text:
        raise InvalidState("The artist has not set their terms of service yet")

    if tos_version_hash != artist_service.tos_hash(artist.tos_text):
        raise Conflict(
            "The artist's terms changed since they were shown to you; read them again"
        )

    now = _utcnow()
    comm.tos_accepted_at = now
    comm.tos_version_hash = tos_version_hash
    comm.payment_deadline_at = now + timedelta(hours=PAYMENT_WINDOW_HOURS)
    comm.payment_reminder_sent = False
    _transition(comm, CommissionStatus.PAYMENT_PENDING)
    await db.flush()
    return comm


async def upload_receipt(
        db: AsyncSession,
        commission_id: uuid.UUID,
        payment_receipt_key: str
) -> Commission:
    comm = await get_commission_for_update(db, commission_id)
    _require_status(comm, CommissionStatus.PAYMENT_PENDING, action="Uploading a receipt")
    comm.payment_receipt_key = payment_receipt_key
    await db.flush()
    return comm


async def confirm_payment(
        db: AsyncSession,
        commission_id: uuid.UUID,
        *,
        payment_method: PaymentMethod | None = None
) -> Commission:
    comm = await get_commission_for_update(db, commission_id)
    _require_status(comm, CommissionStatus.PAYMENT_PENDING, action="Confirming payment")
    comm.payment_confirmed_at = _utcnow()
    comm.payment_method = payment_method or PaymentMethod.GCASH
    _transition(comm, CommissionStatus.IN_PROGRESS)
    await db.flush()
    return comm


async def create_wip_update(
        db: AsyncSession,
        commission_id: uuid.UUID,
        body: WipCreateBody
) -> Commission:
    comm = await get_commission_for_update(db, commission_id)
    _require_status(
        comm,
        CommissionStatus.IN_PROGRESS,
        CommissionStatus.WIP,
        action="Posting a WIP update"
    )
    db.add(
        WipUpdate(
            commission_id=comm.id,
            image_key=body.image_key,
            artist_note=body.artist_note
        )
    )
    if comm.status == CommissionStatus.IN_PROGRESS:
        _transition(comm, CommissionStatus.WIP)
    await db.flush()
    return comm


async def deliver(
        db: AsyncSession,
        commission_id: uuid.UUID,
        file_key: str
) -> Commission:
    comm = await get_commission_for_update(db, commission_id)
    if comm.status == CommissionStatus.IN_PROGRESS:
        raise InvalidState("Post at least one WIP update before delivering the final file")
    _require_status(comm, CommissionStatus.WIP, action="Delivering")

    now = _utcnow()
    comm.delivery_file_key = file_key
    comm.delivered_at = now
    comm.delivery_auto_accept_at = now + timedelta(hours=DELIVERY_AUTO_ACCEPT_HOURS)
    _transition(comm, CommissionStatus.DELIVERED)
    await db.flush()
    return comm


async def complete_commission(db: AsyncSession, commission_id: uuid.UUID) -> Commission:
    comm = await get_commission_for_update(db, commission_id)
    _require_status(comm, CommissionStatus.DELIVERED, action="Completing")
    mark_completed(comm)
    await db.flush()
    return comm


async def cancel_commission(db: AsyncSession, commission_id: uuid.UUID) -> Commission:
    """Cancel before any money has changed hands. After payment a commission can
    only end through completion or a dispute."""
    comm = await get_commission_for_update(db, commission_id)
    if comm.status in (
        CommissionStatus.IN_PROGRESS,
        CommissionStatus.WIP,
        CommissionStatus.DELIVERED,
    ):
        raise InvalidState(
            "This commission has been paid for and can no longer be cancelled; "
            "raise a dispute instead"
        )
    # DISPUTED -> CANCELLED is a valid transition, but only as a moderator's ruling.
    _require_status(
        comm,
        CommissionStatus.INQUIRY,
        CommissionStatus.INTAKE,
        CommissionStatus.QUOTED,
        CommissionStatus.TOS_PENDING,
        CommissionStatus.PAYMENT_PENDING,
        action="Cancelling"
    )
    if comm.status == CommissionStatus.PAYMENT_PENDING and comm.payment_receipt_key:
        raise InvalidState(
            "A payment receipt has been uploaded; raise a dispute instead of cancelling"
        )
    mark_cancelled(comm)
    await db.flush()
    return comm


# Timers — called by the scheduled sweeps

async def cancel_commission_unpaid(
        db: AsyncSession,
        commission_id: uuid.UUID
) -> Commission | None:
    """Cancel a commission whose payment window has passed. Returns None when the
    commission no longer qualifies (paid, already cancelled, deadline moved)."""
    comm = await get_commission_for_update(db, commission_id)
    if comm.status != CommissionStatus.PAYMENT_PENDING:
        return None
    if comm.payment_deadline_at is None or comm.payment_deadline_at > _utcnow():
        return None
    mark_cancelled(comm)
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
        select(Commission).options(*_WITH_PARTIES).where(
            Commission.status == CommissionStatus.PAYMENT_PENDING,
            Commission.payment_deadline_at.is_not(None),
            Commission.payment_reminder_sent.is_(False),
            Commission.payment_deadline_at > now,
            Commission.payment_deadline_at <= window_end,
        )
    )
    return list(result.scalars().all())


async def mark_payment_reminder_sent(db: AsyncSession, commission_id: uuid.UUID) -> None:
    comm = await get_commission_for_update(db, commission_id)
    comm.payment_reminder_sent = True
    await db.flush()
