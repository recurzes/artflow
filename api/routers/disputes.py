import uuid

from fastapi import APIRouter, HTTPException, status

from api.dependencies import BotAuth, DBSession
from api.services import dispute_service
from shared.schemas.dispute import DisputeCreate, DisputeRead, DisputeResolve

router = APIRouter(prefix="/disputes", tags=["disputes"])


@router.post("", response_model=DisputeRead, status_code=status.HTTP_201_CREATED)
async def open_dispute(
        body: DisputeCreate,
        db: DBSession,
        _auth: BotAuth
) -> DisputeRead:
    try:
        row = await dispute_service.open_dispute(db, body)
        return DisputeRead.model_validate(row)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        ) from e
    

@router.patch("/{dispute_id}/resolve", response_model=DisputeRead)
async def resolve_dispute(
        dispute_id: uuid.UUID,
        body: DisputeResolve,
        db: DBSession,
        _auth: BotAuth
) -> DisputeRead:
    try:
        row = await dispute_service.resolve_dispute(db, dispute_id, body)
        return DisputeRead.model_validate(row)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        ) from e