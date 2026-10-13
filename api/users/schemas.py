from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr

from api.common import DiscordId, TimestampSchema


class UserCreate(BaseModel):
    discord_user_id: DiscordId
    discord_account_created_at: datetime | None = None

class UserRead(TimestampSchema):
    discord_user_id: str
    email: EmailStr | None
    is_email_verified: bool
    is_18_verified: bool
    is_18_verified_at: datetime | None
    is_phone_verified: bool
    trust_score: int
    discord_account_created_at: datetime | None


class Verify18Submit(BaseModel):
    model_config = {"from_attributes": False}

    discord_user_id: DiscordId
    discord_account_created_at: datetime | None = None


class Verify18Response(BaseModel):
    status: Literal["approved", "pending_mod", "already_verified"]
    detail: str | None = None
    # True the first time a pending request is recorded, False when the member
    # asks again while still waiting. The bot notifies moderators only once.
    newly_queued: bool = False


class Verify18ApproveBody(BaseModel):
    discord_user_id: DiscordId