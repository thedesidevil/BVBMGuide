"""
Optional Google OAuth2 (OpenID Connect) for the FastAPI app.

Enable with GOOGLE_OAUTH_ENABLED=1 and set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
and SESSION_SECRET in the environment.

When disabled, all routes behave as before with no login.
"""
from __future__ import annotations

import os
from urllib.parse import quote

from authlib.integrations.starlette_client import OAuth
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

oauth = OAuth()


def auth_enabled() -> bool:
    return os.getenv("GOOGLE_OAUTH_ENABLED", "").lower() in ("1", "true", "yes")


def session_secret() -> str:
    secret = os.getenv("SESSION_SECRET", "").strip()
    if auth_enabled():
        if not secret or secret == "change-me":
            raise RuntimeError(
                "Set SESSION_SECRET to a long random string when GOOGLE_OAUTH_ENABLED=1"
            )
        return secret
    return secret or "dev-only-not-for-oauth"


def _register_google() -> None:
    if not auth_enabled():
        return
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "GOOGLE_OAUTH_ENABLED=1 requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET"
        )
    oauth.register(
        name="google",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def init_oauth() -> None:
    _register_google()


def allowed_user(email: str) -> bool:
    if not email:
        return False
    email_l = email.strip().lower()
    raw_emails = os.getenv("GOOGLE_ALLOWED_EMAILS", "").strip()
    if raw_emails:
        allowed = {e.strip().lower() for e in raw_emails.split(",") if e.strip()}
        return email_l in allowed
    domain = os.getenv("GOOGLE_ALLOWED_DOMAIN", "").strip().lstrip("@")
    if domain:
        domain = domain.lower()
        return email_l.endswith("@" + domain)
    return True


def user_session(request: Request) -> dict | None:
    if "session" not in request.scope:
        return None
    u = request.session.get("user")
    return u if isinstance(u, dict) else None


class RequireGoogleAuthMiddleware(BaseHTTPMiddleware):
    PUBLIC_PREFIXES = ("/static",)
    PUBLIC_PATHS = frozenset({"/login", "/auth/callback", "/logout", "/favicon.ico"})

    async def dispatch(self, request: Request, call_next):
        if not auth_enabled():
            return await call_next(request)

        path = request.url.path
        if path in self.PUBLIC_PATHS:
            return await call_next(request)
        for prefix in self.PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        if user_session(request):
            return await call_next(request)

        from starlette.responses import RedirectResponse

        next_url = request.url.path
        if request.url.query:
            next_url += "?" + request.url.query
        login_url = "/login?next=" + quote(next_url, safe="")
        return RedirectResponse(url=login_url, status_code=303)


init_oauth()
