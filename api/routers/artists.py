import uuid

from fastapi import APIRouter, HTTPException, Query, status

from api.dependencies import BotAuth, DBSession
from api.services import artist_service
from shared.schemas.artist import ArtistCreate, ArtistListItem, ArtistRead, ArtistUpdate

router = APIRouter(prefix="/artists", tags=["artists"])

@router.get("", response_model=list[ArtistListItem])
async def list_artists(
        db: DBSession,
        _auth: BotAuth = None,
        server_id: uuid.UUID = Query(...),
        styles: list[str] | None = Query(default=None),
        nsfw_only: bool = Query(default=False),
) -> list[ArtistListItem]:
    artists = await artist_service.get_artists_for_server(
        db,
        server_id,
        styles=styles,
        nsfw_only=nsfw_only
    )
    return [ArtistListItem.model_validate(a) for a in artists]

@router.post("", response_model=ArtistRead, status_code=status.HTTP_201_CREATED)
async def create_artist(
        body: ArtistCreate,
        db: DBSession,
        _auth: BotAuth
) -> ArtistRead:
    artist = await artist_service.create_artist(db, body)
    return ArtistRead.model_validate(artist)

@router.patch("/{artist_id}", response_model=ArtistRead)
async def update_artist(
        artist_id: uuid.UUID,
        body: ArtistUpdate,
        db: DBSession,
        _auth: BotAuth
) -> ArtistRead:
    artist = await artist_service.update_artist(db, artist_id, body)
    if artist is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artist not found"
        )
    return ArtistRead.model_validate(artist)