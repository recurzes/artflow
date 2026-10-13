from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from api.artists import service as artist_service
from api.commissions import exchange_rates, repository, uploads
from api.commissions.schemas import CommissionCreate, QuoteCreate
from api.commissions.uploads import IncomingFile
from api.servers import service as server_service
from api.users import service as user_service
from shared import storage
from shared.errors import Conflict, Forbidden, InvalidState, NotFound
from shared.models.artist import ArtistStatus
from shared.models.commission import Commission, CommissionStatus, PaymentMethod
from shared.models.wip_update import WipUpdate

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


def _require_party(
        comm: Commission,
        actor: str,
        role: Literal["client", "artist"],
        action: str
) -> None:
    """Refuse unless `actor` (a Discord user ID) is that party of the commission.

    The bot passes along who pressed the button; the rule about who may do
    what lives here, not in the bot.
    """
    expected = (
        comm.client_discord_user_id if role == "client" else comm.artist_discord_user_id
    )
    if actor != expected:
        raise Forbidden(f"Only the {role} can {action}")


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

async def get_commission(db: AsyncSession, commission_id: uuid.UUID) -> Commission:
    comm = await repository.get_by_id(db, commission_id)
    if comm is None:
        raise NotFound("Commission not found")
    return comm


async def get_commission_for_update(db: AsyncSession, commission_id: uuid.UUID) -> Commission:
    """Load and row-lock a commission so concurrent actions (a double-clicked
    button, a sweep racing a user) are applied one after the other."""
    comm = await repository.get_by_id(db, commission_id, for_update=True)
    if comm is None:
        raise NotFound("Commission not found")
    return comm


async def get_commission_by_discord_channel_id(
        db: AsyncSession,
        discord_channel_id: str,
) -> Commission:
    comm = await repository.get_by_ticket_channel(db, discord_channel_id)
    if comm is None:
        raise NotFound("No commission for this channel")
    return comm


async def get_artist_capacity(db: AsyncSession, artist_id: uuid.UUID) -> tuple[int, int]:
    """(commissions currently occupying a slot, the artist's limit)."""
    artist = await artist_service.get_artist(db, artist_id)
    active = await repository.count_active_for_artist(db, artist_id)
    return active, artist.max_active_commissions


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
    await server_service.get_server(db, data.server_id)

    # Locked: the capacity check below must not race another request.
    try:
        artist = await artist_service.get_artist_for_update(db, data.artist_id)
    except NotFound:
        artist = None
    if artist is None or artist.server_id != data.server_id:
        raise NotFound("Artist not found on this server")

    try:
        client_user = await user_service.get_user(db, data.client_id)
    except NotFound as exc:
        raise NotFound("Client user not found") from exc

    if artist.status != ArtistStatus.ACTIVE:
        raise InvalidState("This artist is not accepting commissions right now")
    if artist.user_id == client_user.id:
        raise Forbidden("You cannot open a commission with yourself")

    if data.is_nsfw:
        if not client_user.is_18_verified:
            raise Forbidden("Client must complete 18+ verification before NSFW commissions")
        if not artist.nsfw_enabled:
            raise InvalidState("This artist has not enabled NSFW commissions")

    active = await repository.count_active_for_artist(db, artist.id)
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
    await repository.add(db, comm)
    return await get_commission(db, comm.id)


async def open_ticket(
        db: AsyncSession,
        commission_id: uuid.UUID,
        discord_ticket_channel_id: str
) -> Commission:
    """Attach the Discord ticket channel; the commission is now waiting for the brief."""
    comm = await get_commission_for_update(db, commission_id)
    _require_status(comm, CommissionStatus.INQUIRY, action="Opening a ticket")
    if await repository.ticket_channel_in_use(db, discord_ticket_channel_id):
        raise Conflict("That channel is already the ticket of another commission")
    comm.discord_ticket_channel_id = discord_ticket_channel_id
    _transition(comm, CommissionStatus.INTAKE)
    await db.flush()
    return comm


async def submit_intake(
        db: AsyncSession,
        commission_id: uuid.UUID,
        actor: str,
        notes: str
) -> Commission:
    comm = await get_commission_for_update(db, commission_id)
    _require_party(comm, actor, "client", "submit the brief")
    _require_status(comm, CommissionStatus.INTAKE, action="Submitting the brief")
    comm.client_intake_notes = notes
    await db.flush()
    return comm


