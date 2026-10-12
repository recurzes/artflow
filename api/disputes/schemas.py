from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.models.dispute import DisputeStatus


class DisputeCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    commission_id: uuid.UUID
    raised_by_discord_user_id: str = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=8000)


class DisputeResolve(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resolution: str = Field(min_length=1, max_length=8000)
    set_commission_status: Literal["COMPLETED", "CANCELLED"] = "CANCELLED"
    resolved_by_discord_user_id: str = Field(min_length=1, max_length=20)


class DisputeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    commission_id: uuid.UUID
    raised_by: uuid.UUID
    reason: str
    status: DisputeStatus
    resolution: str | None
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None