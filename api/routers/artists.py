import uuid
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status

from api.dependencies import BotAuth, DBSession
from api.services import artist_service
from models import Artist
from shared.schemas.artist import (
    ArtistCommissionCapacity,
    ArtistCreate,
    ArtistListItem,
    ArtistRead,
    ArtistUpdate,
)

router = APIRouter(prefix="/artists", tags=["artists"])

def _dec_price(value: object | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))

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
    return [
        ArtistListItem(
            id=a.id,
            display_name=a.display_name,
            discord_user_id=a.user.discord_user_id,
            styles=a.styles,
            price_min_php=Decimal(str(a.price_min_php)) if a.price_min_php is not None else None,
            price_max_php=Decimal(str(a.price_max_php)) if a.price_max_php is not None else None,
            rating_avg=Decimal(str(a.rating_avg)),
            rating_count=a.rating_count,
            nsfw_enabled=a.nsfw_enabled,
            status=a.status,
        )
        for a in artists
    ]

@router.post("", response_model=ArtistRead, status_code=status.HTTP_201_CREATED)
async def create_artist(
        body: ArtistCreate,
        db: DBSession,
        _auth: BotAuth
) -> ArtistRead:
    created = await artist_service.create_artist(db, body)
    full = await artist_service.get_artist_by_id(db, created.id)
    if full is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return _artist_to_read(full)

@router.get("/{artist_id}", response_model=ArtistRead)
async def get_artist(
        artist_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> ArtistRead:
    artist = await artist_service.get_artist_by_id(db, artist_id)
    if artist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artist not found")
    return _artist_to_read(artist)

@router.get("/{artist_id}/active-commission-count", response_model=ArtistCommissionCapacity)
async def active_commission_count(
        artist_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> ArtistCommissionCapacity:
    cap = await artist_service.get_artist_commission_capacity(db, artist_id)
    if cap is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artist not found")
    count, max_commissions = cap
    return ArtistCommissionCapacity(count=count, max=max_commissions)

@router.patch("/{artist_id}", response_model=ArtistRead)
async def update_artist(
        artist_id: uuid.UUID,
        body: ArtistUpdate,
        db: DBSession,
        _auth: BotAuth
) -> ArtistRead:
    updated = await artist_service.update_artist(db, artist_id, body)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artist not found.")
    full = await artist_service.get_artist_by_id(db, artist_id)
    if full is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artist not found.")
    return _artist_to_read(full)


# Helpers

def _artist_to_read(artist: Artist) -> ArtistRead:
    return ArtistRead(
        id=artist.id,
        created_at=artist.created_at,
        updated_at=artist.updated_at,
        user_id=artist.user_id,
        discord_user_id=artist.user.discord_user_id,
        server_id=artist.server_id,
        display_name=artist.display_name,
        bio=artist.bio,
        styles=artist.styles,
        social_links=artist.social_links,
        portfolio_images=artist.portfolio_images,
        price_min_php=_dec_price(artist.price_min_php),
        price_max_php=_dec_price(artist.price_max_php),
        nsfw_enabled=artist.nsfw_enabled,
        max_active_commissions=artist.max_active_commissions,
        rating_avg=Decimal(str(artist.rating_avg)),
        rating_count=artist.rating_count,
        status=artist.status,
        tos_text=artist.tos_text,
        gcash_number=artist.gcash_number,
        paypal_email=artist.paypal_email,
    )