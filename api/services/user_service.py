from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.user import User
from shared.schemas.user import Verify18Submit

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


async def upsert_user(
        db: AsyncSession,
        *,
        discord_user_id: str,
        is_phone_verified: bool = False,
        discord_account_created_at: datetime | None = None
) -> User:
    result = await db.execute(
        select(User).where(User.discord_user_id == discord_user_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            discord_user_id=discord_user_id,
            is_phone_verified=is_phone_verified,
            discord_account_created_at=discord_account_created_at
        )
        db.add(user)
        await db.flush()

    return user

async def set_email(db: AsyncSession, *, discord_user_id: str, email: str) -> User | None:
    result = await db.execute(
        select(User).where(User.discord_user_id == discord_user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        return None

    user.email = email
    await db.flush()
    return user

async def verify_email(db: AsyncSession, *, discord_user_id: str) -> User | None:
    result = await db.execute(
        select(User).where(User.discord_user_id == discord_user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        return None

    user.is_email_verified = True
    await db.flush()
    return user

async def get_user_by_discord_id(
        db: AsyncSession, discord_user_id: str
) -> User | None:
    result = await db.execute(
        select(User).where(User.discord_user_id == discord_user_id)
    )
    return result.scalar_one_or_none()


async def ensure_user_discord_flags(
        db: AsyncSession,
        *,
        discord_user_id: str,
        is_phone_verified: bool,
        discord_account_created_at: datetime | None
) -> User:
    user = await get_user_by_discord_id(db, discord_user_id)
    if user is None:
        user = User(
            discord_user_id=discord_user_id,
            is_phone_verified=is_phone_verified,
            discord_account_created_at=discord_account_created_at
        )
        db.add(user)
    else:
        user.is_phone_verified = is_phone_verified
        if discord_account_created_at is not None:
            user.discord_account_created_at = discord_account_created_at
    await db.flush()
    return user


async def submit_18_verification(
        db: AsyncSession,
        redis: Redis,
        body: Verify18Submit
) -> tuple[str, str | None]:
    user = await ensure_user_discord_flags(
        db,
        discord_user_id=body.discord_user_id,
        is_phone_verified=body.is_phone_verified,
        discord_account_created_at=body.discord_account_created_at
    )
    if user.is_18_verified:
        return "already_verified", None

    age_days = _account_age_days(user.discord_account_created_at)
    age_ok = age_days is not None and age_days >= MIN_DISCORD_ACCOUNT_AGE_DAYS

    if age_ok:
        user.is_18_verified = True
        user.is_18_verified_at = _utcnow()
        await db.flush()
        key = f"{_AGE_VERIFY_PENDING_PREFIX}{body.discord_user_id}"
        await redis.delete(key)
        return "approved", None

    await redis.setex(
        f"{_AGE_VERIFY_PENDING_PREFIX}{body.discord_user_id}",
        _PENDING_TTL_SEC,
        "1"
    )
    return "pending_mod", "Account must be at least 90 days old for auto-approval, or ask a mod"


async def approve_18_verification(
        db: AsyncSession,
        redis: Redis,
        *,
        discord_user_id: str
) -> User | None:
    user = await get_user_by_discord_id(db, discord_user_id)
    if user is None:
        return None
    user.is_18_verified = True
    user.is_18_verified_at = _utcnow()
    await db.flush()
    await redis.delete(f"{_AGE_VERIFY_PENDING_PREFIX}{discord_user_id}")
    return user