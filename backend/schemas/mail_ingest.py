"""Request and response models for email ingestion."""

from datetime import timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from backend.services.domains import normalize_email
from backend.services.mail_ingest import now

MAX_CLOCK_SKEW = timedelta(minutes=5)
MAX_AGE = timedelta(days=30)


class MailIngestRequest(BaseModel):
    """Minimal metadata about one inbound email, sent by the email Worker.

    There are deliberately no fields for the body, attachments or authentication
    verdicts (SPF/DKIM); claims like those are not accepted.
    """

    model_config = ConfigDict(extra="forbid")

    recipient: str = Field(description="Envelope recipient (an alias).", examples=["pz1l@leaktrap.xyz"])
    envelope_from: str | None = Field(
        default=None, description="Envelope sender from the SMTP session. Empty for bounces.",
        examples=["bounce@mailer.example"],
    )
    from_header: str | None = Field(
        default=None, max_length=998, description="Raw From header. Untrusted.",
        examples=["Example Deals <deals@broker.example>"],
    )
    subject: str | None = Field(
        default=None, max_length=998, description="Raw Subject header. Untrusted; never stored."
    )
    message_id: str | None = Field(
        default=None, max_length=998, description="Message-ID header, used only for deduplication."
    )
    received_at: AwareDatetime | None = Field(
        default=None, description="When the Worker received the message (timezone required)."
    )

    @field_validator("recipient")
    @classmethod
    def check_recipient(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("envelope_from")
    @classmethod
    def check_envelope_from(cls, value: str | None) -> str | None:
        if value is None or value.strip() in ("", "<>"):
            return None
        return normalize_email(value)

    @field_validator("message_id")
    @classmethod
    def check_message_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().strip("<>").strip()
        if not value or any(ch.isspace() or ord(ch) < 32 for ch in value):
            raise ValueError("message_id must be a single token without whitespace")
        return value

    @field_validator("received_at")
    @classmethod
    def check_received_at(cls, value):
        if value is None:
            return None
        current = now()
        if value > current + MAX_CLOCK_SKEW:
            raise ValueError("received_at is in the future")
        if value < current - MAX_AGE:
            raise ValueError("received_at is more than 30 days old")
        return value


class MailIngestResponse(BaseModel):
    status: Literal["accepted", "duplicate"]
    mail_log_id: int
    recipient_known: bool = Field(description="Whether the recipient is a stored alias.")
    match_status: str = Field(description='"matched", "ambiguous" or "no_match". Never proof of a leak.')
    match_confidence: str
