"""Captured privacy notice and consent text at signup time."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base
from backend.models.mixins import CreatedAtMixin, IdMixin

if TYPE_CHECKING:
    from backend.models.signup import Signup
    from backend.models.user import User


RECEIPT_ACTIONS = ("accepted", "declined", "notice_only")
# Only manual entry exists so far. There is deliberately no "verified" source:
# nothing in LeakTrace verifies what a user reports.
CAPTURE_SOURCES = ("manual",)
# Stored in privacy_notice_text (NOT NULL) when only a hash of the notice is kept.
NOTICE_TEXT_NOT_STORED = ""


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class ConsentReceipt(IdMixin, CreatedAtMixin, Base):
    """What a user reported about a privacy notice or consent prompt.

    A receipt never proves that legally valid consent was given, that a site
    complied with the law, or that a violation occurred. created_at is when
    LeakTrace recorded it; reported_occurred_at is when the user says the
    event happened.
    """

    __tablename__ = "consent_receipts"

    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    # SET NULL: deleting a signup keeps the receipt as evidence.
    signup_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("signups.id", ondelete="SET NULL"), index=True
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    privacy_notice_text: Mapped[str] = mapped_column(Text, nullable=False)
    consent_text: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    content_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    # Added in migration 0003. NULL on older rows means "not reported".
    action: Mapped[str | None] = mapped_column(String(16))
    capture_source: Mapped[str | None] = mapped_column(String(32))
    notice_version: Mapped[str | None] = mapped_column(String(100))
    reported_occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User | None"] = relationship()
    signup: Mapped["Signup | None"] = relationship(back_populates="consent_receipts")

    __table_args__ = (
        CheckConstraint(_in("action", RECEIPT_ACTIONS), name="action_allowed"),
        CheckConstraint(_in("capture_source", CAPTURE_SOURCES), name="capture_source_allowed"),
    )
