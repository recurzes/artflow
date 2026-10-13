import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, false
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from shared.models.artist import Artist
    from shared.models.dispute import Dispute
    from shared.models.review import Review
    from shared.models.server import Server
    from shared.models.user import User
    from shared.models.wip_update import WipUpdate


class CommissionStatus(str, enum.Enum):
    INQUIRY = "INQUIRY"
    INTAKE = "INTAKE"
    QUOTED = "QUOTED"
    TOS_PENDING = "TOS_PENDING"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    WIP = "WIP"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"

class PaymentMethod(str, enum.Enum):
    GCASH = "GCASH"
    PAYPAL = "PAYPAL"
    MAYA = "MAYA"
    WISE = "WISE"
    OTHER = "OTHER"

class CurrencyUsed(str, enum.Enum):
    PHP = "PHP"
    USD = "USD"
    BOTH = "BOTH"


class Commission(Base, TimestampMixin):
    __tablename__ = "commissions"

    id: Mapped[uuid.UUID] = uuid_pk()
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    artist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artists.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    # Looked up on every command run in a ticket; one commission per channel
    discord_ticket_channel_id: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        unique=True,
        index=True
    )
    status: Mapped[CommissionStatus] = mapped_column(
        default=CommissionStatus.INQUIRY,
        nullable=False,
        index=True
    )
    commission_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )
    is_nsfw: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )
    client_intake_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pricing
    quoted_price_php: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    quoted_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency_used: Mapped[CurrencyUsed | None] = mapped_column(nullable=True)

    # TOS
    tos_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    tos_version_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True
    )

    # Payment
    payment_method: Mapped[PaymentMethod | None] = mapped_column(nullable=True)
    payment_receipt_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    # Revisions
    revisions_used: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False
    )
    revisions_allowed: Mapped[int] = mapped_column(
        Integer,
        default=2,
        nullable=False
    )

    # Timeline
    deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    payment_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True
    )
    payment_reminder_sent: Mapped[bool] = mapped_column(
        default=False,
        server_default=false(),
        nullable=False
    )
    delivery_file_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_auto_accept_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True
    )

    # 3% platform fee
    platform_fee_php: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)


    # Relationships
    server: Mapped["Server"] = relationship(back_populates="commissions")
    artist: Mapped["Artist"] = relationship(back_populates="commissions")
    client: Mapped["User"] = relationship(
        back_populates="commissions_as_client",
        foreign_keys=[client_id]
    )
    wip_updates: Mapped[list["WipUpdate"]] = relationship(
        back_populates="commission",
        cascade="all, delete-orphan"
    )
    review: Mapped["Review | None"] = relationship(
        back_populates="commission",
        uselist=False
    )
    dispute: Mapped["Dispute | None"] = relationship(
        back_populates="commission",
        uselist=False
    )

    # Read by CommissionRead. Both need `client` and `artist.user` to be loaded,
    # which every query in the commission service does.
    @property
    def client_discord_user_id(self) -> str:
        return self.client.discord_user_id

    @property
    def artist_discord_user_id(self) -> str:
        return self.artist.user.discord_user_id