"""Response models for the personal dashboard API (the signed-in user's own data).

Full email senders, subjects, message hashes and bodies are never returned.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

NOT_PROOF = (
    "A match links a message to one of your signups. It is not proof that a site "
    "leaked, sold or shared your data."
)


class OverviewResponse(BaseModel):
    websites: int
    aliases: int
    nicknames: int
    receipts: int
    emails_total: int
    matched: int
    ambiguous: int
    no_match: int
    unprocessed: int = Field(description="Mail records without a stored match status.")
    investigations: int = Field(description="Matcher results you chose to record.")
    notice: str = NOT_PROOF


class DashboardSignup(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_name: str
    site_domain: str | None
    alias: str | None
    nickname: str | None
    real_name_required: bool
    receipt_count: int
    email_count: int
    created_at: datetime


class DashboardSignupPage(BaseModel):
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


class SignupReceipt(BaseModel):
    id: int
    action: str | None
    evidence_basis: str
    recorded_at: datetime
    reported_occurred_at: datetime | None
    source_url: str | None


class SignupDetailResponse(BaseModel):
    id: int
    site_name: str
    site_domain: str | None
    alias: str | None
    nickname: str | None
    surname_variant: str | None
    real_name_required: bool
    real_name_used: bool
    created_at: datetime
    receipts: list[SignupReceipt] = Field(description="Most recent 20.")
    emails: list[DashboardEmail] = Field(description="Most recent 20.")
    notice: str = NOT_PROOF


class Investigation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    channel: str
    result: str | None = Field(description='"matched", "ambiguous" or "no_match"; never a confirmed leak.')
    confidence: str | None
    matched_site: str | None
    recipient_alias_matched: bool
    sender_domain: str | None
    candidate_count: int
    signal_types: list[str]


class InvestigationPage(BaseModel):
    items: list[Investigation]
    total: int
    limit: int
    offset: int
    notice: str = NOT_PROOF
