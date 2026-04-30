from fastapi import APIRouter, HTTPException, Query, Request, status

from api.dependencies import BotAuth, DBSession, RedisClient, limiter
from api.services import user_service
from shared.schemas.user import UserCreate, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
async def upsert_user(
        request: Request,
        body: UserCreate,
        db: DBSession,
        _auth: BotAuth,
) -> UserRead:
    user = await user_service.upsert_user(
        db,
        discord_user_id=body.discord_user_id,
        is_phone_verified=body.is_phone_verified,
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

    user = await user_service.verify_email(db, discord_user_id=discord_user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    await redis.delete(redis_key)
    return {"message": "Email verified successfully. You can close this tab"}


@router.get("/{discord_user_id}", response_model=UserRead)
@limiter.limit("30/minute")
async def get_user(
        request: Request,
        db: DBSession,
        _auth: BotAuth,
        discord_user_id: str,
) -> UserRead:
    user = await user_service.get_user_by_discord_id(db, discord_user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return UserRead.model_validate(user)