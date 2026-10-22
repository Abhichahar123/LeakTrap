"""Per-site alias recall for the browser extension's autofill.

Local development only, like the dashboard: only requests from this machine
are answered. Results are limited to one ownership scope (the extension sends
no user_id, so: signups without a user). The scope is a filter, not
authentication. POST keeps the hostname out of URLs and access logs.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.routes.dashboard import require_local_dashboard, resolve_scope
from backend.schemas.autofill import AutofillLookupRequest, AutofillLookupResponse, AutofillSignup
from backend.services import signup_service

router = APIRouter(prefix="/autofill", tags=["autofill"], dependencies=[Depends(require_local_dashboard)])


@router.post("/lookup", response_model=AutofillLookupResponse)
def lookup(
    payload: AutofillLookupRequest,
    user_id: int | None = Depends(resolve_scope),
    db: Session = Depends(get_db),
) -> AutofillLookupResponse:
    """Saved signups for exactly this domain. Never creates anything."""
    items = signup_service.find_by_exact_domain(db, user_id, payload.site_domain)
    return AutofillLookupResponse(
        site_domain=payload.site_domain, items=[AutofillSignup.model_validate(s) for s in items]
    )
