import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, SmallInteger, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from shared.models.artist import Artist
    from shared.models.commission import Commission
    from shared.models.user import User


class Review(Base, TimestampMixin):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("commission_id", name="uq_review_commission"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_review_rating_range")
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    commission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("commissions.id", ondelete="RESTRICT"),
        nullable=False
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False
    )
    artist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artists.id", ondelete="RESTRICT"),
        nullable=False
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    commission: Mapped["Commission"] = relationship(back_populates="review")
    reviewer: Mapped["User"] = relationship(back_populates="reviews_given")
    artist: Mapped["Artist"] = relationship(back_populates="reviews")