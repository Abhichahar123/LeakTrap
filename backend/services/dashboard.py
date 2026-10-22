"""Read-only queries for the local dashboard.

Every query is limited to one ownership scope: the signups and mail of a given
user_id, or, when none is given, records that have no user. Without
authentication this scope is a filter, not access control.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import MailLog, Signup

MATCH_STATUSES = ("matched", "ambiguous", "no_match")


def _owner(column, user_id: int | None):
    return column.is_(None) if user_id is None else column == user_id


def mask_alias(alias: str | None) -> str | None:
    """Hide the local part entirely; only the domain is shown."""
    if not alias or "@" not in alias:
        return None
    return "•••@" + alias.split("@", 1)[1]


@dataclass(frozen=True)
class Overview:
    signups_total: int
    emails_total: int
    matched: int
    ambiguous: int
    no_match: int
    unprocessed: int


def overview(session: Session, user_id: int | None) -> Overview:
    signups_total = session.scalar(
        select(func.count()).select_from(Signup).where(_owner(Signup.user_id, user_id))
    )
    rows = session.execute(
        select(MailLog.match_status, func.count())
        .where(_owner(MailLog.user_id, user_id))
        .group_by(MailLog.match_status)
    ).all()
    counts = {status: count for status, count in rows}
    known = {s: counts.get(s, 0) for s in MATCH_STATUSES}
    # Rows from before ingestion stored a status (or with any other value).
    unprocessed = sum(c for s, c in counts.items() if s not in MATCH_STATUSES)
    return Overview(signups_total or 0, sum(counts.values()), **known, unprocessed=unprocessed)


@dataclass(frozen=True)
class SignupRow:
    id: int
    site_name: str
    site_domain: str | None
    alias_masked: str | None
    has_nickname: bool
    has_surname_variant: bool
    real_name_required: bool
    email_count: int
    created_at: datetime


def list_signups(
    session: Session, user_id: int | None, limit: int, offset: int
) -> tuple[list[SignupRow], int]:
    scope = _owner(Signup.user_id, user_id)
    total = session.scalar(select(func.count()).select_from(Signup).where(scope))
    # One grouped subquery instead of a count query per signup.
    email_counts = (
        select(MailLog.signup_id, func.count().label("n"))
        .where(MailLog.signup_id.is_not(None))
        .group_by(MailLog.signup_id)
        .subquery()
    )
    rows = session.execute(
        select(Signup, func.coalesce(email_counts.c.n, 0))
        .outerjoin(email_counts, email_counts.c.signup_id == Signup.id)
        .where(scope)
        .order_by(Signup.created_at.desc(), Signup.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        SignupRow(
            id=s.id, site_name=s.site_name, site_domain=s.site_domain,
            alias_masked=mask_alias(s.alias), has_nickname=s.nickname is not None,
            has_surname_variant=s.surname_variant is not None,
            real_name_required=s.real_name_required, email_count=n, created_at=s.created_at,
        )
        for s, n in rows
    ]
    return items, total or 0


@dataclass(frozen=True)
class EmailRow:
    id: int
    received_at: datetime
    created_at: datetime
    match_status: str | None
    match_confidence: str | None
    recipient_known: bool
    signup_id: int | None
    site_name: str | None
    site_domain: str | None
    sender_domain: str | None


def _email_query(user_id: int | None):
    return (
        select(MailLog, Signup.site_name, Signup.site_domain)
        .outerjoin(Signup, MailLog.signup_id == Signup.id)
        .where(_owner(MailLog.user_id, user_id))
    )


def _email_row(log: MailLog, site_name: str | None, site_domain: str | None) -> EmailRow:
    return EmailRow(
        id=log.id, received_at=log.received_at, created_at=log.created_at,
        match_status=log.match_status, match_confidence=log.match_confidence,
        recipient_known=log.signup_id is not None, signup_id=log.signup_id,
        site_name=site_name, site_domain=site_domain, sender_domain=log.sender_domain,
    )


def list_emails(
    session: Session, user_id: int | None, limit: int, offset: int, status: str | None = None
) -> tuple[list[EmailRow], int]:
    query = _email_query(user_id)
    if status == "unprocessed":
        query = query.where(MailLog.match_status.is_(None))
    elif status is not None:
        query = query.where(MailLog.match_status == status)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows: Sequence = session.execute(
        query.order_by(MailLog.received_at.desc(), MailLog.id.desc()).limit(limit).offset(offset)
    ).all()
    return [_email_row(*row) for row in rows], total or 0


def get_email(session: Session, user_id: int | None, mail_log_id: int) -> EmailRow | None:
    row = session.execute(_email_query(user_id).where(MailLog.id == mail_log_id)).first()
    return _email_row(*row) if row else None
