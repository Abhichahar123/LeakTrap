"""Minimal user record for future account ownership (no authentication yet)."""

from backend.database import Base
from backend.models.mixins import CreatedAtMixin, IdMixin


class User(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "users"
