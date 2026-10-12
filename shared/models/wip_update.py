import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from shared.models.artist import Artist
    from shared.models.commission import Commission


class WipUpdate(Base, TimestampMixin):
    __tablename__ = "wip_updates"

    id: Mapped[uuid.UUID] = uuid_pk()
    commission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("commissions.id", ondelete="CASCADE"),
        nullable=False
    )
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    watermarked_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    artist_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    commission: Mapped["Commission"] = relationship(back_populates="wip_updates")
    artist: Mapped["Artist"] = relationship(
        secondary="commissions",
        primaryjoin="WipUpdate.commission_id == Commission.id",
        secondaryjoin="Commission.artist_id == Artist.id",
        viewonly=True
    )