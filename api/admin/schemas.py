import uuid
from decimal import Decimal

from pydantic import BaseModel

from shared.models.artist import ArtistStatus


class AdminStats(BaseModel):
    active_commissions: int
    completed_today: int
    revenue_php_this_month: Decimal


class AdminArtist(BaseModel):
    id: uuid.UUID
    display_name: str
    discord_user_id: str
    status: ArtistStatus
    nsfw_enabled: bool
    active_commission_count: int


class AdminArtistList(BaseModel):
    artists: list[AdminArtist]
    limit: int
    offset: int


class CommissionSummary(BaseModel):
    by_status: dict[str, int]
