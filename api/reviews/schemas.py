import uuid

from pydantic import BaseModel, ConfigDict, Field

from api.common import TimestampSchema


class ReviewCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rating: int = Field(ge=1, le=5)
    body: str | None = Field(default=None, max_length=2000)
    is_public: bool = True


class ReviewRead(TimestampSchema):
    commission_id: uuid.UUID
    reviewer_id: uuid.UUID
    artist_id: uuid.UUID
    rating: int
    body: str | None
    is_public: bool