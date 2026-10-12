import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.servers import repository
from api.servers.schemas import ServerCreate, ServerPatch, ServerSettings
from shared.errors import NotFound
from shared.models.server import Server


async def get_server(db: AsyncSession, server_id: uuid.UUID) -> Server:
    server = await repository.get_by_id(db, server_id)
    if server is None:
        raise NotFound("Server not found")
    return server


async def find_server_by_discord_guild_id(
        db: AsyncSession,
        discord_guild_id: str
) -> Server | None:
    return await repository.get_by_guild_id(db, discord_guild_id)


async def get_server_by_discord_guild_id(
        db: AsyncSession,
        discord_guild_id: str
) -> Server:
    server = await repository.get_by_guild_id(db, discord_guild_id)
    if server is None:
        raise NotFound("Server not found")
    return server


def _merge_settings(current: dict | None, changes: dict) -> dict:
    merged = ServerSettings.model_validate(current or {}).model_dump()
    merged.update(changes)
    return ServerSettings.model_validate(merged).model_dump()


async def upsert_server(db: AsyncSession, data: ServerCreate) -> Server:
    existing = await repository.get_by_guild_id(db, data.discord_guild_id)
    if existing is not None:
        existing.name = data.name
        # Only the settings the caller actually sent; re-registering a server
        # must not reset its channel and role IDs to the defaults.
        existing.settings = _merge_settings(
            existing.settings,
            data.settings.model_dump(exclude_unset=True)
        )
        await db.flush()
        return existing

    return await repository.create(
        db,
        discord_guild_id=data.discord_guild_id,
        name=data.name,
        settings=data.settings.model_dump()
    )


async def patch_server(
        db: AsyncSession,
        discord_guild_id: str,
        patch: ServerPatch
) -> Server:
    server = await get_server_by_discord_guild_id(db, discord_guild_id)

    if patch.name is not None:
        server.name = patch.name

    if patch.settings is not None:
        server.settings = _merge_settings(
            server.settings,
            patch.settings.model_dump(exclude_none=True)
        )

    await db.flush()
    return server
