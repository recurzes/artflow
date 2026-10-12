import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, cast, func, select
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.artists.schemas import ArtistApplication, ArtistUpdate
from api.users import service as user_service
from shared.errors import Conflict, InvalidState, NotFound
from shared.models.artist import Artist, ArtistStatus
from shared.models.commission import Commission, CommissionStatus
from shared.models.server import Server
from shared.models.user import User

_TERMINAL_COMMISSION_STATUSES = (CommissionStatus.COMPLETED, CommissionStatus.CANCELLED)

# How long a rejected applicant waits before applying again
REAPPLY_AFTER = timedelta(days=7)


def tos_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def apply(db: AsyncSession, data: ArtistApplication) -> Artist:
    """Record an artist application as a PENDING artist row."""
    server = await db.scalar(
        select(Server).where(Server.discord_guild_id == data.discord_guild_id)
    )
    if server is None:
        raise NotFound("This server is not set up with ArtFlow yet. Ask an admin to run setup")

    user = await user_service.upsert_user(
        db,
        discord_user_id=data.discord_user_id,
        discord_account_created_at=data.discord_account_created_at
    )

    artist = await db.scalar(
        select(Artist)
        .where(Artist.user_id == user.id, Artist.server_id == server.id)
        .with_for_update()
    )
    if artist is None:
        artist = Artist(user_id=user.id, server_id=server.id, display_name=data.display_name)
        db.add(artist)
    elif artist.status == ArtistStatus.PENDING:
        raise Conflict("Your application is already waiting for review")
    elif artist.status != ArtistStatus.REJECTED:
        raise Conflict("You are already registered as an artist on this server")
    else:
        wait = _reapply_wait(artist)
        if wait is not None:
            days = max(1, wait.days + (1 if wait.seconds else 0))
            raise Conflict(
                f"Your application was recently rejected. You may reapply in {days} day(s)"
            )

    artist.display_name = data.display_name
    artist.styles = data.styles
    artist.social_links = data.social_links
    artist.price_min_php = float(data.price_min_php) if data.price_min_php is not None else None
    artist.price_max_php = float(data.price_max_php) if data.price_max_php is not None else None
    artist.gcash_number = data.gcash_number
    artist.paypal_email = data.paypal_email
    artist.status = ArtistStatus.PENDING
    artist.rejected_at = None
    artist.rejection_reason = None
    await db.flush()
    return await get_artist(db, artist.id)


def _reapply_wait(artist: Artist) -> timedelta | None:
    """Time left before a rejected applicant may apply again, if any."""
    if artist.rejected_at is None:
        return None
    remaining = artist.rejected_at + REAPPLY_AFTER - datetime.now(timezone.utc)
    return remaining if remaining > timedelta(0) else None


async def _get_pending_for_decision(db: AsyncSession, artist_id: uuid.UUID) -> Artist:
    artist = await db.scalar(
        select(Artist)
        .options(joinedload(Artist.user))
        .where(Artist.id == artist_id)
        .with_for_update(of=Artist)
    )
    if artist is None:
        raise NotFound("Application not found")
    if artist.status != ArtistStatus.PENDING:
        raise InvalidState(
            f"This application was already decided (it is {artist.status.value.lower()})"
        )
    return artist


async def approve(
        db: AsyncSession,
        artist_id: uuid.UUID,
        moderator_discord_user_id: str
) -> Artist:
    artist = await _get_pending_for_decision(db, artist_id)
    moderator = await user_service.upsert_user(db, discord_user_id=moderator_discord_user_id)
    artist.status = ArtistStatus.ACTIVE
    artist.verified_at = datetime.now(timezone.utc)
    artist.verified_by = moderator.id
    await db.flush()
    return artist


async def reject(
        db: AsyncSession,
        artist_id: uuid.UUID,
        moderator_discord_user_id: str,
        reason: str
) -> Artist:
    artist = await _get_pending_for_decision(db, artist_id)
    await user_service.upsert_user(db, discord_user_id=moderator_discord_user_id)
    artist.status = ArtistStatus.REJECTED
    artist.rejected_at = datetime.now(timezone.utc)
    artist.rejection_reason = reason
    await db.flush()
    return artist


async def update_artist(db: AsyncSession, artist_id: uuid.UUID, data: ArtistUpdate) -> Artist:
    artist = await get_artist(db, artist_id)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(artist, field, value)
    await db.flush()
    return artist


async def get_artist(db: AsyncSession, artist_id: uuid.UUID) -> Artist:
    result = await db.execute(
        select(Artist).options(joinedload(Artist.user)).where(Artist.id == artist_id)
    )
    artist = result.scalar_one_or_none()
    if artist is None:
        raise NotFound("Artist not found")
    return artist


async def get_artist_by_discord_id(
        db: AsyncSession,
        discord_user_id: str,
        server_id: uuid.UUID
) -> Artist:
    result = await db.execute(
        select(Artist)
        .options(joinedload(Artist.user))
        .join(User, Artist.user_id == User.id)
        .where(User.discord_user_id == discord_user_id)
        .where(Artist.server_id == server_id)
    )
    artist = result.scalar_one_or_none()
    if artist is None:
        raise NotFound("This member is not a registered artist on this server")
    return artist


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
        .order_by(Artist.display_name)
    )

    if active_only:
        query = query.where(Artist.status == ArtistStatus.ACTIVE)
    if nsfw_only:
        query = query.where(Artist.nsfw_enabled.is_(True))
    if styles:
        styles_col = Artist.__table__.c.styles
        query = query.where(styles_col.overlap(cast(styles, PG_ARRAY(String))))

    result = await db.execute(query)
    return list(result.scalars().all())


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
) -> tuple[int, int]:
    artist = await get_artist(db, artist_id)
    count = await count_active_commissions_for_artist(db, artist_id)
    return count, artist.max_active_commissions
