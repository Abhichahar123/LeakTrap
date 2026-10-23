"""LeakTrace account.

Rows created before accounts existed have no email or password; they cannot
sign in. Records owned by no user are visible to nobody.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base
from backend.models.mixins import CreatedAtMixin, IdMixin


class User(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "users"

    # Added in migration 0004. Stored lowercased.
    email: Mapped[str | None] = mapped_column(String(320))
    # Argon2id hash (argon2-cffi). Never the password itself.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), sort_order=11
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("uq_users_email_lower", func.lower(email), unique=True, postgresql_where=email.is_not(None)),
        # An account has both credentials or neither (rows from before accounts).
        CheckConstraint("(email IS NULL) = (password_hash IS NULL)", name="credentials_complete"),
    )
