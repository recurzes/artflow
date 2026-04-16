import uuid

from fastapi import APIRouter, HTTPException, status

from api.dependencies import BotAuth, DBSession
from shared.schemas.commission import (
    CommissionCreate,
    CommissionRead,
    CommissionStatusUpdate,
    QuoteCreate
)

router = APIRouter(prefix="/commissions", tags=["commissions"])

@router.post("", response_model=CommissionRead, status_code=status.HTTP_201_CREATED)
async def create_commission(
        body: CommissionCreate,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet"
    )

@router.get("/{commission_id}", response_model=CommissionRead)
async def get_commission(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet"
    )

@router.patch("/{commission_id}/status", response_model=CommissionRead)
async def update_commission_status(
        commission_id: uuid.UUID,
        body: CommissionStatusUpdate,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet"
    )

@router.post("/{commission_id}/quote", response_model=CommissionRead)
async def apply_quote(
        commission_id: uuid.UUID,
        body: QuoteCreate,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet"
    )

@router.post("/{commission_id}/tos-accept", response_model=CommissionRead)
async def accept_tos(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet"
    )

@router.post("/{commission_id}/receipt", response_model=CommissionRead)
async def upload_receipt(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet"
    )

@router.post("/{commission_id}/confirm-payment", response_model=CommissionRead)
async def confirm_payment(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet"
    )

@router.post("/{commission_id}/deliver", response_model=CommissionRead)
async def deliver(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet"
    )

@router.post("/{commission_id}/complete", response_model=CommissionRead)
async def complete(
        commission_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> CommissionRead:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet"
    )