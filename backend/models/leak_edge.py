"""A directed edge in the leak relationship graph.

source_id and target_id are generic identifiers whose meaning depends on
source_type and target_type, so the database cannot enforce them as foreign
keys. Application code must validate them.
"""

from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base
from backend.models.mixins import CreatedAtMixin, IdMixin

if TYPE_CHECKING:
    from backend.models.user import User


class LeakEdge(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "leak_edges"

    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confidence: Mapped[str | None] = mapped_column(String(32))

    user: Mapped["User | None"] = relationship()

    __table_args__ = (
        Index("ix_leak_edges_source", source_type, source_id),
        Index("ix_leak_edges_target", target_type, target_id),
    )
