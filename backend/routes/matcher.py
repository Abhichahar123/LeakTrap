"""Leak matcher endpoint. Searches only the signed-in user's own signups."""

from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas.matcher import MatchCheckRequest, MatchCheckResponse
from backend.security import require_user
from backend.services import matcher
from backend.services.auth import AuthContext

router = APIRouter(prefix="/matcher", tags=["matcher"])


@router.post(
    "/check",
    response_model=MatchCheckResponse,
    responses={401: {"description": "Sign in required"}, 422: {"description": "Invalid clues"},
               503: {"description": "Database unavailable"}},
)
def check(
    payload: MatchCheckRequest, auth: AuthContext = Depends(require_user), db: Session = Depends(get_db)
) -> MatchCheckResponse:
    """Compare clues from a suspicious email with your signups.

    A match links the message to a signup; it is never proof of a leak.
    Nothing is saved unless record_incident is true.
    """
    clues = matcher.Clues(
        recipient=payload.recipient,
        sender=payload.sender,
        subject=payload.subject,
        nickname=payload.nickname.lower() if payload.nickname else None,
        surname_variant=payload.surname_variant.lower() if payload.surname_variant else None,
        user_id=auth.user_id,
    )
    result = matcher.check(db, clues)
    if payload.record_incident:
        result.incident_id = matcher.record_incident(db, clues, result).id
    return MatchCheckResponse.model_validate(asdict(result))
