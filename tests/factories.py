"""
Row builders for tests. Each one commits, so rows are visible to the API's own
sessions (which share the test's connection and its outer transaction).
"""
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.artist import Artist, ArtistStatus
from shared.models.commission import Commission, CommissionStatus
from shared.models.server import Server
from shared.models.user import User
from tests.conftest import make_discord_id

# (filename, content, content type) as httpx's `files=` takes them
PNG = ("art.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png")
PDF = ("receipt.pdf", b"%PDF-1.4 " + b"\x00" * 64, "application/pdf")
ZIP = ("layers.zip", b"PK\x03\x04" + b"\x00" * 64, "application/zip")


ACTOR_HEADER = "X-Actor-Discord-Id"

# Which party performs each commission action (the path's last segment).
ACTION_ROLES = {
    "intake": "client",
    "quote": "artist",
    "counter-offer": "client",
    "accept-quote": "client",
    "tos-accept": "client",
    "receipt": "client",
    "confirm-payment": "artist",
    "wip-update": "artist",
    "deliver": "artist",
    "complete": "client",
    "cancel": "client",
    "review": "client",
}


def acting(discord_user_id: str) -> dict[str, str]:
    """Request headers for an action performed by that Discord user."""
    return {ACTOR_HEADER: discord_user_id}


def as_client(commission: "Commission") -> dict[str, str]:
    return acting(commission.test_client_discord_id)


def as_artist(commission: "Commission") -> dict[str, str]:
    return acting(commission.test_artist_discord_id)


def as_party(commission: "Commission", action: str) -> dict[str, str]:
    """Headers for whoever is allowed to perform `action` on this commission."""
    role = ACTION_ROLES.get(action)
    if role is None:
        return {}
    return as_client(commission) if role == "client" else as_artist(commission)


async def make_server(db: AsyncSession, **overrides) -> Server:
    server = Server(
        discord_guild_id=overrides.pop("discord_guild_id", make_discord_id()),
        name=overrides.pop("name", "Test Server"),
        settings=overrides.pop("settings", {}),
        **overrides,
    )
    db.add(server)
    await db.commit()
    return server


async def make_user(db: AsyncSession, **overrides) -> User:
    user = User(
        discord_user_id=overrides.pop("discord_user_id", make_discord_id()),
        **overrides,
    )
    db.add(user)
    await db.commit()
    return user


async def make_artist(
        db: AsyncSession,
        *,
        server: Server | None = None,
        user: User | None = None,
        **overrides
) -> Artist:
    server = server or await make_server(db)
    user = user or await make_user(db)
    artist = Artist(
        user_id=user.id,
        server_id=server.id,
        display_name=overrides.pop("display_name", "Test Artist"),
        styles=overrides.pop("styles", ["anime"]),
        social_links=overrides.pop("social_links", {}),
        portfolio_images=overrides.pop("portfolio_images", []),
        status=overrides.pop("status", ArtistStatus.ACTIVE),
        tos_text=overrides.pop("tos_text", "No refunds after the sketch is approved."),
        **overrides,
    )
    db.add(artist)
    await db.commit()
    artist.test_discord_id = user.discord_user_id  # for as_artist()
    return artist


async def make_commission(
        db: AsyncSession,
        *,
        artist: Artist | None = None,
        client: User | None = None,
        status: CommissionStatus = CommissionStatus.INQUIRY,
        **overrides
) -> Commission:
    """A commission placed directly in `status`, bypassing the lifecycle."""
    artist = artist or await make_artist(db)
    client = client or await make_user(db)
    commission = Commission(
        server_id=artist.server_id,
        artist_id=artist.id,
        client_id=client.id,
        status=status,
        discord_ticket_channel_id=overrides.pop("discord_ticket_channel_id", make_discord_id()),
        **overrides,
    )
    db.add(commission)
    await db.commit()
    commission.test_client_discord_id = client.discord_user_id
    commission.test_artist_discord_id = artist.test_discord_id
    return commission
