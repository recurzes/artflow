import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    # Fetch server-generated values (updated_at) with RETURNING on UPDATE as well
    # as INSERT; an async session cannot lazily load them afterwards.
    __mapper_args__ = {"eager_defaults": True}

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        # Set whenever the ORM updates a row. The database's clock, like created_at:
        # mixing it with the application's clock lets the two disagree. Wall-clock
        # rather than now(), which is frozen at the start of the transaction.
        onupdate=func.clock_timestamp(),
        nullable=False
    )

def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )