"""A user-submitted leak report, held for review. Never published automatically."""

from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base
from backend.models.mixins import IdMixin, TimestampMixin

if TYPE_CHECKING:
    from backend.models.user import User


class Report(IdMixin, TimestampMixin, Base):
    __tablename__ = "reports"

    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    site_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending_review",
        server_default="pending_review",
        index=True,
    )

    user: Mapped["User | None"] = relationship()

    __table_args__ = (Index("ix_reports_site_name_lower", func.lower(site_name)),)
