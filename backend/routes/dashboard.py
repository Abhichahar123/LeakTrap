"""Local-development dashboard: a static page plus read-only JSON endpoints.

There is no authentication. Every route here only answers requests from this
machine (loopback addresses) and only when LEAKTRACE_DASHBOARD_ENABLED is on.
A reverse proxy running on the same machine would defeat the loopback check,
so do not put this behind one or expose it publicly.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models import User
from backend.schemas.dashboard import (
    DashboardEmail,
    DashboardEmailDetail,
    DashboardEmailPage,
    DashboardSignup,
    DashboardSignupPage,
    OverviewResponse,
    ScopeInfo,
)
from backend.schemas.signup import MAX_BIGINT
from backend.services import dashboard, matcher

STATIC_DIR = Path(__file__).resolve().parent.parent / "dashboard"
STATIC_FILES = {"app.js": "text/javascript", "styles.css": "text/css"}
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
MAX_PAGE_SIZE = 100

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


@dataclass(frozen=True)
class DashboardConfig:
    enabled: bool


def get_dashboard_config() -> DashboardConfig:
    return DashboardConfig(enabled=settings.dashboard_enabled)


def require_local_dashboard(
    request: Request, config: DashboardConfig = Depends(get_dashboard_config)
) -> None:
    if not config.enabled:
        raise HTTPException(404, "Not Found")
    host = request.client.host if request.client else None
    if host not in LOOPBACK_HOSTS:
        raise HTTPException(403, "The dashboard is only available from this machine.")


router = APIRouter(
    prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_local_dashboard)]
)


def resolve_scope(
    user_id: int | None = Query(
        None, gt=0, le=MAX_BIGINT,
        description="Show this user's records. Omit for records without a user. Not authenticated.",
    ),
    db: Session = Depends(get_db),
) -> int | None:
    if user_id is not None and db.get(User, user_id) is None:
        raise HTTPException(422, "user_id does not refer to an existing user")
    return user_id


Limit = Query(20, ge=1, le=MAX_PAGE_SIZE)
Offset = Query(0, ge=0, le=MAX_BIGINT)


@router.get("", include_in_schema=False)
def page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html", headers=SECURITY_HEADERS)


@router.get("/static/{name}", include_in_schema=False)
def static_file(name: str) -> FileResponse:
    if name not in STATIC_FILES:
        raise HTTPException(404, "Not Found")
    return FileResponse(STATIC_DIR / name, media_type=STATIC_FILES[name], headers=SECURITY_HEADERS)


@router.get("/api/overview", response_model=OverviewResponse)
def get_overview(
    user_id: int | None = Depends(resolve_scope), db: Session = Depends(get_db)
) -> OverviewResponse:
    counts = dashboard.overview(db, user_id)
    return OverviewResponse(scope=ScopeInfo(user_id=user_id), **vars(counts))


@router.get("/api/signups", response_model=DashboardSignupPage)
def get_signups(
    limit: int = Limit,
    offset: int = Offset,
    user_id: int | None = Depends(resolve_scope),
    db: Session = Depends(get_db),
) -> DashboardSignupPage:
    items, total = dashboard.list_signups(db, user_id, limit, offset)
    return DashboardSignupPage(
        scope=ScopeInfo(user_id=user_id),
        items=[DashboardSignup.model_validate(i) for i in items],
        total=total, limit=limit, offset=offset,
    )


@router.get("/api/emails", response_model=DashboardEmailPage)
def get_emails(
    limit: int = Limit,
    offset: int = Offset,
    status: Literal["matched", "ambiguous", "no_match", "unprocessed"] | None = None,
    user_id: int | None = Depends(resolve_scope),
    db: Session = Depends(get_db),
) -> DashboardEmailPage:
    items, total = dashboard.list_emails(db, user_id, limit, offset, status)
    return DashboardEmailPage(
        scope=ScopeInfo(user_id=user_id),
        items=[DashboardEmail.model_validate(i) for i in items],
        total=total, limit=limit, offset=offset,
    )


@router.get("/api/emails/{mail_log_id}", response_model=DashboardEmailDetail, responses={404: {}})
def get_email(
    mail_log_id: int = PathParam(gt=0, le=MAX_BIGINT),
    user_id: int | None = Depends(resolve_scope),
    db: Session = Depends(get_db),
) -> DashboardEmailDetail:
    row = dashboard.get_email(db, user_id, mail_log_id)
    if row is None:
        raise HTTPException(404, "Email record not found in this scope")
    return DashboardEmailDetail(**vars(row), limitations=list(matcher.LIMITATIONS))
