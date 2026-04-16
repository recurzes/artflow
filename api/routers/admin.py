import uuid

from fastapi import APIRouter, HTTPException, Query, status

from api.dependencies import BotAuth, DBSession

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/stats")
async def get_stats(
        db: DBSession,
        _auth: BotAuth,
        server_id: uuid.UUID = Query(...),
) -> dict:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet"
    )

@router.get("/artists")
async def list_artists_admin(
        db: DBSession,
        _auth: BotAuth,
        server_id: uuid.UUID = Query(...)
) -> dict:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet"
    )

@router.get("/commissions/summary")
async def commissions_summary(
        db: DBSession,
        _auth: BotAuth,
        server_id: uuid.UUID = Query(...)
) -> dict:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet"
    )