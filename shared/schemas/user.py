from datetime import datetime

from pydantic import EmailStr

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
    is_phone_verified: bool
    trust_score: int
    discord_account_created_at: datetime | None