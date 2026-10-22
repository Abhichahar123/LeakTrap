"""Request and response models for the extension's per-site alias recall."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.services.domains import normalize_domain


class AutofillLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_domain: str = Field(description="Exact domain of the current site, e.g. shop.example.com.")

    @field_validator("site_domain")
    @classmethod
    def check_domain(cls, value: str) -> str:
        return normalize_domain(value)


class AutofillSignup(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_name: str
    site_domain: str | None
    alias: str | None
    nickname: str | None
    real_name_required: bool
    created_at: datetime


class AutofillLookupResponse(BaseModel):
    site_domain: str
    items: list[AutofillSignup] = Field(description="Exact-domain matches in this scope, newest first (max 10).")
    note: str = (
        "Exact domain match only; other subdomains are not included. Scope is a filter, "
        "not authentication."
    )
