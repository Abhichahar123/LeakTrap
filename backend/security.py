"""Request authentication and authorization dependencies.

Web sessions use the HttpOnly `lt_session` cookie; state-changing requests
must also send `X-CSRF-Token` and come from this server's own origin.
Extension tokens use `Authorization: Bearer`, carry explicit scopes, and are
not cookies, so CSRF does not apply to them.

Every private route depends on one of these; the authenticated user id is
the only ownership scope. Clients can never choose another user's scope.
"""

import hmac
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.services.auth import AuthContext, authenticate

SESSION_COOKIE = "lt_session"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

EXTENSION_SCOPES = frozenset({"signups:create", "signups:lookup", "receipts:create"})

UNAUTHENTICATED = HTTPException(401, "Sign in required.", headers={"WWW-Authenticate": "Bearer"})


def bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def get_auth_context(request: Request, db: Session = Depends(get_db)) -> AuthContext | None:
    """The caller's session, or None. A Bearer token takes precedence over the cookie."""
    token = bearer_token(request)
    if token:
        context = authenticate(db, token)
        return context if context and context.kind == "extension" else None
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        context = authenticate(db, cookie)
        return context if context and context.kind == "web" else None
    return None


def _own_origin(request: Request) -> str:
    return f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"


def verify_csrf(request: Request, context: AuthContext) -> None:
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is None:
        referer = request.headers.get("referer")
        if referer:
            parts = urlsplit(referer)
            origin = f"{parts.scheme}://{parts.netloc}"
    if origin != _own_origin(request):
        raise HTTPException(403, "Request blocked: it did not come from this site.")
    sent = request.headers.get(CSRF_HEADER, "")
    if not context.csrf_token or not hmac.compare_digest(sent.encode(), context.csrf_token.encode()):
        raise HTTPException(403, "Request blocked: missing or invalid security token. Reload the page and try again.")


def require_user(request: Request, context: AuthContext | None = Depends(get_auth_context)) -> AuthContext:
    """A signed-in web session (dashboard). CSRF-checked for unsafe methods."""
    if context is None or context.kind != "web":
        raise UNAUTHENTICATED
    verify_csrf(request, context)
    return context


def require_scope(scope: str):
    """A web session, or an extension token that carries `scope`."""
    if scope not in EXTENSION_SCOPES:
        raise ValueError(f"unknown scope {scope}")

    def dependency(request: Request, context: AuthContext | None = Depends(get_auth_context)) -> AuthContext:
        if context is None:
            raise UNAUTHENTICATED
        if context.kind == "web":
            verify_csrf(request, context)
            return context
        if scope not in context.scopes:
            raise HTTPException(403, "This connection is not allowed to do that.")
        return context

    dependency.__name__ = f"require_scope_{scope.replace(':', '_')}"
    return dependency


def require_extension(context: AuthContext | None = Depends(get_auth_context)) -> AuthContext:
    if context is None or context.kind != "extension":
        raise UNAUTHENTICATED
    return context


def set_session_cookie(response: Response, token: str, max_age_seconds: int) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, max_age=max_age_seconds, path="/", httponly=True,
        samesite="strict", secure=settings.cookie_secure,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict", secure=settings.cookie_secure)


def client_ip(request: Request) -> str:
    # Proxy headers are not trusted: the app is not deployed behind a known proxy.
    return request.client.host if request.client else "unknown"
