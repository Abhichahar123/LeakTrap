"""Response models for the local dashboard API. Aliases, nicknames, sender
addresses, subjects and message hashes are deliberately absent."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

NOT_PROOF = (
    "A match links a message to one of your signups. It is not proof that a site "
    "leaked, sold or shared your data."
)


class ScopeInfo(BaseModel):
    user_id: int | None = Field(description="null means records that have no user.")
    note: str = "Scope is a filter, not access control: there is no authentication yet."


class OverviewResponse(BaseModel):
    scope: ScopeInfo
    signups_total: int
    emails_total: int
    matched: int
    ambiguous: int
    no_match: int
    unprocessed: int = Field(description="Mail records without a stored match status.")
    notice: str = NOT_PROOF


class DashboardSignup(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_name: str
    site_domain: str | None
    alias_masked: str | None = Field(description="Only the alias domain, e.g. •••@leaktrap.xyz.")
    has_nickname: bool
    has_surname_variant: bool
    real_name_required: bool
    email_count: int
    created_at: datetime


class DashboardSignupPage(BaseModel):
    scope: ScopeInfo
    items: list[DashboardSignup]
    total: int
    limit: int
    offset: int


class DashboardEmail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    received_at: datetime
    created_at: datetime
    match_status: str | None
    match_confidence: str | None
    recipient_known: bool
    signup_id: int | None
    site_name: str | None
    site_domain: str | None
    sender_domain: str | None = Field(description="Claimed sender domain; may be forged.")


class DashboardEmailPage(BaseModel):
    scope: ScopeInfo
    items: list[DashboardEmail]
    total: int
    limit: int
    offset: int


class DashboardEmailDetail(DashboardEmail):
    stored_details: str = (
        "Only the match status and confidence were stored for this message. Signal-level "
        "explanations are produced when the matcher runs; use the matcher check to see them."
    )
    limitations: list[str]
    notice: str = NOT_PROOF
