from fastapi import APIRouter, status

from api.dependencies import BotAuth, DBSession
from api.servers import service as server_service
from api.servers.schemas import (
    ServerCreate,
    ServerPatch,
    ServerRead,
    ServerSettings,
)
from shared.models.server import Server

router = APIRouter(prefix="/servers", tags=["servers"])


def _server_to_read(server: Server) -> ServerRead:
    return ServerRead(
        id=server.id,
        created_at=server.created_at,
        updated_at=server.updated_at,
        discord_guild_id=server.discord_guild_id,
        name=server.name,
        subscription_tier=server.subscription_tier,
        subscription_expires_at=server.subscription_expires_at,
        settings=ServerSettings.model_validate(server.settings or {}),
    )

@router.post("", response_model=ServerRead, status_code=status.HTTP_201_CREATED)
async def create_or_update_server(
        body: ServerCreate,
        db: DBSession,
        _auth: BotAuth
) -> ServerRead:
    server = await server_service.upsert_server(db, body)
    return _server_to_read(server)

@router.get("/{guild_id}", response_model=ServerRead)
async def get_server(
        guild_id: str,
        db: DBSession,
        _auth: BotAuth
) -> ServerRead:
    server = await server_service.get_server_by_discord_guild_id(db, guild_id)
    return _server_to_read(server)

@router.patch("/{guild_id}", response_model=ServerRead)
async def patch_server(
        guild_id: str,
        body: ServerPatch,
        db: DBSession,
        _auth: BotAuth
) -> ServerRead:
    server = await server_service.patch_server(db, guild_id, body)
    return _server_to_read(server)
