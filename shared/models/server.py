import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin, uuid_pk

class SubscriptionTier(str, enum.Enum):
    FREE = "FREE"
    STARTER = "STARTER"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"

class Server(Base, TimestampMixin):
    __tablename__ = "servers"

    id: Mapped[uuid.UUID] = uuid_pk()
    discord_guild_id: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )
    subscription_tier: Mapped[SubscriptionTier] = mapped_column(
        default=SubscriptionTier.FREE,
        nullable=False
    )
    subscription_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    settings: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False
    )
    artists: Mapped[list["Artist"]] = relationship(back_populates="server")
    commissions: Mapped[list["Commission"]] = relationship(back_populates="server")