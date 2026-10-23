"""Connecting a browser extension to an account.

1. The extension creates a random secret and starts a pairing with only the
   secret's SHA-256 hash. It receives a short code (shown to the user) and a
   pairing id.
2. The signed-in user approves that code in the dashboard.
3. The extension exchanges the pairing id plus the secret for a scoped,
   short-lived token. Knowing the code alone is not enough.

Codes and tokens are stored only as hashes; each pairing is single-use.
"""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import ExtensionPairing, User, UserSession
from backend.security import EXTENSION_SCOPES
from backend.services import auth as auth_service
from backend.services.auth import RateLimited, check_rate, now, record_event, token_hash

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
CODE_LENGTH = 8
PAIRING_MINUTES = 10
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class PairingNotFound(Exception):
    pass


class PairingExpired(Exception):
    pass


class PairingPending(Exception):
    pass


def normalize_code(code: str) -> str:
    return re.sub(r"[\s-]", "", str(code)).upper()


def format_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


@dataclass(frozen=True)
class StartedPairing:
    pairing_id: int
    code: str
    expires_at: datetime


def start(session: Session, secret_hash: str, ip: str) -> StartedPairing:
    if not _HEX64.match(secret_hash or ""):
        raise ValueError("secret_hash must be 64 lowercase hex characters")
    check_rate(session, "pairing_start_ip", ip)
    record_event(session, "pairing_start_ip", ip)
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    row = ExtensionPairing(code_hash=token_hash(code), secret_hash=secret_hash,
                           expires_at=now() + timedelta(minutes=PAIRING_MINUTES))
    session.add(row)
    session.commit()
    return StartedPairing(row.id, format_code(code), row.expires_at)


def approve(session: Session, user_id: int, code: str) -> ExtensionPairing:
    check_rate(session, "pairing_approve_failed_user", str(user_id))
    row = session.scalar(select(ExtensionPairing).where(ExtensionPairing.code_hash == token_hash(normalize_code(code))))
    if row is None or row.expires_at <= now() or row.approved_at is not None or row.consumed_at is not None:
        record_event(session, "pairing_approve_failed_user", str(user_id))
        session.commit()
        raise PairingNotFound
    row.user_id = user_id
    row.approved_at = now()
    session.commit()
    return row


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_at: datetime
    email: str
    scopes: tuple[str, ...]


def exchange(session: Session, pairing_id: int, secret: str, ip: str) -> IssuedToken:
    check_rate(session, "pairing_exchange_ip", ip)
    record_event(session, "pairing_exchange_ip", ip)
    session.commit()
    row = session.get(ExtensionPairing, pairing_id)
    given = hashlib.sha256(str(secret).encode()).hexdigest()
    if row is None or not hmac.compare_digest(given, row.secret_hash):
        raise PairingNotFound
    if row.consumed_at is not None or row.expires_at <= now():
        raise PairingExpired
    if row.approved_at is None or row.user_id is None:
        raise PairingPending
    created = auth_service.create_session(
        session, row.user_id, "extension", " ".join(sorted(EXTENSION_SCOPES)), label="Browser extension",
        lifetime=timedelta(hours=settings.extension_token_hours),
    )
    row.consumed_at = now()
    email = session.get(User, row.user_id).email
    session.commit()
    return IssuedToken(created.token, created.expires_at, email, tuple(sorted(EXTENSION_SCOPES)))


def active_extension_sessions(session: Session, user_id: int) -> list[UserSession]:
    return list(session.scalars(
        select(UserSession)
        .where(UserSession.user_id == user_id, UserSession.kind == "extension",
               UserSession.revoked_at.is_(None), UserSession.expires_at > now())
        .order_by(UserSession.created_at.desc())
    ).all())


def revoke_extension_session(session: Session, user_id: int, session_id: int) -> bool:
    row = session.get(UserSession, session_id)
    if row is None or row.user_id != user_id or row.kind != "extension":
        return False
    return auth_service.revoke_session(session, session_id, user_id)


__all__ = ["RateLimited", "PairingNotFound", "PairingExpired", "PairingPending"]