async def apply_quote(
        db: AsyncSession,
        commission_id: uuid.UUID,
        actor: str,
        quote: QuoteCreate
) -> Commission:
    # Looked up before the row is locked: it may be a network call.
    price_usd = quote.quoted_price_usd
    if price_usd is None:
        price_usd = await exchange_rates.php_to_usd(quote.quoted_price_php)

    comm = await get_commission_for_update(db, commission_id)
    _require_party(comm, actor, "artist", "send a quote")
    _require_status(comm, CommissionStatus.INTAKE, action="Quoting")

    comm.quoted_price_php = float(quote.quoted_price_php)
    comm.quoted_price_usd = float(price_usd) if price_usd is not None else None
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
        actor: str,
        notes: str = ""
) -> Commission:
    """The client declines the quote and asks for a new one."""
    comm = await get_commission_for_update(db, commission_id)
    _require_party(comm, actor, "client", "counter the quote")
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


async def accept_quote(db: AsyncSession, commission_id: uuid.UUID, actor: str) -> Commission:
    comm = await get_commission_for_update(db, commission_id)
    _require_party(comm, actor, "client", "accept the quote")
    _require_status(comm, CommissionStatus.QUOTED, action="Accepting the quote")
    _transition(comm, CommissionStatus.TOS_PENDING)
    await db.flush()
    return comm


async def confirm_tos_acceptance(
        db: AsyncSession,
        commission_id: uuid.UUID,
        actor: str,
        tos_version_hash: str
) -> Commission:
    comm = await get_commission_for_update(db, commission_id)
    _require_party(comm, actor, "client", "accept the terms")
    _require_status(comm, CommissionStatus.TOS_PENDING, action="Accepting the terms")

    artist = await artist_service.get_artist(db, comm.artist_id)
    if not artist.tos_text:
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
        actor: str,
        file: IncomingFile
) -> Commission:
    uploads.check(file, allowed_types=uploads.RECEIPT_TYPES, max_bytes=uploads.MAX_RECEIPT_BYTES)
    comm = await get_commission_for_update(db, commission_id)
    _require_party(comm, actor, "client", "upload the receipt")
    # Checked before anything is stored, so a refused request leaves no file behind.
    _require_status(comm, CommissionStatus.PAYMENT_PENDING, action="Uploading a receipt")
    comm.payment_receipt_key = await storage.upload_receipt(
        file.content,
        file.filename,
        str(comm.id)
    )
    await db.flush()
    return comm


async def confirm_payment(
        db: AsyncSession,
        commission_id: uuid.UUID,
        actor: str,
        *,
        payment_method: PaymentMethod | None = None
) -> Commission:
    comm = await get_commission_for_update(db, commission_id)
    _require_party(comm, actor, "artist", "confirm payment")
    _require_status(comm, CommissionStatus.PAYMENT_PENDING, action="Confirming payment")
    comm.payment_confirmed_at = _utcnow()
    comm.payment_method = payment_method or PaymentMethod.GCASH
    _transition(comm, CommissionStatus.IN_PROGRESS)
    await db.flush()
    return comm


async def create_wip_update(
        db: AsyncSession,
        commission_id: uuid.UUID,
        actor: str,
        file: IncomingFile,
        note: str | None = None
) -> Commission:
    uploads.check(file, allowed_types=uploads.IMAGE_TYPES, max_bytes=uploads.MAX_ARTWORK_BYTES)
    comm = await get_commission_for_update(db, commission_id)
    _require_party(comm, actor, "artist", "post a WIP update")
    _require_status(
        comm,
        CommissionStatus.IN_PROGRESS,
        CommissionStatus.WIP,
        action="Posting a WIP update"
    )
    image_key = await storage.upload_wip_image(file.content, file.filename, str(comm.id))
    await repository.add_wip_update(
        db,
        WipUpdate(
            commission_id=comm.id,
            image_key=image_key,
            artist_note=note
        )
    )
    if comm.status == CommissionStatus.IN_PROGRESS:
        _transition(comm, CommissionStatus.WIP)
    await db.flush()
    return comm


