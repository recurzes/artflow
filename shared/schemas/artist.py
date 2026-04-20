import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from shared.models.artist import ArtistStatus
from shared.schemas.common import TimestampSchema


class ArtistCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    server_id: uuid.UUID
    display_name: str
    bio: str | None = None
    styles: list[str] = []
    social_links: dict[str, str] = {}
    portfolio_images: list[str] = []
    price_min_php: Decimal | None = None
    price_max_php: Decimal | None = None
    nsfw_enabled: bool = False
    max_active_commissions: int = 5
    gcash_number: str | None = None
    paypal_email: str | None = None


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
    status: ArtistStatus | None = None
    tos_text: str | None = None
    gcash_number: str | None = None
    paypal_email: str | None = None


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