import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from shared.models.commission import Commission
    from shared.models.review import Review
    from shared.models.server import Server
    from shared.models.user import User
    from shared.models.wip_update import WipUpdate


class ArtistStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"
    REJECTED = "REJECTED"

class Artist(Base, TimestampMixin):
    __tablename__ = "artists"
    # One artist profile per member per server
    __table_args__ = (UniqueConstraint("user_id", "server_id", name="uq_artist_user_server"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    display_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )
    bio: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )
    styles: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False
    )
    social_links: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False
    )
    portfolio_images: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False
    )
    price_min_php: Mapped[float | None] = mapped_column(
        Numeric(10, 2),
        nullable=True
    )
    price_max_php: Mapped[float | None] = mapped_column(
        Numeric(10, 2),
        nullable=True
    )
    nsfw_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )
    max_active_commissions: Mapped[int] = mapped_column(
        Integer,
        default=5,
        nullable=False
    )
    rating_avg: Mapped[float] = mapped_column(
        Numeric(3, 2),
        default=0.0,
        nullable=False
    )
    rating_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False
    )
    status: Mapped[ArtistStatus] = mapped_column(
        default=ArtistStatus.PENDING,
        nullable=False
    )
    # TOS
    tos_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True
    )
    # Set when an application is turned down; the applicant may reapply later
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )
    # Gcash
    gcash_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    paypal_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(
        back_populates="artist_profiles",
        foreign_keys=[user_id]
    )
    server: Mapped["Server"] = relationship(back_populates="artists")
    commissions: Mapped[list["Commission"]] = relationship(back_populates="artist")
    reviews: Mapped[list["Review"]] = relationship(back_populates="artist")
    wip_updates: Mapped[list["WipUpdate"]] = relationship(
        back_populates="artist",
        secondary="commissions",
        primaryjoin="Artist.id == Commission.artist_id",
        secondaryjoin="Commission.id == WipUpdate.commission_id",
        viewonly=True
    )