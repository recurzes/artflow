from fastapi import APIRouter, HTTPException, Query, Request, status

from api.dependencies import BotAuth, DBSession, RedisClient, limiter
from api.services import user_service
from shared.schemas.user import (
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


@router.get("/verify-email", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def verify_email(
        request: Request,
        db: DBSession,
        redis: RedisClient,
        token: str = Query(..., description="Email verification token from DM Link"),
) -> dict:
    redis_key = f"email_verify:{token}"
    discord_user_id = await redis.get(redis_key)

    if discord_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification token is invalid or has expired"
        )

    await user_service.verify_email(db, discord_user_id=discord_user_id)
    await redis.delete(redis_key)
    return {"message": "Email verified successfully. You can close this tab"}


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
    outcome, detail = await user_service.submit_18_verification(db, redis, body)
    return Verify18Response(status=outcome, detail=detail)

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
