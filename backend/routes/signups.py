"""Signup management endpoints.

There is no authentication yet: every caller can see and delete every signup.
These endpoints are for single-user local development only.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models import Signup
from backend.schemas.signup import MAX_BIGINT, SignupCreate, SignupList, SignupRead
from backend.services import signup_service
from backend.services.alias_generator import (
    AliasConfig,
    AliasConfigurationError,
    AliasGenerationError,
)
from backend.services.domains import normalize_domain
from backend.services.nickname_generator import NicknameExhaustedError

router = APIRouter(prefix="/signups", tags=["signups"])

SignupId = Path(gt=0, le=MAX_BIGINT)


def get_alias_config() -> AliasConfig:
    """Alias settings for the request; tests override this dependency."""
    return AliasConfig.from_settings(settings)


@router.post(
    "",
    response_model=SignupRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"description": "No unused nickname is left in this ownership scope"},
        422: {"description": "Invalid input or unknown user_id"},
        503: {"description": "Alias domain not configured, or markers kept colliding"},
    },
)
def create_signup(
    payload: SignupCreate,
    db: Session = Depends(get_db),
    alias_config: AliasConfig = Depends(get_alias_config),
) -> SignupRead:
    data = signup_service.NewSignup(**payload.model_dump())
    try:
        signup = signup_service.create_signup(db, data, alias_config)
    except signup_service.UserNotFoundError:
        raise HTTPException(422, "user_id does not refer to an existing user") from None
    except NicknameExhaustedError as exc:
        raise HTTPException(
            409, f"{exc}. Create the signup with generate_nickname=false instead."
        ) from None
    except AliasConfigurationError as exc:
        raise HTTPException(503, str(exc)) from None
    except (AliasGenerationError, signup_service.MarkerRetriesExhaustedError):
        raise HTTPException(503, "Could not generate unique markers. Please try again.") from None
    return SignupRead.model_validate(signup)


@router.get("", response_model=SignupList)
def list_signups(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    site_domain: str | None = Query(None, description="Exact domain filter, e.g. example.com"),
    db: Session = Depends(get_db),
) -> SignupList:
    if site_domain is not None:
        try:
            site_domain = normalize_domain(site_domain)
        except ValueError as exc:
            raise HTTPException(422, f"site_domain: {exc}") from None
    items, total = signup_service.list_signups(db, limit, offset, site_domain)
    return SignupList(
        items=[SignupRead.model_validate(s) for s in items], total=total, limit=limit, offset=offset
    )


@router.get("/{signup_id}", response_model=SignupRead, responses={404: {}})
def get_signup(signup_id: int = SignupId, db: Session = Depends(get_db)) -> SignupRead:
    signup = db.get(Signup, signup_id)
    if signup is None:
        raise HTTPException(404, "Signup not found")
    return SignupRead.model_validate(signup)


@router.delete(
    "/{signup_id}", status_code=status.HTTP_204_NO_CONTENT, responses={404: {}, 409: {}}
)
def delete_signup(signup_id: int = SignupId, db: Session = Depends(get_db)) -> Response:
    """Delete a signup. Linked consent receipts and mail logs are kept and unlinked."""
    try:
        deleted = signup_service.delete_signup(db, signup_id)
    except signup_service.SignupDeleteRestrictedError:
        raise HTTPException(409, "Signup is still referenced by other records") from None
    if not deleted:
        raise HTTPException(404, "Signup not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
