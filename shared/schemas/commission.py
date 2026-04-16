import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from shared.models.commission import CommissionStatus, CurrencyUsed, PaymentMethod
from shared.schemas.common import TimestampSchema


class CommissionCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    server_id: uuid.UUID
    artist_id: uuid.UUID
    client_id: uuid.UUID
    commission_type: str | None = None
    is_nsfw: bool = False
    deadline_at: datetime | None = None
    discord_ticket_channel_id: str | None = None


class QuoteCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    quoted_price_php: Decimal
    quoted_price_usd: Decimal | None = None
    currency_used: CurrencyUsed = CurrencyUsed.PHP
    revisions_allowed: int = 2
    deadline_at: datetime | None = None


class CommissionStatusUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: CommissionStatus
    # Optional fields filled in at specific stage transitions
    payment_method: PaymentMethod | None = None
    payment_receipt_url: str | None = None


class CommissionRead(TimestampSchema):
    server_id: uuid.UUID
    artist_id: uuid.UUID
    client_id: uuid.UUID
    discord_ticket_channel_id: str | None
    status: CommissionStatus
    commission_type: str | None
    is_nsfw: bool
    quoted_price_php: Decimal | None
    quoted_price_usd: Decimal | None
    currency_used: CurrencyUsed | None
    tos_accepted_at: datetime | None
    payment_method: PaymentMethod | None
    payment_receipt_url: str | None
    payment_confirmed_at: datetime | None
    revisions_used: int
    revisions_allowed: int
    deadline_at: datetime | None
    delivered_at: datetime | None
    completed_at: datetime | None
    platform_fee_php: Decimal | None
