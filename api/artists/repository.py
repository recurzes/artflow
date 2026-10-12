import uuid

from sqlalchemy import String, cast, select
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from shared.models.artist import Artist, ArtistStatus
from shared.models.user import User

# Every artist handed to a caller carries its user, for the Discord ID.
_WITH_USER = joinedload(Artist.user, innerjoin=True)


async def get_by_id(
        db: AsyncSession,
        artist_id: uuid.UUID,
        *,
        for_update: bool = False
) -> Artist | None:
    query = select(Artist).options(_WITH_USER).where(Artist.id == artist_id)
    if for_update:
        query = query.with_for_update(of=Artist)
    return await db.scalar(query)


async def get_for_member(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        server_id: uuid.UUID,
        for_update: bool = False
) -> Artist | None:
    query = (
        select(Artist)
        .options(_WITH_USER)
        .where(Artist.user_id == user_id, Artist.server_id == server_id)
    )
    if for_update:
        query = query.with_for_update(of=Artist)
    return await db.scalar(query)


async def get_by_discord_id(
        db: AsyncSession,
        *,
        discord_user_id: str,
        server_id: uuid.UUID
) -> Artist | None:
    return await db.scalar(
        select(Artist)
        .options(_WITH_USER)
        .join(User, Artist.user_id == User.id)
        .where(User.discord_user_id == discord_user_id, Artist.server_id == server_id)
    )


async def list_for_server(
        db: AsyncSession,
        server_id: uuid.UUID,
        *,
        styles: list[str] | None = None,
        nsfw_only: bool = False,
        status: ArtistStatus | None = ArtistStatus.ACTIVE
) -> list[Artist]:
    query = (
        select(Artist)
        .options(_WITH_USER)
        .where(Artist.server_id == server_id)
        .order_by(Artist.display_name)
    )
    if status is not None:
        query = query.where(Artist.status == status)
    if nsfw_only:
        query = query.where(Artist.nsfw_enabled.is_(True))
    if styles:
        # any of the requested styles
        query = query.where(Artist.__table__.c.styles.overlap(cast(styles, PG_ARRAY(String))))
    return list((await db.scalars(query)).all())


async def add(db: AsyncSession, artist: Artist) -> Artist:
    db.add(artist)
    await db.flush()
    return artist
