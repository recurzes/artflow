import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from api.dependencies import BotAuth, DBSession
from api.services import commission_service
from shared.models.commission import PaymentMethod
from shared.schemas.commission import (
    CommissionCreate,
    CommissionRead,
    CommissionStatusUpdate,
    DeliverySubmitBody,
    QuoteCreate,
    ReceiptUploadBody,
    TosAcceptBody,
    WipCreateBody,
)

router = APIRouter(prefix="/commissions", tags=["commissions"])


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


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
    if comm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No commission for this channel"
        )
    return CommissionRead.model_validate(comm)

@router.post("", response_model=CommissionRead, status_code=status.HTTP_201_CREATED)
async def create_commission(
        body: CommissionCreate,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    try:
        comm = await commission_service.create_commission(db, body)
        return CommissionRead.model_validate(comm)
    except ValueError as e:
        raise _bad_request(e) from e

@router.get("/{commission_id}", response_model=CommissionRead)
async def get_commission(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    comm = await commission_service.get_commission(db, commission_id)
    if comm is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return CommissionRead.model_validate(comm)

@router.patch("/{commission_id}/status", response_model=CommissionRead)
async def update_commission_status(
        commission_id: uuid.UUID,
        body: CommissionStatusUpdate,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    try:
        comm = await commission_service.transition_status(db, commission_id, body)
        return CommissionRead.model_validate(comm)
    except ValueError as e:
        raise _bad_request(e) from e

@router.post("/{commission_id}/quote", response_model=CommissionRead)
async def apply_quote(
        commission_id: uuid.UUID,
        body: QuoteCreate,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    try:
        comm = await commission_service.apply_quote(db, commission_id, body)
        return CommissionRead.model_validate(comm)
    except ValueError as e:
        raise _bad_request(e) from e

@router.post("/{commission_id}/tos-accept", response_model=CommissionRead)
async def accept_tos(
        commission_id: uuid.UUID,
        db: DBSession,
        body: TosAcceptBody,
        _auth: BotAuth
) -> CommissionRead:
    try:
        comm = await commission_service.confirm_tos_acceptance(
            db,
            commission_id,
            body.tos_version_hash
        )
        return CommissionRead.model_validate(comm)
    except ValueError as e:
        raise _bad_request(e) from e

@router.post("/{commission_id}/receipt", response_model=CommissionRead)
async def upload_receipt(
        commission_id: uuid.UUID,
        db: DBSession,
        body: ReceiptUploadBody,
        _auth: BotAuth
) -> CommissionRead:
    try:
        comm = await commission_service.upload_receipt(
            db,
            commission_id,
            body.payment_receipt_url
        )
        return CommissionRead.model_validate(comm)
    except ValueError as e:
        raise _bad_request(e) from e

@router.post("/{commission_id}/confirm-payment", response_model=CommissionRead)
async def confirm_payment(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth,
        method: Annotated[PaymentMethod | None, Query()] = None
) -> CommissionRead:
    try:
        comm = await commission_service.confirm_payment(
            db,
            commission_id,
            payment_method=method
        )
        return CommissionRead.model_validate(comm)
    except ValueError as e:
        raise _bad_request(e) from e

@router.post("/{commission_id}/wip-update", response_model=CommissionRead)
async def deliver(
        commission_id: uuid.UUID,
        body: WipCreateBody,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    try:
        comm = await commission_service.create_wip_update(db, commission_id, body)
        return CommissionRead.model_validate(comm)
    except ValueError as e:
        raise _bad_request(e) from e

@router.post("/{commission_id}/deliver", response_model=CommissionRead)
async def deliver(
        commission_id: uuid.UUID,
        body: DeliverySubmitBody,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    try:
        comm = await commission_service.deliver(db, commission_id, body.final_file_url)
        return CommissionRead.model_validate(comm)
    except ValueError as e:
        raise _bad_request(e) from e

@router.post("/{commission_id}/complete", response_model=CommissionRead)
async def complete(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    try:
        comm = await commission_service.complete_commission(db, commission_id)
        return CommissionRead.model_validate(comm)
    except ValueError as e:
        raise _bad_request(e) from e