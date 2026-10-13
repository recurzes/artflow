from fastapi import APIRouter, status

from api.dependencies import BotAuth, DBSession, RedisClient
from api.users import service as user_service
from api.users.schemas import (
    UserCreate,
    UserRead,
    Verify18ApproveBody,
    Verify18Response,
    Verify18Submit,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_200_OK)
async def upsert_user(
        body: UserCreate,
        db: DBSession,
        _auth: BotAuth,
) -> UserRead:
    user = await user_service.upsert_user(
        db,
        discord_user_id=body.discord_user_id,
        discord_account_created_at=body.discord_account_created_at
    )
    return UserRead.model_validate(user)


@router.get("/{discord_user_id}", response_model=UserRead)
async def get_user(
        db: DBSession,
        _auth: BotAuth,
        discord_user_id: str,
) -> UserRead:
    user = await user_service.require_user_by_discord_id(db, discord_user_id)
    return UserRead.model_validate(user)


@router.post("/verify-18/submit", response_model=Verify18Response)
async def submit_verify_18(
        body: Verify18Submit,
        db: DBSession,
        redis: RedisClient,
        _auth: BotAuth
) -> Verify18Response:
    outcome, detail, newly_queued = await user_service.submit_18_verification(db, redis, body)
    return Verify18Response(status=outcome, detail=detail, newly_queued=newly_queued)

@router.post("/verify-18/approve", response_model=UserRead)
async def approve_verify_18(
        body: Verify18ApproveBody,
        db: DBSession,
        redis: RedisClient,
        _auth: BotAuth
) -> UserRead:
    user = await user_service.approve_18_verification(
        db,
        redis,
        discord_user_id=body.discord_user_id
    )
    return UserRead.model_validate(user)
