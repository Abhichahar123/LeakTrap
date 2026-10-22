"""Health check route.

Reports only that the API process is able to respond. It does not check
databases or external services, since none exist yet.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    message: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", message="LeakTrace running")
