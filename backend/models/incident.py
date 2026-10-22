"""A suspicious message or contact reported by the user."""

from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base
from backend.models.mixins import CreatedAtMixin, IdMixin

if TYPE_CHECKING:
    from backend.models.complaint_draft import ComplaintDraft
    from backend.models.user import User

INCIDENT_CHANNELS = ("email", "sms", "call")


class Incident(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "incidents"

    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    message_text: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(String(50))
    matched_site: Mapped[str | None] = mapped_column(String(255), index=True)
    confidence: Mapped[str | None] = mapped_column(String(32))
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    user: Mapped["User | None"] = relationship()
    complaint_drafts: Mapped[list["ComplaintDraft"]] = relationship(
        back_populates="incident", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint(
            "channel IN (" + ", ".join(f"'{c}'" for c in INCIDENT_CHANNELS) + ")",
            name="channel_allowed",
        ),
        Index("ix_incidents_user_id_created_at", "user_id", "created_at"),
    )
