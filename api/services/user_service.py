from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.user import User


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