"""Request and response models for the leak matcher."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.schemas.signup import MAX_BIGINT
from backend.services.domains import normalize_email


def _clean_text(value: str | None, name: str, max_length: int) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    if not value:
        raise ValueError(f"{name} must not be blank")
    if len(value) > max_length:
        raise ValueError(f"{name} must be at most {max_length} characters")
    return value


class MatchCheckRequest(BaseModel):
    """Clues from one suspicious email. Send only these fields, never the body.

    At least one of recipient, sender, nickname or surname_variant is required.
    The subject is only searched for the nickname of signups found by other clues.
    """

    model_config = ConfigDict(extra="forbid")

    recipient: str | None = Field(
        default=None, description="Address the message was sent to.", examples=["pz1l@leaktrap.xyz"]
    )
    sender: str | None = Field(
        default=None, description="Address the message claims to be from.",
        examples=["offers@broker.example"],
    )
    subject: str | None = Field(default=None, examples=["Hi Ocelot, a special offer"])
    nickname: str | None = Field(default=None, description="A nickname the message addressed you by.")
    surname_variant: str | None = Field(default=None, description="A surname the message used.")
    user_id: int | None = Field(
        default=None, gt=0, le=MAX_BIGINT,
        description="Owner scope to search. Omit for signups without a user. Not authenticated.",
    )
    record_incident: bool = Field(
        default=False, description="Opt in to saving the result as a suspected incident."
    )

    @field_validator("recipient", "sender")
    @classmethod
    def check_email(cls, value: str | None) -> str | None:
        return None if value is None else normalize_email(value)

    @field_validator("subject")
    @classmethod
    def check_subject(cls, value: str | None) -> str | None:
        return _clean_text(value, "subject", 998)

    @field_validator("nickname", "surname_variant")
    @classmethod
    def check_name_clue(cls, value: str | None, info) -> str | None:
        return _clean_text(value, info.field_name, 100)

    @model_validator(mode="after")
    def require_a_clue(self) -> "MatchCheckRequest":
        if not any((self.recipient, self.sender, self.nickname, self.surname_variant)):
            raise ValueError(
                "provide at least one of recipient, sender, nickname or surname_variant"
            )
        return self


class MatchSignal(BaseModel):
    type: str
    explanation: str


class MatchCandidate(BaseModel):
    signup_id: int
    site_name: str
    site_domain: str | None
    confidence: str
    signals: list[MatchSignal]


class MatchCheckResponse(BaseModel):
    status: str = Field(description='"matched", "ambiguous" or "no_match". Never a confirmed leak.')
    confidence: str = Field(description='"high", "medium", "low" or "none".')
    matches: list[MatchCandidate]
    warnings: list[str]
    limitations: list[str]
    incident_id: int | None = Field(
        description="Set only when record_incident was true and the incident was saved."
    )
