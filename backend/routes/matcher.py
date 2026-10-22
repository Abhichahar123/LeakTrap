"""Leak matcher endpoint.

There is no authentication yet: user_id selects which signups are searched but
is not verified. This endpoint is for single-user local development only.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User
from backend.schemas.matcher import MatchCheckRequest, MatchCheckResponse
from backend.services import matcher

router = APIRouter(prefix="/matcher", tags=["matcher"])


@router.post(
    "/check",
    response_model=MatchCheckResponse,
    responses={422: {"description": "Invalid clues or unknown user_id"},
               503: {"description": "Database unavailable"}},
)
def check(payload: MatchCheckRequest, db: Session = Depends(get_db)) -> MatchCheckResponse:
    """Compare clues from a suspicious email with your signups.

    A match links the message to a signup; it is never proof of a leak.
    Nothing is saved unless record_incident is true.
    """
    if payload.user_id is not None and db.get(User, payload.user_id) is None:
        raise HTTPException(422, "user_id does not refer to an existing user")

    clues = matcher.Clues(
        recipient=payload.recipient,
        sender=payload.sender,
        subject=payload.subject,
        nickname=payload.nickname.lower() if payload.nickname else None,
        surname_variant=payload.surname_variant.lower() if payload.surname_variant else None,
        user_id=payload.user_id,
    )
    result = matcher.check(db, clues)
    if payload.record_incident:
        result.incident_id = matcher.record_incident(db, clues, result).id
    return MatchCheckResponse.model_validate(asdict(result))
