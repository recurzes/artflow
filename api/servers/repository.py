import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.server import Server


async def get_by_id(db: AsyncSession, server_id: uuid.UUID) -> Server | None:
    return await db.scalar(select(Server).where(Server.id == server_id))


async def get_by_guild_id(db: AsyncSession, discord_guild_id: str) -> Server | None:
    return await db.scalar(select(Server).where(Server.discord_guild_id == discord_guild_id))


async def create(db: AsyncSession, *, discord_guild_id: str, name: str, settings: dict) -> Server:
    server = Server(discord_guild_id=discord_guild_id, name=name, settings=settings)
    db.add(server)
    await db.flush()
    return server
