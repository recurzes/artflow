import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from api.common import TimestampSchema
from shared.models.artist import ArtistStatus


class ArtistApplication(BaseModel):
    """What a member submits with /artist-apply."""

    discord_guild_id: str = Field(min_length=1, max_length=20)
    discord_user_id: str = Field(min_length=1, max_length=20)
    discord_account_created_at: datetime | None = None
    display_name: str = Field(min_length=1, max_length=100)
    styles: list[str] = []
    social_links: dict[str, str] = {}
    price_min_php: Decimal | None = None
    price_max_php: Decimal | None = None
    gcash_number: str | None = Field(default=None, max_length=20)
    paypal_email: str | None = Field(default=None, max_length=255)


class ArtistApproval(BaseModel):
    moderator_discord_user_id: str = Field(min_length=1, max_length=20)


class ArtistRejection(ArtistApproval):
    reason: str = Field(min_length=1, max_length=1000)


class ArtistUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    display_name: str | None = None
    bio: str | None = None
    styles: list[str] | None = None
    social_links: dict[str, str] | None = None
    portfolio_images: list[str] | None = None
    price_min_php: Decimal | None = None
    price_max_php: Decimal | None = None
    nsfw_enabled: bool | None = None
    max_active_commissions: int | None = None
    tos_text: str | None = None
    gcash_number: str | None = None
    paypal_email: str | None = None


class ArtistAvailability(BaseModel):
    open: bool


class ArtistRead(TimestampSchema):
    user_id: uuid.UUID
    discord_user_id: str
    server_id: uuid.UUID
    display_name: str
    bio: str | None
    styles: list[str]
    social_links: dict[str, str]
    portfolio_images: list[str]
    price_min_php: Decimal | None
    price_max_php: Decimal | None
    nsfw_enabled: bool
    max_active_commissions: int
    rating_avg: Decimal
    rating_count: int
    status: ArtistStatus
    tos_text: str | None
    # SHA-256 of tos_text; a client accepts a specific version of the terms
    tos_hash: str | None
    gcash_number: str | None
    paypal_email: str | None


class ArtistCommissionCapacity(BaseModel):
    count: int
    max: int


class ArtistListItem(BaseModel):
    """Compact view used for the Discord artist directory embed."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    discord_user_id: str
    styles: list[str]
    price_min_php: Decimal | None
    price_max_php: Decimal | None
    rating_avg: Decimal
    rating_count: int
    nsfw_enabled: bool
    status: ArtistStatus