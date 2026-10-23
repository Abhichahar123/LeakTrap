"""Read-only queries for the personal dashboard.

Every query is limited to the authenticated user's own records (owned_by);
records without an owner are never returned. List queries use grouped
subqueries for counts, so the number of queries does not grow with rows.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.models import ConsentReceipt, Incident, MailLog, Signup
from backend.services.ownership import owned_by

MATCH_STATUSES = ("matched", "ambiguous", "no_match")
SIGNUP_FILTERS = ("all", "with_receipts", "with_emails", "real_name")


# ---------- overview ----------

@dataclass(frozen=True)
class Overview:
    websites: int
    aliases: int
    nicknames: int
    receipts: int
    emails_total: int
    matched: int
    ambiguous: int
    no_match: int
    unprocessed: int
    investigations: int


def overview(session: Session, user_id: int) -> Overview:
    s = session.execute(
        select(func.count(), func.count(Signup.alias), func.count(Signup.nickname))
        .where(owned_by(Signup.user_id, user_id))
    ).one()
    receipts = session.scalar(select(func.count()).select_from(ConsentReceipt).where(owned_by(ConsentReceipt.user_id, user_id)))
    investigations = session.scalar(select(func.count()).select_from(Incident).where(owned_by(Incident.user_id, user_id)))
    rows = session.execute(
        select(MailLog.match_status, func.count()).where(owned_by(MailLog.user_id, user_id)).group_by(MailLog.match_status)
    ).all()
    counts = {status: count for status, count in rows}
    known = {status: counts.get(status, 0) for status in MATCH_STATUSES}
    unprocessed = sum(c for status, c in counts.items() if status not in MATCH_STATUSES)
    return Overview(
        websites=s[0], aliases=s[1], nicknames=s[2], receipts=receipts or 0, emails_total=sum(counts.values()),
        **known, unprocessed=unprocessed, investigations=investigations or 0,
    )


# ---------- My Websites ----------

@dataclass(frozen=True)
class SignupRow:
    id: int
    site_name: str
    site_domain: str | None
    alias: str | None
    nickname: str | None
    real_name_required: bool
    receipt_count: int
    email_count: int
    created_at: datetime


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _counts_subqueries(user_id: int):
    receipts = (
        select(ConsentReceipt.signup_id, func.count().label("n"))
        .where(owned_by(ConsentReceipt.user_id, user_id), ConsentReceipt.signup_id.is_not(None))
        .group_by(ConsentReceipt.signup_id).subquery()
    )
    emails = (
        select(MailLog.signup_id, func.count().label("n"))
        .where(owned_by(MailLog.user_id, user_id), MailLog.signup_id.is_not(None))
        .group_by(MailLog.signup_id).subquery()
    )
    return receipts, emails


def list_signups(
    session: Session, user_id: int, limit: int, offset: int, q: str | None = None, filter_: str = "all"
) -> tuple[list[SignupRow], int]:
    receipts, emails = _counts_subqueries(user_id)
    receipt_n = func.coalesce(receipts.c.n, 0)
    email_n = func.coalesce(emails.c.n, 0)
    query = (
        select(Signup, receipt_n, email_n)
        .outerjoin(receipts, receipts.c.signup_id == Signup.id)
        .outerjoin(emails, emails.c.signup_id == Signup.id)
        .where(owned_by(Signup.user_id, user_id))
    )
    if q:
        pattern = f"%{_escape_like(q.strip().lower())}%"
        query = query.where(or_(*(func.lower(col).like(pattern, escape="\\") for col in
                                  (Signup.site_name, Signup.site_domain, Signup.alias, Signup.nickname))))
    if filter_ == "with_receipts":
        query = query.where(receipt_n > 0)
    elif filter_ == "with_emails":
        query = query.where(email_n > 0)
    elif filter_ == "real_name":
        query = query.where(Signup.real_name_required.is_(True))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.execute(
        query.order_by(Signup.created_at.desc(), Signup.id.desc()).limit(limit).offset(offset)
    ).all()
    items = [
        SignupRow(id=s.id, site_name=s.site_name, site_domain=s.site_domain, alias=s.alias, nickname=s.nickname,
                  real_name_required=s.real_name_required, receipt_count=r, email_count=e, created_at=s.created_at)
        for s, r, e in rows
    ]
    return items, total or 0


@dataclass(frozen=True)
class SignupDetail:
    signup: Signup
    receipts: list[ConsentReceipt]
    emails: list["EmailRow"]


def get_signup_detail(session: Session, user_id: int, signup_id: int, recent: int = 20) -> SignupDetail | None:
    signup = session.scalar(select(Signup).where(Signup.id == signup_id, owned_by(Signup.user_id, user_id)))
    if signup is None:
        return None
    receipts = session.scalars(
        select(ConsentReceipt)
        .where(owned_by(ConsentReceipt.user_id, user_id), ConsentReceipt.signup_id == signup.id)
        .order_by(ConsentReceipt.created_at.desc(), ConsentReceipt.id.desc()).limit(recent)
    ).all()
    emails = session.execute(
        _email_query(user_id).where(MailLog.signup_id == signup.id)
        .order_by(MailLog.received_at.desc(), MailLog.id.desc()).limit(recent)
    ).all()
    return SignupDetail(signup, list(receipts), [_email_row(*row) for row in emails])


# ---------- email activity ----------

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


def _email_query(user_id: int):
    return (
        select(MailLog, Signup.site_name, Signup.site_domain)
        .outerjoin(Signup, MailLog.signup_id == Signup.id)
        .where(owned_by(MailLog.user_id, user_id))
    )


def _email_row(log: MailLog, site_name: str | None, site_domain: str | None) -> EmailRow:
    return EmailRow(
        id=log.id, received_at=log.received_at, created_at=log.created_at,
        match_status=log.match_status, match_confidence=log.match_confidence,
        recipient_known=log.signup_id is not None, signup_id=log.signup_id,
        site_name=site_name, site_domain=site_domain, sender_domain=log.sender_domain,
    )


def list_emails(
    session: Session, user_id: int, limit: int, offset: int, status: str | None = None
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


def get_email(session: Session, user_id: int, mail_log_id: int) -> EmailRow | None:
    row = session.execute(_email_query(user_id).where(MailLog.id == mail_log_id)).first()
    return _email_row(*row) if row else None


# ---------- leak investigations (matcher incidents the user chose to record) ----------

@dataclass(frozen=True)
class InvestigationRow:
    id: int
    created_at: datetime
    channel: str
    result: str | None
    confidence: str | None
    matched_site: str | None
    recipient_alias_matched: bool
    sender_domain: str | None
    candidate_count: int
    signal_types: list[str]


def _summary(evidence: dict[str, Any] | None) -> tuple[bool, str | None, int, list[str]]:
    evidence = evidence if isinstance(evidence, dict) else {}
    candidates = evidence.get("candidates") if isinstance(evidence.get("candidates"), list) else []
    signals = sorted({s for c in candidates if isinstance(c, dict) for s in (c.get("signals") or []) if isinstance(s, str)})
    sender = evidence.get("sender_domain")
    return (evidence.get("recipient_alias_matched") is True, sender if isinstance(sender, str) else None,
            len(candidates), signals)


def list_investigations(session: Session, user_id: int, limit: int, offset: int) -> tuple[list[InvestigationRow], int]:
    query = select(Incident).where(owned_by(Incident.user_id, user_id))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.scalars(query.order_by(Incident.created_at.desc(), Incident.id.desc()).limit(limit).offset(offset)).all()
    items = []
    for i in rows:
        alias_matched, sender, n, signals = _summary(i.evidence)
        items.append(InvestigationRow(
            id=i.id, created_at=i.created_at, channel=i.channel, result=i.result, confidence=i.confidence,
            matched_site=i.matched_site, recipient_alias_matched=alias_matched, sender_domain=sender,
            candidate_count=n, signal_types=signals,
        ))
    return items, total or 0
