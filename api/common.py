import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Field types shared by the request schemas. Validation happens once, here at
# the edge; services never receive a value outside these bounds.

# A Discord snowflake, as a string (they are too large for a JSON number)
DiscordId = Annotated[str, StringConstraints(pattern=r"^\d{15,20}$")]

# An amount of money: to the centavo, within the NUMERIC(10, 2) columns
Money = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class UUIDSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID

class TimestampSchema(UUIDSchema):
    created_at: datetime
    updated_at: datetime
