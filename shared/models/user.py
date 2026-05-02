import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin, uuid_pk


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    discord_user_id: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False,
        index=True
    )
    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )
    is_email_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )
    is_18_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )
    is_18_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    discord_account_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    is_phone_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )
    trust_score: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False
    )

    # Relationships
    artist_profiles: Mapped[list["Artist"]] = relationship(back_populates="user", foreign_keys="Artist.user_id")
    commissions_as_client: Mapped[list["Commission"]] = relationship(back_populates="client", foreign_keys="Commission.client_id")
    reviews_given: Mapped[list["Review"]] = relationship(back_populates="reviewer")
    disputes_raised: Mapped[list["Dispute"]] = relationship(
        back_populates="raised_by_user",
        foreign_keys="Dispute.raised_by"
    )
