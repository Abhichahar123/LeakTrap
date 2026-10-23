"""Consent receipt endpoints for the signed-in user's own signups.

Recording a receipt is allowed from the dashboard (web session) or a connected
extension (receipts:create scope); reading needs the dashboard. As an extra
layer, like the dashboard, these routes answer only requests from this machine.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.routes.common import read_limited_body, require_json, validation_error
from backend.routes.dashboard import MAX_PAGE_SIZE, require_local_dashboard
from backend.schemas.consent_receipt import (
    ConsentReceiptCreate,
    ConsentReceiptDetail,
    ConsentReceiptPage,
)
from backend.schemas.signup import MAX_BIGINT
from backend.services import consent_receipts
from backend.security import require_scope, require_user
from backend.services.auth import AuthContext
from backend.services.consent_receipts import NotInScopeError

MAX_BODY_BYTES = 128 * 1024

router = APIRouter(
    prefix="/consent-receipts", tags=["consent receipts"],
    dependencies=[Depends(require_local_dashboard)],
)


@router.post(
    "",
    status_code=201,
    response_model=ConsentReceiptDetail,
    responses={
        404: {"description": "Signup not found"},
        413: {"description": "Body too large"},
        415: {"description": "Body is not JSON"},
        422: {"description": "Invalid input"},
    },
    openapi_extra={"requestBody": {"required": True, "content": {"application/json": {
        "schema": ConsentReceiptCreate.model_json_schema()}}}},
)
async def create_receipt(
    request: Request,
    auth: AuthContext = Depends(require_scope("receipts:create")),
    db: Session = Depends(get_db),
) -> ConsentReceiptDetail:
    """Record a receipt you are reporting for one of your signups.

    It is stored as user-reported. It is not proof of legally valid consent,
    of compliance, or of a violation. URLs are never fetched.
    """
    require_json(request)
    body = await read_limited_body(request, MAX_BODY_BYTES)
    try:
        payload = ConsentReceiptCreate.model_validate_json(body)
    except ValidationError as exc:
        raise validation_error(exc) from None
    try:
        return await run_in_threadpool(consent_receipts.create, db, auth.user_id, payload)
    except NotInScopeError:
        raise HTTPException(404, "Signup not found") from None


@router.get("", response_model=ConsentReceiptPage, responses={404: {}})
def list_receipts(
    signup_id: int | None = Query(None, gt=0, le=MAX_BIGINT),
    limit: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    auth: AuthContext = Depends(require_user),
    db: Session = Depends(get_db),
) -> ConsentReceiptPage:
    try:
        items, total = consent_receipts.list_receipts(db, auth.user_id, limit, offset, signup_id)
    except NotInScopeError:
        raise HTTPException(404, "Signup not found") from None
    return ConsentReceiptPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{receipt_id}", response_model=ConsentReceiptDetail, responses={404: {}})
def get_receipt(
    receipt_id: int = Path(gt=0, le=MAX_BIGINT),
    auth: AuthContext = Depends(require_user),
    db: Session = Depends(get_db),
) -> ConsentReceiptDetail:
    try:
        return consent_receipts.get(db, auth.user_id, receipt_id)
    except NotInScopeError:
        raise HTTPException(404, "Receipt not found") from None
