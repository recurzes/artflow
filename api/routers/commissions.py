import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from api.dependencies import BotAuth, DBSession
from api.services import commission_service, review_service
from shared.models.commission import PaymentMethod
from shared.schemas.commission import (
    CommissionCreate,
    CommissionFiles,
    CommissionRead,
    CounterOfferBody,
    DeliverySubmitBody,
    IntakeSubmitBody,
    QuoteCreate,
    ReceiptUploadBody,
    TicketOpenBody,
    TosAcceptBody,
    WipCreateBody,
)
from shared.schemas.review import ReviewCreate, ReviewRead

router = APIRouter(prefix="/commissions", tags=["commissions"])


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
        body: ReceiptUploadBody,
        _auth: BotAuth
) -> CommissionRead:
    comm = await commission_service.upload_receipt(
        db,
        commission_id,
        body.payment_receipt_key
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
        body: WipCreateBody,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    comm = await commission_service.create_wip_update(db, commission_id, body)
    return CommissionRead.model_validate(comm)

@router.post("/{commission_id}/deliver", response_model=CommissionRead)
async def deliver(
        commission_id: uuid.UUID,
        body: DeliverySubmitBody,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    comm = await commission_service.deliver(db, commission_id, body.file_key)
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

@router.post(
    "/{commission_id}/review",
    response_model=ReviewRead,
    status_code=status.HTTP_201_CREATED
)
async def create_commission_review(
        commission_id: uuid.UUID,
        body: ReviewCreate,
        db: DBSession,
        _auth: BotAuth
) -> ReviewRead:
    review = await review_service.create_review(db, commission_id, body)
    return ReviewRead.model_validate(review)