async def deliver(
        db: AsyncSession,
        commission_id: uuid.UUID,
        actor: str,
        file: IncomingFile
) -> Commission:
    uploads.check(file, allowed_types=None, max_bytes=uploads.MAX_ARTWORK_BYTES)
    comm = await get_commission_for_update(db, commission_id)
    _require_party(comm, actor, "artist", "deliver")
    if comm.status == CommissionStatus.IN_PROGRESS:
        raise InvalidState("Post at least one WIP update before delivering the final file")
    _require_status(comm, CommissionStatus.WIP, action="Delivering")

    now = _utcnow()
    comm.delivery_file_key = await storage.upload_delivery_file(
        file.content,
        file.filename,
        str(comm.id)
    )
    comm.delivered_at = now
    comm.delivery_auto_accept_at = now + timedelta(hours=DELIVERY_AUTO_ACCEPT_HOURS)
    _transition(comm, CommissionStatus.DELIVERED)
    await db.flush()
    return comm


async def complete_commission(db: AsyncSession, commission_id: uuid.UUID, actor: str) -> Commission:
    comm = await get_commission_for_update(db, commission_id)
    _require_party(comm, actor, "client", "accept the delivery")
    _require_status(comm, CommissionStatus.DELIVERED, action="Completing")
    mark_completed(comm)
    await db.flush()
    return comm


async def cancel_commission(
        db: AsyncSession,
        commission_id: uuid.UUID,
        actor: str,
        *,
        as_staff: bool = False
) -> Commission:
    """Cancel before any money has changed hands. After payment a commission can
    only end through completion or a dispute."""
    comm = await get_commission_for_update(db, commission_id)
    is_party = actor in (comm.client_discord_user_id, comm.artist_discord_user_id)
    if not is_party and not as_staff:
        raise Forbidden("Only the client, the artist or a moderator can cancel")
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


# Scheduled sweeps
#
# Each returns the commissions it acted on, so the caller can tell the people
# involved. They are safe to run as often as you like and from more than one
# place: every commission is re-checked under a row lock before it is changed.

PAYMENT_REMINDER_WINDOW = timedelta(hours=12)


async def expire_unpaid(db: AsyncSession) -> list[Commission]:
    """Cancel commissions whose payment window passed with no receipt uploaded.

    A commission with a receipt is left alone even when the artist has not
    confirmed it: the client may have paid, and that is a dispute, not a lapse.
    """
    cancelled: list[Commission] = []
    for commission_id in await repository.list_unpaid_past_deadline(db, _utcnow()):
        comm = await get_commission_for_update(db, commission_id)
        if (
            comm.status != CommissionStatus.PAYMENT_PENDING
            or comm.payment_receipt_key is not None
            or comm.payment_deadline_at is None
            or comm.payment_deadline_at > _utcnow()
        ):
            continue  # changed since it was selected
        mark_cancelled(comm)
        cancelled.append(comm)
    await db.flush()
    return cancelled


async def auto_accept_deliveries(db: AsyncSession) -> list[Commission]:
    """Complete deliveries the client neither accepted nor disputed in time."""
    completed: list[Commission] = []
    for commission_id in await repository.list_deliveries_past_auto_accept(db, _utcnow()):
        comm = await get_commission_for_update(db, commission_id)
        if (
            comm.status != CommissionStatus.DELIVERED
            or comm.delivery_auto_accept_at is None
            or comm.delivery_auto_accept_at > _utcnow()
        ):
            continue
        mark_completed(comm)
        completed.append(comm)
    await db.flush()
    return completed


async def take_payment_reminders(db: AsyncSession) -> list[Commission]:
    """Commissions whose payment deadline is near and that have not been
    reminded yet. They are marked as reminded here, so each is returned once."""
    now = _utcnow()
    due = await repository.list_unreminded_with_deadline_between(
        db,
        now,
        now + PAYMENT_REMINDER_WINDOW
    )
    reminded: list[Commission] = []
    for commission_id in due:
        comm = await get_commission_for_update(db, commission_id)
        if comm.status != CommissionStatus.PAYMENT_PENDING or comm.payment_reminder_sent:
            continue
        comm.payment_reminder_sent = True
        reminded.append(comm)
    await db.flush()
    return reminded
