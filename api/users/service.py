import uuid
from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from api.users import repository
from api.users.schemas import Verify18Submit
from shared.errors import NotFound
from shared.models.user import User

MIN_DISCORD_ACCOUNT_AGE_DAYS = 90
_AGE_VERIFY_PENDING_PREFIX = "age_verify_pending:"
_PENDING_TTL_SEC = 7 * 24 * 3600


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _account_age_days(created_at: datetime | None) -> int | None:
    if created_at is None:
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    delta = _utcnow() - created_at
    return max(0, delta.days)


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await repository.get_by_id(db, user_id)
    if user is None:
        raise NotFound("User not found")
    return user


async def get_user_by_discord_id(
        db: AsyncSession, discord_user_id: str
) -> User | None:
    return await repository.get_by_discord_id(db, discord_user_id)


async def require_user_by_discord_id(db: AsyncSession, discord_user_id: str) -> User:
    user = await repository.get_by_discord_id(db, discord_user_id)
    if user is None:
        raise NotFound("User not found")
    return user


async def upsert_user(
        db: AsyncSession,
        *,
        discord_user_id: str,
        discord_account_created_at: datetime | None = None
) -> User:
    user = await repository.get_by_discord_id(db, discord_user_id)
    if user is None:
        return await repository.create(
            db,
            discord_user_id=discord_user_id,
            discord_account_created_at=discord_account_created_at
        )
    if discord_account_created_at is not None:
        user.discord_account_created_at = discord_account_created_at
        await db.flush()
    return user


async def verify_email(db: AsyncSession, *, discord_user_id: str) -> User:
    user = await require_user_by_discord_id(db, discord_user_id)
    user.is_email_verified = True
    await db.flush()
    return user


async def submit_18_verification(
        db: AsyncSession,
        redis: Redis,
        body: Verify18Submit
) -> tuple[str, str | None, bool]:
    """Returns (status, detail, newly_queued)."""
    user = await upsert_user(
        db,
        discord_user_id=body.discord_user_id,
        discord_account_created_at=body.discord_account_created_at
    )
    if user.is_18_verified:
        return "already_verified", None, False

    pending_key = f"{_AGE_VERIFY_PENDING_PREFIX}{body.discord_user_id}"
    age_days = _account_age_days(user.discord_account_created_at)
    if age_days is not None and age_days >= MIN_DISCORD_ACCOUNT_AGE_DAYS:
        user.is_18_verified = True
        user.is_18_verified_at = _utcnow()
        await db.flush()
        await redis.delete(pending_key)
        return "approved", None, False

    # SET NX: only the first request while one is pending reports newly_queued.
    newly_queued = bool(await redis.set(pending_key, "1", ex=_PENDING_TTL_SEC, nx=True))
    return (
        "pending_mod",
        f"Accounts younger than {MIN_DISCORD_ACCOUNT_AGE_DAYS} days are reviewed by a moderator",
        newly_queued
    )


async def approve_18_verification(
        db: AsyncSession,
        redis: Redis,
        *,
        discord_user_id: str
) -> User:
    user = await require_user_by_discord_id(db, discord_user_id)
    user.is_18_verified = True
    user.is_18_verified_at = _utcnow()
    await db.flush()
    await redis.delete(f"{_AGE_VERIFY_PENDING_PREFIX}{discord_user_id}")
    return user
