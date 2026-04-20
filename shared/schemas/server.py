from datetime import datetime

from pydantic import BaseModel, ConfigDict

from shared.models.server import SubscriptionTier
from shared.schemas.common import TimestampSchema


class ServerSettings(BaseModel):
    """JSONB settings blob stored in servers.settings."""

    model_config = ConfigDict(from_attributes=True)

    timezone: str = "Asia/Manila"
    default_currency: str = "PHP"  # PHP | USD | BOTH
    nsfw_enabled: bool = False
    max_active_commissions_per_artist: int = 5
    commission_expiry_hours: int = 24
    # Discord channel IDs (populated by /setup wizard)
    channel_verification: str | None = None
    channel_artist_directory: str | None = None
    channel_verification_queue: str | None = None
    channel_commissions_open: str | None = None
    channel_completed_works: str | None = None
    channel_reviews: str | None = None
    channel_admin_logs: str | None = None
    channel_age_check: str | None = None
    # Discord role IDs
    role_unverified: str | None = None
    role_verified_user: str | None = None
    role_verified_artist: str | None = None
    role_18_verified: str | None = None
    role_moderator: str | None = None


class ServerCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    discord_guild_id: str
    name: str
    settings: ServerSettings = ServerSettings()


class ServerRead(TimestampSchema):
    discord_guild_id: str
    name: str
    subscription_tier: SubscriptionTier
    subscription_expires_at: datetime | None
    settings: ServerSettings

class ServerSettingsPatch(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timezone: str | None = None
    default_currency: str | None = None
    nsfw_enabled: bool | None = None
    max_active_commissions_per_artist: int | None = None
    commission_expiry_hours: int | None = None
    channel_verification: str | None = None
    channel_bot_commands: str | None = None
    channel_artist_directory: str | None = None
    channel_verification_queue: str | None = None
    channel_commissions_open: str | None = None
    channel_completed_works: str | None = None
    channel_reviews: str | None = None
    channel_admin_logs: str | None = None
    channel_age_check: str | None = None
    role_unverified: str | None = None
    role_verified_user: str | None = None
    role_verified_artist: str | None = None
    role_18_verified: str | None = None
    role_moderator: str | None = None


class ServerPatch(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None = None
    settings: ServerSettingsPatch | None = None
