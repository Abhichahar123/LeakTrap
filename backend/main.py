"""LeakTrace API entry point.

Run from the project root with:
    uvicorn backend.main:app --reload
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError

from backend.config import (
    APP_DESCRIPTION,
    APP_NAME,
    APP_VERSION,
    mask_database_url,
    settings,
)
from backend.database import DatabaseNotConfiguredError
from backend.routes import auth, autofill, consent_receipts, dashboard, extension, health, ingest, matcher, signups

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("leaktrace")


class RootResponse(BaseModel):
    application: str
    status: str
    version: str


app = FastAPI(
    title=f"{APP_NAME} API",
    description=APP_DESCRIPTION,
    version=APP_VERSION,
)

# Register routers here. Future phases add their routers alongside this one.
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(auth.account_router)
app.include_router(extension.router)
app.include_router(signups.router)
app.include_router(matcher.router)
app.include_router(ingest.router)
app.include_router(dashboard.router)
app.include_router(consent_receipts.router)
app.include_router(autofill.router)


@app.exception_handler(DatabaseNotConfiguredError)
def database_not_configured(request: Request, exc: DatabaseNotConfiguredError) -> JSONResponse:
    logger.error("Database not configured: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "Database is not configured."})


@app.exception_handler(OperationalError)
def database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
    # Log only the error type: messages can include host names or SQL.
    logger.error("Database unavailable: %s", type(exc.orig).__name__)
    return JSONResponse(status_code=503, content={"detail": "Database is unavailable."})


@app.get("/", response_model=RootResponse, tags=["root"])
def root() -> RootResponse:
    return RootResponse(application=APP_NAME, status="running", version=APP_VERSION)


logger.info("%s API %s initialised (environment=%s)", APP_NAME, APP_VERSION, settings.environment)
# Log only the masked URL. No connection is opened here; sessions are created
# on demand through backend.database.get_db.
logger.info("Database: %s", mask_database_url(settings.database_url))
