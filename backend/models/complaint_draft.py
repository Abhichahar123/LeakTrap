"""A complaint draft stored for the user to review. Never sent automatically."""

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base
from backend.models.mixins import IdMixin, TimestampMixin

if TYPE_CHECKING:
    from backend.models.consent_receipt import ConsentReceipt
    from backend.models.incident import Incident
    from backend.models.user import User


class ComplaintDraft(IdMixin, TimestampMixin, Base):
    __tablename__ = "complaint_drafts"

    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    # SET NULL: a draft survives deletion of the incident or receipt it cites.
    incident_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("incidents.id", ondelete="SET NULL"), index=True
    )
    consent_receipt_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("consent_receipts.id", ondelete="SET NULL"), index=True
    )
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft", index=True
    )

    user: Mapped["User | None"] = relationship()
    incident: Mapped["Incident | None"] = relationship(back_populates="complaint_drafts")
    consent_receipt: Mapped["ConsentReceipt | None"] = relationship()
