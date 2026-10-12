import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.user import User


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.scalar(select(User).where(User.id == user_id))


async def get_by_discord_id(db: AsyncSession, discord_user_id: str) -> User | None:
    return await db.scalar(select(User).where(User.discord_user_id == discord_user_id))


async def create(
        db: AsyncSession,
        *,
        discord_user_id: str,
        discord_account_created_at: datetime | None
) -> User:
    user = User(
        discord_user_id=discord_user_id,
        discord_account_created_at=discord_account_created_at
    )
    db.add(user)
    await db.flush()
    return user
