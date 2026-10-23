"""Application configuration loaded from environment variables.

A local .env file is loaded if present but is not required: every setting
has a safe default, except DATABASE_URL, which is only needed by code that
talks to the database.
"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

# Load a local .env file if present. Real environment variables take precedence.
load_dotenv()

APP_NAME = "LeakTrace"
APP_VERSION = "0.1.0"
APP_DESCRIPTION = (
    "Privacy-focused data-leak investigation platform. LeakTrace helps users "
    "identify likely sources of personal-data leaks by assigning distinct "
    "identity variants to different websites."
)


@dataclass(frozen=True)
class Settings:
    environment: str
    log_level: str
    # Expected format: postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE
    database_url: str | None = field(repr=False)
    db_pool_size: int
    db_max_overflow: int
    db_pool_recycle_seconds: int
    # Domain for generated signup aliases (e.g. aliases.example.com). Generating
    # an alias does not configure mail routing or verify delivery.
    alias_domain: str | None
    alias_prefix: str
    alias_suffix_length: int
    marker_max_retries: int
    # Shared secret the email Worker sends as a Bearer token. Ingestion is
    # disabled while it is unset.
    ingest_secret: str | None = field(repr=False)
    ingest_max_bytes: int
    # The dashboard has no authentication. It is served only to requests from
    # this machine, and only when enabled (default: in development).
    dashboard_enabled: bool
    # Accounts and sessions.
    session_idle_hours: int
    session_max_days: int
    extension_token_hours: int
    # Secure cookies need HTTPS; off by default only in development (http://127.0.0.1).
    cookie_secure: bool
    # Unverified accounts may sign in only where this is on (default: development).
    allow_unverified_login: bool
    # Key for hashing rate-limit identifiers (IPs, emails). Required outside
    # development; a random per-process key is used when unset.
    secret_key: str | None = field(repr=False)
    # Name of a configured email delivery provider. None: no emails are sent.
    email_delivery: str | None


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def get_settings() -> Settings:
    """Read settings from the environment, falling back to defaults."""
    environment = os.getenv("LEAKTRACE_ENV", "development")
    return Settings(
        environment=environment,
        log_level=os.getenv("LEAKTRACE_LOG_LEVEL", "INFO").upper(),
        database_url=os.getenv("DATABASE_URL") or None,
        db_pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        db_max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
        db_pool_recycle_seconds=int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800")),
        alias_domain=os.getenv("LEAKTRACE_ALIAS_DOMAIN") or None,
        alias_prefix=os.getenv("LEAKTRACE_ALIAS_PREFIX", ""),
        alias_suffix_length=int(os.getenv("LEAKTRACE_ALIAS_SUFFIX_LENGTH", "8")),
        marker_max_retries=int(os.getenv("LEAKTRACE_MARKER_MAX_RETRIES", "5")),
        ingest_secret=os.getenv("LEAKTRACE_INGEST_SECRET") or None,
        ingest_max_bytes=int(os.getenv("LEAKTRACE_INGEST_MAX_BYTES", "16384")),
        dashboard_enabled=_flag("LEAKTRACE_DASHBOARD_ENABLED", environment == "development"),
        session_idle_hours=int(os.getenv("LEAKTRACE_SESSION_IDLE_HOURS", "12")),
        session_max_days=int(os.getenv("LEAKTRACE_SESSION_MAX_DAYS", "7")),
        extension_token_hours=int(os.getenv("LEAKTRACE_EXTENSION_TOKEN_HOURS", "8")),
        cookie_secure=_flag("LEAKTRACE_COOKIE_SECURE", environment != "development"),
        allow_unverified_login=_flag("LEAKTRACE_ALLOW_UNVERIFIED_LOGIN", environment == "development"),
        secret_key=os.getenv("LEAKTRACE_SECRET_KEY") or None,
        email_delivery=os.getenv("LEAKTRACE_EMAIL_DELIVERY") or None,
    )


def mask_database_url(url: str | None) -> str:
    """Return a database URL that is safe to log (password hidden)."""
    if not url:
        return "<not configured>"
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return "<invalid DATABASE_URL>"


settings = get_settings()
