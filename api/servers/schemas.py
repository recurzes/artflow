from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from api.common import DiscordId, ShortText, TimestampSchema
from shared.models.server import SubscriptionTier

# IDs of channels and roles the bot created. Looser than DiscordId on purpose:
# these are read back from stored settings as well as written.
SettingId = Annotated[str, StringConstraints(pattern=r"^\d{1,20}$")]


class ServerSettings(BaseModel):
    """JSONB settings blob stored in servers.settings."""

    model_config = ConfigDict(from_attributes=True)

    timezone: str = Field(default="Asia/Manila", max_length=64)
    default_currency: Literal["PHP", "USD", "BOTH"] = "PHP"
    nsfw_enabled: bool = False
    max_active_commissions_per_artist: int = Field(default=5, ge=1, le=50)
    commission_expiry_hours: int = Field(default=24, ge=1, le=168)
    # Discord channel IDs (filled in when the bot provisions the server)
    channel_verification: SettingId | None = None
    channel_bot_commands: SettingId | None = None
    channel_artist_directory: SettingId | None = None
    channel_verification_queue: SettingId | None = None
    channel_commissions_open: SettingId | None = None
    channel_completed_works: SettingId | None = None
    channel_reviews: SettingId | None = None
    channel_admin_logs: SettingId | None = None
    channel_age_check: SettingId | None = None
    # Discord role IDs
    role_unverified: SettingId | None = None
    role_verified_user: SettingId | None = None
    role_verified_artist: SettingId | None = None
    role_18_verified: SettingId | None = None
    role_moderator: SettingId | None = None


class ServerCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    discord_guild_id: DiscordId
    name: ShortText
    settings: ServerSettings = ServerSettings()


class ServerRead(TimestampSchema):
    discord_guild_id: str
    name: str
    subscription_tier: SubscriptionTier
    subscription_expires_at: datetime | None
    settings: ServerSettings

class ServerSettingsPatch(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timezone: str | None = Field(default=None, max_length=64)
    default_currency: Literal["PHP", "USD", "BOTH"] | None = None
    nsfw_enabled: bool | None = None
    max_active_commissions_per_artist: int | None = Field(default=None, ge=1, le=50)
    commission_expiry_hours: int | None = Field(default=None, ge=1, le=168)
    channel_verification: SettingId | None = None
    channel_bot_commands: SettingId | None = None
    channel_artist_directory: SettingId | None = None
    channel_verification_queue: SettingId | None = None
    channel_commissions_open: SettingId | None = None
    channel_completed_works: SettingId | None = None
    channel_reviews: SettingId | None = None
    channel_admin_logs: SettingId | None = None
    channel_age_check: SettingId | None = None
    role_unverified: SettingId | None = None
    role_verified_user: SettingId | None = None
    role_verified_artist: SettingId | None = None
    role_18_verified: SettingId | None = None
    role_moderator: SettingId | None = None


class ServerPatch(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: ShortText | None = None
    settings: ServerSettingsPatch | None = None
