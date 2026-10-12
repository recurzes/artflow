import uuid
from decimal import Decimal

from fastapi import APIRouter, Query, status

from api.artists import service as artist_service
from api.artists.schemas import (
    ArtistApplication,
    ArtistApproval,
    ArtistCommissionCapacity,
    ArtistListItem,
    ArtistRead,
    ArtistRejection,
    ArtistUpdate,
)
from api.commissions import service as commission_service
from api.dependencies import BotAuth, DBSession
from shared.models.artist import Artist

router = APIRouter(prefix="/artists", tags=["artists"])

def _dec_price(value: object | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))

@router.get("", response_model=list[ArtistListItem])
async def list_artists(
        db: DBSession,
        _auth: BotAuth,
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
            price_min_php=_dec_price(a.price_min_php),
            price_max_php=_dec_price(a.price_max_php),
            rating_avg=Decimal(str(a.rating_avg)),
            rating_count=a.rating_count,
            nsfw_enabled=a.nsfw_enabled,
            status=a.status,
        )
        for a in artists
    ]

@router.post(
    "/applications",
    response_model=ArtistRead,
    status_code=status.HTTP_201_CREATED
)
async def apply_as_artist(
        body: ArtistApplication,
        db: DBSession,
        _auth: BotAuth
) -> ArtistRead:
    artist = await artist_service.apply(db, body)
    return _artist_to_read(artist)

@router.get("/by-discord/{discord_user_id}", response_model=ArtistRead)
async def get_artist_by_discord_id(
        discord_user_id: str,
        db: DBSession,
        _auth: BotAuth,
        server_id: uuid.UUID = Query(...)
) -> ArtistRead:
    artist = await artist_service.get_artist_by_discord_id(db, discord_user_id, server_id)
    return _artist_to_read(artist)

@router.get("/{artist_id}", response_model=ArtistRead)
async def get_artist(
        artist_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> ArtistRead:
    artist = await artist_service.get_artist(db, artist_id)
    return _artist_to_read(artist)

@router.get("/{artist_id}/active-commission-count", response_model=ArtistCommissionCapacity)
async def active_commission_count(
        artist_id: uuid.UUID,
        db: DBSession,
        _auth: BotAuth
) -> ArtistCommissionCapacity:
    count, max_commissions = await commission_service.get_artist_capacity(db, artist_id)
    return ArtistCommissionCapacity(count=count, max=max_commissions)

@router.post("/{artist_id}/approve", response_model=ArtistRead)
async def approve_artist(
        artist_id: uuid.UUID,
        body: ArtistApproval,
        db: DBSession,
        _auth: BotAuth
) -> ArtistRead:
    artist = await artist_service.approve(db, artist_id, body.moderator_discord_user_id)
    return _artist_to_read(artist)

@router.post("/{artist_id}/reject", response_model=ArtistRead)
async def reject_artist(
        artist_id: uuid.UUID,
        body: ArtistRejection,
        db: DBSession,
        _auth: BotAuth
) -> ArtistRead:
    artist = await artist_service.reject(
        db,
        artist_id,
        body.moderator_discord_user_id,
        body.reason
    )
    return _artist_to_read(artist)

@router.patch("/{artist_id}", response_model=ArtistRead)
async def update_artist(
        artist_id: uuid.UUID,
        body: ArtistUpdate,
        db: DBSession,
        _auth: BotAuth
) -> ArtistRead:
    artist = await artist_service.update_artist(db, artist_id, body)
    return _artist_to_read(artist)


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
        tos_hash=artist_service.tos_hash(artist.tos_text) if artist.tos_text else None,
        gcash_number=artist.gcash_number,
        paypal_email=artist.paypal_email,
    )
