"""Per-site alias recall for the browser extension's autofill.

Returns only the authenticated user's own signups (dashboard session or an
extension token with the signups:lookup scope). As an extra layer, like the
dashboard, only requests from this machine are answered. POST keeps the
hostname out of URLs and access logs.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.routes.dashboard import require_local_dashboard
from backend.security import require_scope
from backend.services.auth import AuthContext
from backend.schemas.autofill import AutofillLookupRequest, AutofillLookupResponse, AutofillSignup
from backend.services import signup_service

router = APIRouter(prefix="/autofill", tags=["autofill"], dependencies=[Depends(require_local_dashboard)])


@router.post("/lookup", response_model=AutofillLookupResponse)
def lookup(
    payload: AutofillLookupRequest,
    auth: AuthContext = Depends(require_scope("signups:lookup")),
    db: Session = Depends(get_db),
) -> AutofillLookupResponse:
    """Saved signups for exactly this domain. Never creates anything."""
    items = signup_service.find_by_exact_domain(db, auth.user_id, payload.site_domain)
    return AutofillLookupResponse(
        site_domain=payload.site_domain, items=[AutofillSignup.model_validate(s) for s in items]
    )
