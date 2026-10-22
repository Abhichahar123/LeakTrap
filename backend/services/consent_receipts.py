"""Create and read consent receipts within one ownership scope.

A receipt's owner is always taken from its signup, never from the client.
The scope (a user_id, or "no user") is a filter, not authentication.
"""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import ConsentReceipt, Signup
from backend.models.consent_receipt import NOTICE_TEXT_NOT_STORED
from backend.schemas.consent_receipt import (
    ConsentReceiptCreate,
    ConsentReceiptDetail,
    ConsentReceiptSummary,
)


class NotInScopeError(Exception):
    """The signup or receipt does not exist in the requested scope."""


def _owner(column, user_id: int | None):
    return column.is_(None) if user_id is None else column == user_id


def _signup_in_scope(session: Session, signup_id: int, user_id: int | None) -> Signup:
    signup = session.get(Signup, signup_id)
    # Same error whether it is missing or someone else's: do not reveal which.
    if signup is None or signup.user_id != user_id:
        raise NotInScopeError
    return signup


def _summary_fields(receipt: ConsentReceipt, site_name: str | None, site_domain: str | None) -> dict:
    notice_stored = bool(receipt.privacy_notice_text) and receipt.privacy_notice_text != NOTICE_TEXT_NOT_STORED
    return dict(
        id=receipt.id, signup_id=receipt.signup_id, site_name=site_name, site_domain=site_domain,
        action=receipt.action, capture_source=receipt.capture_source,
        evidence_basis="user_reported" if receipt.capture_source == "manual" else "unknown",
        recorded_at=receipt.created_at, reported_occurred_at=receipt.reported_occurred_at,
        source_url=receipt.source_url, notice_version=receipt.notice_version,
        content_hash=receipt.content_hash, notice_text_stored=notice_stored,
        consent_text_stored=receipt.consent_text is not None,
    )


def _detail(receipt: ConsentReceipt, site_name: str | None, site_domain: str | None) -> ConsentReceiptDetail:
    fields = _summary_fields(receipt, site_name, site_domain)
    return ConsentReceiptDetail(
        **fields,
        notice_text=receipt.privacy_notice_text if fields["notice_text_stored"] else None,
        consent_text=receipt.consent_text,
    )


def create(session: Session, user_id: int | None, data: ConsentReceiptCreate) -> ConsentReceiptDetail:
    signup = _signup_in_scope(session, data.signup_id, user_id)
    receipt = ConsentReceipt(
        user_id=signup.user_id,
        signup_id=signup.id,
        action=data.action,
        capture_source="manual",
        source_url=data.source_url,
        notice_version=data.notice_version,
        content_hash=data.content_hash,
        privacy_notice_text=data.notice_text if data.notice_text is not None else NOTICE_TEXT_NOT_STORED,
        consent_text=data.consent_text,
        reported_occurred_at=data.reported_occurred_at,
    )
    try:
        session.add(receipt)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _detail(receipt, signup.site_name, signup.site_domain)


def _query(user_id: int | None):
    return (
        select(ConsentReceipt, Signup.site_name, Signup.site_domain)
        .outerjoin(Signup, ConsentReceipt.signup_id == Signup.id)
        .where(_owner(ConsentReceipt.user_id, user_id))
    )


def list_receipts(
    session: Session, user_id: int | None, limit: int, offset: int, signup_id: int | None = None
) -> tuple[list[ConsentReceiptSummary], int]:
    query = _query(user_id)
    if signup_id is not None:
        _signup_in_scope(session, signup_id, user_id)
        query = query.where(ConsentReceipt.signup_id == signup_id)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows: Sequence = session.execute(
        query.order_by(ConsentReceipt.created_at.desc(), ConsentReceipt.id.desc())
        .limit(limit).offset(offset)
    ).all()
    return [ConsentReceiptSummary(**_summary_fields(*row)) for row in rows], total or 0


def get(session: Session, user_id: int | None, receipt_id: int) -> ConsentReceiptDetail:
    row = session.execute(_query(user_id).where(ConsentReceipt.id == receipt_id)).first()
    if row is None:
        raise NotInScopeError
    return _detail(*row)
