import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from api.commissions import service as commission_service
from api.commissions import uploads
from api.commissions.schemas import (
    CommissionCreate,
    CommissionFiles,
    CommissionRead,
    CounterOfferBody,
    IntakeSubmitBody,
    QuoteCreate,
    TicketOpenBody,
    TosAcceptBody,
)
from api.commissions.uploads import IncomingFile
from api.dependencies import BotAuth, DBSession
from shared.models.commission import PaymentMethod

router = APIRouter(prefix="/commissions", tags=["commissions"])


async def _incoming(file: UploadFile, max_bytes: int) -> IncomingFile:
    # One byte past the limit is enough to know it is too large, without
    # reading an arbitrarily big upload into memory.
    return IncomingFile(
        filename=file.filename or "upload",
        content=await file.read(max_bytes + 1),
        content_type=file.content_type
    )


@router.get(
    "/by-discord-channel/{discord_channel_id}",
    response_model=CommissionRead
)
async def get_commission_by_discord_channel(
        discord_channel_id: str,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    comm = await commission_service.get_commission_by_discord_channel_id(
        db,
        discord_channel_id
    )
    return CommissionRead.model_validate(comm)

# Scheduled sweeps. Each changes what is due and returns it, so the bot can
# announce it in the ticket.

@router.post("/sweeps/expire-unpaid", response_model=list[CommissionRead])
async def sweep_expire_unpaid(db: DBSession, _auth: BotAuth) -> list[CommissionRead]:
    commissions = await commission_service.expire_unpaid(db)
    return [CommissionRead.model_validate(c) for c in commissions]

@router.post("/sweeps/auto-accept", response_model=list[CommissionRead])
async def sweep_auto_accept(db: DBSession, _auth: BotAuth) -> list[CommissionRead]:
    commissions = await commission_service.auto_accept_deliveries(db)
    return [CommissionRead.model_validate(c) for c in commissions]

@router.post("/sweeps/payment-reminders", response_model=list[CommissionRead])
async def sweep_payment_reminders(db: DBSession, _auth: BotAuth) -> list[CommissionRead]:
    commissions = await commission_service.take_payment_reminders(db)
    return [CommissionRead.model_validate(c) for c in commissions]

@router.post("", response_model=CommissionRead, status_code=status.HTTP_201_CREATED)
async def create_commission(
        body: CommissionCreate,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    comm = await commission_service.create_commission(db, body)
    return CommissionRead.model_validate(comm)

@router.get("/{commission_id}", response_model=CommissionRead)
async def get_commission(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    comm = await commission_service.get_commission(db, commission_id)
    return CommissionRead.model_validate(comm)

@router.get("/{commission_id}/files", response_model=CommissionFiles)
async def get_commission_files(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> CommissionFiles:
    urls = await commission_service.get_file_urls(db, commission_id)
    return CommissionFiles(**urls)

@router.post("/{commission_id}/ticket", response_model=CommissionRead)
async def open_ticket(
        commission_id: uuid.UUID,
        body: TicketOpenBody,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    comm = await commission_service.open_ticket(
        db,
        commission_id,
        body.discord_ticket_channel_id
    )
    return CommissionRead.model_validate(comm)

@router.post("/{commission_id}/intake", response_model=CommissionRead)
async def submit_intake(
        commission_id: uuid.UUID,
        body: IntakeSubmitBody,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    comm = await commission_service.submit_intake(db, commission_id, body.notes)
    return CommissionRead.model_validate(comm)

@router.post("/{commission_id}/quote", response_model=CommissionRead)
async def apply_quote(
        commission_id: uuid.UUID,
        body: QuoteCreate,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    comm = await commission_service.apply_quote(db, commission_id, body)
    return CommissionRead.model_validate(comm)

@router.post("/{commission_id}/counter-offer", response_model=CommissionRead)
async def counter_offer(
        commission_id: uuid.UUID,
        body: CounterOfferBody,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    comm = await commission_service.request_counter_offer(
        db,
        commission_id,
        notes=body.notes
    )
    return CommissionRead.model_validate(comm)

@router.post("/{commission_id}/accept-quote", response_model=CommissionRead)
async def accept_quote(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    comm = await commission_service.accept_quote(db, commission_id)
    return CommissionRead.model_validate(comm)

@router.post("/{commission_id}/tos-accept", response_model=CommissionRead)
async def accept_tos(
        commission_id: uuid.UUID,
        db: DBSession,
        body: TosAcceptBody,
        _auth: BotAuth
) -> CommissionRead:
    comm = await commission_service.confirm_tos_acceptance(
        db,
        commission_id,
        body.tos_version_hash
    )
    return CommissionRead.model_validate(comm)

@router.post("/{commission_id}/receipt", response_model=CommissionRead)
async def upload_receipt(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth,
        file: UploadFile = File(...)
) -> CommissionRead:
    comm = await commission_service.upload_receipt(
        db,
        commission_id,
        await _incoming(file, uploads.MAX_RECEIPT_BYTES)
    )
    return CommissionRead.model_validate(comm)

@router.post("/{commission_id}/confirm-payment", response_model=CommissionRead)
async def confirm_payment(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth,
        method: Annotated[PaymentMethod | None, Query()] = None
) -> CommissionRead:
    comm = await commission_service.confirm_payment(
        db,
        commission_id,
        payment_method=method
    )
    return CommissionRead.model_validate(comm)

@router.post("/{commission_id}/wip-update", response_model=CommissionRead)
async def wip_update(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth,
        file: UploadFile = File(...),
        note: str | None = Form(default=None, max_length=2000)
) -> CommissionRead:
    comm = await commission_service.create_wip_update(
        db,
        commission_id,
        await _incoming(file, uploads.MAX_ARTWORK_BYTES),
        note
    )
    return CommissionRead.model_validate(comm)

@router.post("/{commission_id}/deliver", response_model=CommissionRead)
async def deliver(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth,
        file: UploadFile = File(...)
) -> CommissionRead:
    comm = await commission_service.deliver(
        db,
        commission_id,
        await _incoming(file, uploads.MAX_ARTWORK_BYTES)
    )
    return CommissionRead.model_validate(comm)

@router.post("/{commission_id}/complete", response_model=CommissionRead)
async def complete(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    comm = await commission_service.complete_commission(db, commission_id)
    return CommissionRead.model_validate(comm)

@router.post("/{commission_id}/cancel", response_model=CommissionRead)
async def cancel(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    comm = await commission_service.cancel_commission(db, commission_id)
    return CommissionRead.model_validate(comm)
