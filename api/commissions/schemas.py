import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from api.common import DiscordId, Money, PositiveMoney, TimestampSchema
from shared.models.commission import CommissionStatus, CurrencyUsed, PaymentMethod


class CommissionCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    server_id: uuid.UUID
    artist_id: uuid.UUID
    client_id: uuid.UUID
    commission_type: str | None = Field(default=None, max_length=100)
    is_nsfw: bool = False
    deadline_at: datetime | None = None


class TicketOpenBody(BaseModel):
    discord_ticket_channel_id: DiscordId


class QuoteCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    quoted_price_php: PositiveMoney
    quoted_price_usd: Money | None = None
    currency_used: CurrencyUsed = CurrencyUsed.PHP
    revisions_allowed: int = Field(default=2, ge=0, le=20)
    deadline_at: datetime | None = None


class TosAcceptBody(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tos_version_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class IntakeSubmitBody(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    notes: str = Field(min_length=1, max_length=12000)


class CounterOfferBody(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    notes: str = Field(default="", max_length=2000)


class CommissionRead(TimestampSchema):
    server_id: uuid.UUID
    artist_id: uuid.UUID
    client_id: uuid.UUID
    artist_discord_user_id: str
    client_discord_user_id: str
    discord_ticket_channel_id: str | None
    status: CommissionStatus
    commission_type: str | None
    is_nsfw: bool
    client_intake_notes: str | None
    quoted_price_php: Decimal | None
    quoted_price_usd: Decimal | None
    currency_used: CurrencyUsed | None
    tos_accepted_at: datetime | None
    tos_version_hash: str | None
    payment_method: PaymentMethod | None
    payment_receipt_key: str | None
    payment_confirmed_at: datetime | None
    revisions_used: int
    revisions_allowed: int
    deadline_at: datetime | None
    delivered_at: datetime | None
    completed_at: datetime | None
    payment_deadline_at: datetime | None
    payment_reminder_sent: bool
    delivery_file_key: str | None
    delivery_auto_accept_at: datetime | None
    platform_fee_php: Decimal | None


class CommissionFiles(BaseModel):
    """Short-lived links to a commission's stored files, signed on request."""

    receipt_url: str | None
    delivery_url: str | None
