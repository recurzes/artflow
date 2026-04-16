import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin, uuid_pk

class DisputeStatus(str, enum.Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"


class Dispute(Base, TimestampMixin):
    __tablename__ = "disputes"
    __table_args__ = (UniqueConstraint("commission_id", name="uq_dispute_commission"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    commission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("commissions.id", ondelete="RESTRICT"),
        nullable=False
    )
    raised_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DisputeStatus] = mapped_column(
        default=DisputeStatus.OPEN,
        nullable=False
    )
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    # Relationships
    commission: Mapped["Commission"] = relationship(back_populates="dispute")
    raised_by_user: Mapped["User"] = relationship(
        back_populates="disputes_raised",
        foreign_keys=[raised_by]
    )
    resolved_by_user: Mapped["User | None"] = relationship(foreign_keys=[resolved_by])