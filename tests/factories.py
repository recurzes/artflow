"""
Row builders for tests. Each one commits, so rows are visible to the API's own
sessions (which share the test's connection and its outer transaction).
"""
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.artist import Artist, ArtistStatus
from shared.models.server import Server
from shared.models.user import User
from tests.conftest import make_discord_id


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
    return artist
