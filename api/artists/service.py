import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from api.artists import repository
from api.artists.schemas import ArtistApplication, ArtistUpdate
from api.servers import service as server_service
from api.users import service as user_service
from shared.errors import Conflict, InvalidState, NotFound
from shared.models.artist import Artist, ArtistStatus

# How long a rejected applicant waits before applying again
REAPPLY_AFTER = timedelta(days=7)


def tos_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Reads

async def get_artist(db: AsyncSession, artist_id: uuid.UUID) -> Artist:
    artist = await repository.get_by_id(db, artist_id)
    if artist is None:
        raise NotFound("Artist not found")
    return artist


async def get_artist_for_update(db: AsyncSession, artist_id: uuid.UUID) -> Artist:
    """Load and row-lock an artist: for checks that must not race (capacity, rating)."""
    artist = await repository.get_by_id(db, artist_id, for_update=True)
    if artist is None:
        raise NotFound("Artist not found")
    return artist


async def get_artist_by_discord_id(
        db: AsyncSession,
        discord_user_id: str,
        server_id: uuid.UUID
) -> Artist:
    artist = await repository.get_by_discord_id(
        db,
        discord_user_id=discord_user_id,
        server_id=server_id
    )
    if artist is None:
        raise NotFound("This member is not a registered artist on this server")
    return artist


async def get_artists_for_server(
        db: AsyncSession,
        server_id: uuid.UUID,
        *,
        styles: list[str] | None = None,
        nsfw_only: bool = False
) -> list[Artist]:
    """Artists a client can commission: only the active ones."""
    return await repository.list_for_server(
        db,
        server_id,
        styles=styles,
        nsfw_only=nsfw_only,
        status=ArtistStatus.ACTIVE
    )


# Onboarding

async def apply(db: AsyncSession, data: ArtistApplication) -> Artist:
    """Record an artist application as a PENDING artist row."""
    server = await server_service.find_server_by_discord_guild_id(db, data.discord_guild_id)
    if server is None:
        raise NotFound("This server is not set up with ArtFlow yet. Ask an admin to run setup")

    user = await user_service.upsert_user(
        db,
        discord_user_id=data.discord_user_id,
        discord_account_created_at=data.discord_account_created_at
    )

    artist = await repository.get_for_member(
        db,
        user_id=user.id,
        server_id=server.id,
        for_update=True
    )
    if artist is None:
        artist = await repository.add(
            db,
            Artist(user_id=user.id, server_id=server.id, display_name=data.display_name)
        )
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
    artist = await repository.get_by_id(db, artist_id, for_update=True)
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


# Profile

async def update_artist(db: AsyncSession, artist_id: uuid.UUID, data: ArtistUpdate) -> Artist:
    artist = await get_artist(db, artist_id)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(artist, field, value)
    await db.flush()
    return artist
