import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from api.common import DiscordId, Money, ShortText, TimestampSchema
from shared.models.artist import ArtistStatus

Style = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=40)
]
GcashNumber = Annotated[str, StringConstraints(pattern=r"^\d{7,20}$")]


class _ArtistProfileRules(BaseModel):
    """Checks shared by an application and a profile edit."""

    @field_validator("social_links", check_fields=False)
    @classmethod
    def _social_links_are_reasonable(cls, links: dict[str, str] | None) -> dict[str, str] | None:
        if links is None:
            return links
        if len(links) > 10:
            raise ValueError("At most 10 social links")
        for label, url in links.items():
            if not 1 <= len(label) <= 40 or not 1 <= len(url) <= 300:
                raise ValueError("A social link needs a label (max 40) and a URL (max 300)")
        return links

    @model_validator(mode="after")
    def _price_range_is_ordered(self) -> "_ArtistProfileRules":
        low = getattr(self, "price_min_php", None)
        high = getattr(self, "price_max_php", None)
        if low is not None and high is not None and low > high:
            raise ValueError("The minimum price cannot be above the maximum price")
        return self


class ArtistApplication(_ArtistProfileRules):
    """What a member submits with /artist-apply."""

    discord_guild_id: DiscordId
    discord_user_id: DiscordId
    discord_account_created_at: datetime | None = None
    display_name: ShortText
    styles: list[Style] = Field(default=[], max_length=15)
    social_links: dict[str, str] = {}
    price_min_php: Money | None = None
    price_max_php: Money | None = None
    gcash_number: GcashNumber | None = None
    paypal_email: EmailStr | None = None


class ArtistApproval(BaseModel):
    moderator_discord_user_id: DiscordId


class ArtistRejection(ArtistApproval):
    reason: str = Field(min_length=1, max_length=1000)


class ArtistUpdate(_ArtistProfileRules):
    model_config = ConfigDict(from_attributes=True)

    display_name: ShortText | None = None
    bio: str | None = Field(default=None, max_length=2000)
    styles: list[Style] | None = Field(default=None, max_length=15)
    social_links: dict[str, str] | None = None
    portfolio_images: list[str] | None = Field(default=None, max_length=20)
    price_min_php: Money | None = None
    price_max_php: Money | None = None
    nsfw_enabled: bool | None = None
    max_active_commissions: int | None = Field(default=None, ge=1, le=50)
    tos_text: str | None = Field(default=None, min_length=1, max_length=6000)
    gcash_number: GcashNumber | None = None
    paypal_email: EmailStr | None = None


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