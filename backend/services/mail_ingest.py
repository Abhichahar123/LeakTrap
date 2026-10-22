"""Email ingestion: turn one inbound message into a MailLog row and a matcher result.

Trust boundaries:
- recipient and envelope_from come from the email Worker, i.e. from Cloudflare's
  SMTP session. The envelope sender is still whatever the sending server
  claimed and can be forged.
- from_header and subject are message content, fully untrusted. They are parsed
  leniently: anything unparseable is ignored rather than trusted.

Only the alias, the claimed sender's domain and the match outcome are stored.
Full sender addresses, subjects and bodies are not.
"""

import hashlib
import logging
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import MailLog, Signup
from backend.services import matcher
from backend.services.domains import normalize_email

logger = logging.getLogger("leaktrace.ingest")

DEDUP_CONSTRAINT = "uq_mail_log_message_id_hash"
MAX_SUBJECT_LENGTH = 998


@dataclass(frozen=True)
class InboundMail:
    recipient: str
    envelope_from: str | None
    claimed_sender: str | None
    subject: str | None
    message_id: str | None
    received_at: datetime

    @property
    def sender_for_matching(self) -> str | None:
        """The From header address when present (what the recipient sees),
        otherwise the envelope sender."""
        return self.claimed_sender or self.envelope_from


@dataclass(frozen=True)
class IngestOutcome:
    mail_log_id: int
    duplicate: bool
    recipient_known: bool
    match_status: str
    match_confidence: str


def parse_from_header(value: str | None) -> str | None:
    """First valid address in an untrusted From header, or None."""
    if not value:
        return None
    for _, address in getaddresses([value]):
        try:
            return normalize_email(address)
        except ValueError:
            continue
    return None


def decode_subject(value: str | None) -> str | None:
    """Decode MIME encoded-words, drop control characters, collapse whitespace."""
    if not value:
        return None
    try:
        value = str(make_header(decode_header(value)))
    except Exception:  # malformed encoding: fall back to the raw text
        pass
    value = "".join(" " if unicodedata.category(ch).startswith("C") else ch for ch in value)
    value = " ".join(value.split())[:MAX_SUBJECT_LENGTH]
    return value or None


def dedup_hash(mail: InboundMail) -> str:
    """Stable key for one message.

    Uses the provider Message-ID when present. Without one, it falls back to
    the message's key fields, so two genuinely different messages with
    identical fields would be treated as one.
    """
    if mail.message_id:
        basis = "message-id\n" + mail.message_id
    else:
        parts = (mail.recipient, mail.envelope_from, mail.claimed_sender, mail.subject)
        basis = "fields\n" + "\n".join(p or "" for p in parts)
    return hashlib.sha256(basis.encode()).hexdigest()


def _duplicate(log: MailLog) -> IngestOutcome:
    return IngestOutcome(
        log.id, True, log.signup_id is not None, log.match_status or "no_match",
        log.match_confidence or "none",
    )


def _existing(session: Session, key: str) -> MailLog | None:
    return session.scalar(select(MailLog).where(MailLog.message_id_hash == key))


def process(session: Session, mail: InboundMail) -> IngestOutcome:
    """Match and record one message. Safe to call again for a retried delivery.

    The recipient alias decides whose signups are searched: the matcher runs
    in that signup owner's scope only. If the alias is unknown, no search is
    made at all, rather than searching more broadly.
    """
    key = dedup_hash(mail)
    if existing := _existing(session, key):
        return _duplicate(existing)

    signup = session.scalar(select(Signup).where(func.lower(Signup.alias) == mail.recipient))
    sender = mail.sender_for_matching
    status, confidence = "no_match", "none"
    if signup is not None:
        result = matcher.check(session, matcher.Clues(
            recipient=mail.recipient, sender=sender, subject=mail.subject, user_id=signup.user_id,
        ))
        status, confidence = result.status, result.confidence

    log = MailLog(
        user_id=signup.user_id if signup else None,
        signup_id=signup.id if signup else None,
        alias=mail.recipient,
        received_at=mail.received_at,
        message_id_hash=key,
        sender_domain=sender.split("@", 1)[1] if sender else None,
        match_status=status,
        match_confidence=confidence,
    )
    try:
        session.add(log)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint != DEDUP_CONSTRAINT:
            raise
        # A concurrent delivery of the same message committed first.
        existing = _existing(session, key)
        if existing is None:
            raise
        return _duplicate(existing)
    except Exception:
        session.rollback()
        raise
    return IngestOutcome(log.id, False, signup is not None, status, confidence)


def now() -> datetime:
    return datetime.now(timezone.utc)
