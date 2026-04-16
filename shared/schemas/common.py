import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

class UUIDSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID

class TimestampSchema(UUIDSchema):
    created_at: datetime
    updated_at: datetime