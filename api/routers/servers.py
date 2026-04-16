from fastapi import APIRouter, HTTPException, status

from api.dependencies import BotAuth, DBSession
from shared.schemas.server import ServerCreate, ServerRead

router = APIRouter(prefix="/servers", tags=["servers"])

@router.post("", response_model=ServerRead, status_code=status.HTTP_201_CREATED)
async def create_server(
        body: ServerCreate,
        db: DBSession,
        _auth: BotAuth
) -> ServerRead:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet"
    )

@router.get("/{guild_id}", response_model=ServerRead)
async def get_server(
        guild_id: str,
        db: DBSession,
        _auth: BotAuth
) -> ServerRead:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet"
    )

@router.patch("/{guild_id}/settings", response_model=ServerRead)
async def update_server_settings(
        guild_id: str,
        db: DBSession,
        _auth: BotAuth
) -> ServerRead:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet"
    )