import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from api.dependencies import BotAuth, DBSession
from shared.models.artist import Artist
from shared.models.user import User
from shared.models.commission import Commission, CommissionStatus

router = APIRouter(prefix="/admin", tags=["admin"])

_ACTIVE = (
    CommissionStatus.INQUIRY,
    CommissionStatus.INTAKE,
    CommissionStatus.QUOTED,
    CommissionStatus.TOS_PENDING,
    CommissionStatus.PAYMENT_PENDING,
    CommissionStatus.PAYMENT_PENDING,
    CommissionStatus.IN_PROGRESS,
    CommissionStatus.WIP,
    CommissionStatus.DELIVERED,
    CommissionStatus.DISPUTED
)

@router.get("/stats")
async def get_stats(
        db: DBSession,
        _auth: BotAuth,
        server_id: uuid.UUID = Query(...),
) -> dict:
    now = datetime.now(timezone.utc)
    start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    active = await db.scalar(
        select(func.count())
        .select_from(Commission)
        .where(
            Commission.server_id == server_id,
            Commission.status.in_(_ACTIVE)
        )
    )
    completed_today = await db.scalar(
        select(func.count())
        .select_from(Commission)
        .where(
            Commission.server_id == server_id,
            Commission.status == CommissionStatus.COMPLETED,
            Commission.completed_at.is_not(None),
            Commission.completed_at >= start_day
        )
    )
    rev = await db.scalar(
        select(func.coalesce(func.sum(Commission.platform_fee_php), 0.0))
        .where(
            Commission.server_id == server_id,
            Commission.status == CommissionStatus.COMPLETED,
            Commission.completed_at.is_not(None),
            Commission.completed_at >= start_month
        )
    )
    return {
        "active_commissions": int(active or 0),
        "completed_today": int(completed_today or 0),
        "revenue_php_this_month": float(rev or 0.0)
    }

@router.get("/artists")
async def list_artists_admin(
        db: DBSession,
        _auth: BotAuth,
        server_id: uuid.UUID = Query(...),
        limit: int = Query(default=25, ge=1, le=200),
        offset: int = Query(default=0, ge=0)
) -> dict:
    r = await db.execute(
        select(Artist, User.discord_user_id)
        .join(User, Artist.user_id == User.id)
        .where(Artist.server_id == server_id)
        .order_by(Artist.display_name)
        .limit(limit)
        .offset(offset)
    )
    rows = r.all()
    out: list[dict] = []
    for artist, duid in rows:
        n_active = await db.scalar(
            select(func.count())
            .select_from(Commission)
            .where(
                Commission.artist_id == artist.id,
                Commission.status.in_(_ACTIVE)
            )
        )
        out.append(
            {
                "id": str(artist.id),
                "display_name": artist.display_name,
                "discord_user_id": duid,
                "status": artist.status.value,
                "nsfw_enabled": artist.nsfw_enabled,
                "active_commission_count": int(n_active or 0)
            }
        )
    return {"artists": out, "limit": limit, "offset": offset}

@router.get("/commissions/summary")
async def commissions_summary(
        db: DBSession,
        _auth: BotAuth,
        server_id: uuid.UUID = Query(...)
) -> dict:
    r = await db.execute(
        select(Commission.status, func.count(Commission.id))
        .where(Commission.server_id == server_id)
        .group_by(Commission.status)
    )
    by_status: dict[str, int] = {}
    for st, n in r.all():
        by_status[st.value] = int(n)
    return {"by_status": by_status}