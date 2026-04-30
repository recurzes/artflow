import uuid

from sqlalchemy import String, cast, func, select
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from shared.models.artist import Artist, ArtistStatus
from shared.models.commission import Commission, CommissionStatus
from shared.schemas.artist import ArtistCreate, ArtistUpdate

_TERMINAL_COMMISSION_STATUSES = (CommissionStatus. COMPLETED, CommissionStatus.CANCELLED)

async def create_artist(db: AsyncSession, data: ArtistCreate) -> Artist:
    artist = Artist(
        user_id=data.user_id,
        server_id=data.server_id,
        display_name=data.display_name,
        bio=data.bio,
        styles=data.styles,
        social_links=data.social_links,
        portfolio_images=data.portfolio_images,
        price_min_php=float(data.price_min_php) if data.price_min_php else None,
        price_max_php=float(data.price_max_php) if data.price_max_php else None,
        nsfw_enabled=data.nsfw_enabled,
        max_active_commission=data.max_active_commissions,
        gcash_number=data.gcash_number,
        status=ArtistStatus.ACTIVE
    )
    db.add(artist)
    await db.flush()
    return artist

async def update_artist_status(
        db:AsyncSession,
        artist_id: uuid.UUID,
        status: ArtistStatus
) -> Artist | None:
    result = await db.execute(select(Artist).where(Artist.id == artist_id))
    artist = result.scalar_one_or_none()
    if artist is None:
        return None
    artist.status = status
    await db.flush()
    return artist

async def update_artist(
    db: AsyncSession, artist_id: uuid.UUID, data: ArtistUpdate
) -> Artist | None:
    result = await db.execute(select(Artist).where(Artist.id == artist_id))
    artist = result.scalar_one_or_none()
    if artist is None:
        return None

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(artist, field, value)

    await db.flush()
    return artist


async def get_artist_by_id(db: AsyncSession, artist_id: uuid.UUID) -> Artist | None:
    result = await db.execute(
        select(Artist).options(joinedload(Artist.user)).where(Artist.id == artist_id)
    )
    return result.scalar_one_or_none()


async def get_artist_by_discord_id(
        db: AsyncSession,
        discord_user_id: str,
        server_id: uuid.UUID
) -> Artist | None:
    from shared.models.user import User

    result = await db.execute(
        select(Artist)
        .join(User, Artist.user_id == User.id)
        .where(User.discord_user_id == discord_user_id)
        .where(Artist.server_id == server_id)
    )
    return result.scalar_one_or_none()

async def get_artists_for_server(
        db: AsyncSession,
        server_id: uuid.UUID,
        *,
        styles: list[str] | None = None,
        nsfw_only: bool = False,
        active_only: bool = True
) -> list[Artist]:
    query = (
        select(Artist)
        .options(joinedload(Artist.user))
        .where(Artist.server_id == server_id)
    )

    if active_only:
        query = query.where(Artist.status == ArtistStatus.ACTIVE)
    if nsfw_only:
        query = query.where(Artist.nsfw_enabled.is_(True))
    if styles:
        styles_col = Artist.__table__.c.styles
        query = query.where(styles_col.overlap(cast(styles, PG_ARRAY(String))))

    result = await db.execute(query)
    return list[Artist](result.scalars().all())

async def count_active_commissions_for_artist(
        db: AsyncSession,
        artist_id: uuid.UUID
) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(Commission)
        .where(
            Commission.artist_id == artist_id,
            Commission.status.notin_(_TERMINAL_COMMISSION_STATUSES)
        )
    )
    return int(result.scalar_one() or 0)

async def get_artist_commission_capacity(
        db: AsyncSession,
        artist_id: uuid.UUID
) -> tuple[int, int] | None:
    result = await db.execute(
        select(Artist)
        .where(Artist.id == artist_id)
    )
    artist = result.scalar_one_or_none()
    if artist is None:
        return None
    count = await count_active_commissions_for_artist(db, artist_id)
    return count, artist.max_active_commissions