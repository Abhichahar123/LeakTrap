"""Column mixins shared by several models."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, func
from sqlalchemy.orm import Mapped, mapped_column


class IdMixin:
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, sort_order=-10
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), sort_order=10
    )


class TimestampMixin(CreatedAtMixin):
    # onupdate is applied by the ORM; raw SQL updates must set it themselves.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        sort_order=11,
    )
