"""Request and response models for consent receipts."""

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.schemas.signup import MAX_BIGINT

MAX_NOTICE_TEXT = 20_000
MAX_CONSENT_TEXT = 2_000
MAX_URL = 2_048
EARLIEST_EVENT = datetime(1990, 1, 1, tzinfo=timezone.utc)
MAX_CLOCK_SKEW = timedelta(minutes=5)
_HASH = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")

LEGAL_NOTICE = (
    "A receipt records what you reported. It does not prove that legally valid consent "
    "was given, that the site complied with data-protection law, or that a violation occurred."
)
TIMESTAMP_NOTE = (
    "recorded_at is when LeakTrace saved this receipt. reported_occurred_at is the time "
    "you reported for the event, if any; LeakTrace has not verified it."
)


def sha256_of(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check_text(value: str | None, name: str, limit: int) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise ValueError(f"{name} must not be blank")
    if len(value) > limit:
        raise ValueError(f"{name} must be at most {limit} characters")
    if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in value):
        raise ValueError(f"{name} must not contain control characters")
    return value


class ConsentReceiptCreate(BaseModel):
    """A receipt you are reporting manually. The server never fetches URLs and
    records the receipt as user-reported; nothing here is verified."""

    model_config = ConfigDict(extra="forbid")

    signup_id: int = Field(gt=0, le=MAX_BIGINT)
    action: Literal["accepted", "declined", "notice_only"] = Field(
        description="What you did: accepted, declined, or only saw the notice."
    )
    source_url: str | None = Field(default=None, description="Privacy notice URL (http/https). Not fetched.")
    notice_version: str | None = Field(default=None, description='Version or date shown, e.g. "2026-01-15".')
    content_hash: str | None = Field(
        default=None, description="SHA-256 of the notice text, as 64 hex characters or sha256:<hex>."
    )
    notice_text: str | None = Field(
        default=None,
        description=f"Optional notice text, up to {MAX_NOTICE_TEXT} characters. Prefer sending only the hash.",
    )
    consent_text: str | None = Field(default=None, description="Wording of the consent prompt, if any.")
    reported_occurred_at: AwareDatetime | None = Field(
        default=None, description="When the event happened, if you know (timezone required)."
    )

    @field_validator("source_url")
    @classmethod
    def check_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or len(value) > MAX_URL or any(ch.isspace() or ord(ch) < 32 for ch in value):
            raise ValueError(f"source_url must be a single URL of at most {MAX_URL} characters")
        parts = urlsplit(value)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            raise ValueError("source_url must be an http or https URL with a host")
        if parts.username or parts.password:
            raise ValueError("source_url must not contain credentials")
        return value

    @field_validator("notice_version")
    @classmethod
    def check_version(cls, value: str | None) -> str | None:
        value = _check_text(value, "notice_version", 100)
        return " ".join(value.split()) if value else None

    @field_validator("content_hash")
    @classmethod
    def check_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        match = _HASH.match(value.strip())
        if not match:
            raise ValueError("content_hash must be 64 hex characters, optionally prefixed sha256:")
        return "sha256:" + match.group(1).lower()

    @field_validator("notice_text")
    @classmethod
    def check_notice_text(cls, value: str | None) -> str | None:
        return _check_text(value, "notice_text", MAX_NOTICE_TEXT)

    @field_validator("consent_text")
    @classmethod
    def check_consent_text(cls, value: str | None) -> str | None:
        return _check_text(value, "consent_text", MAX_CONSENT_TEXT)

    @field_validator("reported_occurred_at")
    @classmethod
    def check_occurred_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value > datetime.now(timezone.utc) + MAX_CLOCK_SKEW:
            raise ValueError("reported_occurred_at is in the future")
        if value < EARLIEST_EVENT:
            raise ValueError("reported_occurred_at is before 1990")
        return value

    @model_validator(mode="after")
    def check_hash_matches_text(self) -> "ConsentReceiptCreate":
        if self.notice_text is not None:
            computed = sha256_of(self.notice_text)
            if self.content_hash is not None and self.content_hash != computed:
                raise ValueError("content_hash does not match notice_text")
            self.content_hash = computed
        if not any((self.source_url, self.content_hash, self.notice_version, self.consent_text)):
            raise ValueError(
                "provide at least one of source_url, content_hash, notice_text, "
                "notice_version or consent_text"
            )
        return self


class ConsentReceiptSummary(BaseModel):
    id: int
    signup_id: int | None
    site_name: str | None = Field(description="From the linked signup; null if it was deleted.")
    site_domain: str | None
    action: str | None = Field(description="null on receipts recorded before actions were stored.")
    capture_source: str | None
    evidence_basis: Literal["user_reported", "unknown"] = Field(
        description="user_reported for manual receipts. No receipt is verified by LeakTrace."
    )
    recorded_at: datetime = Field(description="When LeakTrace saved the receipt (server time).")
    reported_occurred_at: datetime | None = Field(description="User-reported event time; unverified.")
    source_url: str | None
    notice_version: str | None
    content_hash: str | None
    notice_text_stored: bool
    consent_text_stored: bool


class ConsentReceiptDetail(ConsentReceiptSummary):
    notice_text: str | None
    consent_text: str | None
    legal_notice: str = LEGAL_NOTICE
    timestamp_note: str = TIMESTAMP_NOTE


class ConsentReceiptPage(BaseModel):
    items: list[ConsentReceiptSummary]
    total: int
    limit: int
    offset: int
    legal_notice: str = LEGAL_NOTICE
