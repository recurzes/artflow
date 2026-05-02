from datetime import datetime
from typing import Literal

from pydantic import EmailStr, BaseModel, Field

from shared.schemas.common import TimestampSchema


class UserCreate(TimestampSchema):
    model_config = TimestampSchema.model_config

    discord_user_id: str
    is_phone_verified: bool = False
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

    discord_user_id: str = Field(min_length=1, max_length=20)
    is_phone_verified: bool = False
    discord_account_created_at: datetime | None = None


class Verify18Response(BaseModel):
    status: Literal["approved", "pending_mode", "already_verified"]
    detail: str | None = None


class Verify18ApproveBody(BaseModel):
    discord_user_id: str = Field(min_length=1, max_length=20)