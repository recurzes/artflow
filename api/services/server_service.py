from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.server import Server
from shared.schemas.server import ServerCreate, ServerPatch, ServerSettings, ServerSettingsPatch

async def get_server_by_discord_guild_id(
        db: AsyncSession,
        discord_guild_id: str
) -> Server | None:
    result = await db.execute(
        select(Server).where(Server.discord_guild_id == discord_guild_id)
    )
    return result.scalar_one_or_none()

async def upsert_server(db: AsyncSession, data: ServerCreate) -> Server:
    existing = await get_server_by_discord_guild_id(db, data.discord_guild_id)
    settings_dict = data.settings.model_dump()
    if existing:
        existing.name = data.name
        existing.settings = settings_dict
        await db.flush()
        return existing

    server = Server(
        discord_guild_id=data.discord_guild_id,
        name=data.name,
        settings=settings_dict
    )
    db.add(server)
    await db.flush()
    return server

async def patch_server(
        db: AsyncSession,
        discord_guild_id: str,
        patch: ServerPatch
) -> Server | None:
    server = await get_server_by_discord_guild_id(db, discord_guild_id)
    if server is None:
        return None

    if patch.name is not None:
        server.name = patch.name

    if patch.settings is not None:
        partial: dict = patch.settings.model_dump(exclude_none=True)
        current = ServerSettings.model_validate(server.settings or {})
        merged = current.model_dump()
        for key, value in partial.items():
            merged[key] = value
        server.settings = ServerSettings.model_validate(merged).model_dump()

    await db.flush()
    return server

async def merge_server_settings(
        db: AsyncSession,
        discord_guild_id: str,
        patch: ServerSettingsPatch
) -> Server | None:
    spatch = ServerPatch(settings=patch)
    return await patch_server(db, discord_guild_id, spatch)