import uuid

from fastapi import APIRouter, Query

from api.admin import service as admin_service
from api.admin.schemas import AdminArtistList, AdminStats, CommissionSummary
from api.dependencies import BotAuth, DBSession

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats", response_model=AdminStats)
async def get_stats(
        db: DBSession,
        _auth: BotAuth,
        server_id: uuid.UUID = Query(...),
) -> AdminStats:
    return await admin_service.get_stats(db, server_id)

@router.get("/artists", response_model=AdminArtistList)
async def list_artists_admin(
        db: DBSession,
        _auth: BotAuth,
        server_id: uuid.UUID = Query(...),
        limit: int = Query(default=25, ge=1, le=200),
        offset: int = Query(default=0, ge=0)
) -> AdminArtistList:
    return await admin_service.list_artists(db, server_id, limit=limit, offset=offset)

@router.get("/commissions/summary", response_model=CommissionSummary)
async def commissions_summary(
        db: DBSession,
        _auth: BotAuth,
        server_id: uuid.UUID = Query(...)
) -> CommissionSummary:
    return await admin_service.get_commission_summary(db, server_id)
