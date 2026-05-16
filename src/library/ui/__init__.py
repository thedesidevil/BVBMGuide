"""FastAPI application factory for the Library QC UI."""

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from . import google_auth as ga
from .api import tree, city, country, review, sweep, audit, ingest
from .storage import LocalStorageBackend, StorageBackend


def create_app(
    db_path: Optional[Path] = None,
    library_path: Path = Path("aig-library"),
    storage_backend: Optional[StorageBackend] = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        db_path: Path to the library database directory (local dev).
        library_path: Path to the AIG library directory.
        storage_backend: Pre-configured storage backend (Lambda). Overrides db_path.
    """
    app = FastAPI(
        title="Library QC UI",
        description="Quality control interface for the AIG library database",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if ga.auth_enabled():
        app.add_middleware(ga.RequireGoogleAuthMiddleware)
        app.add_middleware(
            SessionMiddleware,
            secret_key=ga.session_secret(),
            session_cookie="session",
            same_site="lax",
            https_only=os.getenv("SESSION_HTTPS_ONLY", "").lower() in ("1", "true", "yes"),
        )

    if storage_backend is None:
        if db_path is None:
            db_path = Path("library_db")
        storage_backend = LocalStorageBackend(db_path)

    app.state.storage_backend = storage_backend
    app.state.library_path = library_path

    @app.get("/login")
    async def login(request: Request):
        if not ga.auth_enabled():
            return RedirectResponse(url="/", status_code=303)
        redirect_uri = str(request.url_for("auth_callback"))
        next_path = request.query_params.get("next") or "/"
        if not next_path.startswith("/"):
            next_path = "/"
        request.session["oauth_next"] = next_path
        prompt = request.query_params.get("prompt")
        extra = {"prompt": prompt} if prompt else {}
        return await ga.oauth.google.authorize_redirect(request, redirect_uri, **extra)

    @app.get("/auth/callback", name="auth_callback")
    async def auth_callback(request: Request):
        if not ga.auth_enabled():
            return RedirectResponse(url="/", status_code=303)
        try:
            token = await ga.oauth.google.authorize_access_token(request)
        except Exception as e:
            return JSONResponse(
                {"error": "oauth_failed", "detail": str(e)},
                status_code=400,
            )
        userinfo: dict = {}
        if isinstance(token, dict):
            userinfo = token.get("userinfo") or {}
            if not userinfo.get("email") and token.get("access_token"):
                import httpx

                async with httpx.AsyncClient() as client:
                    r = await client.get(
                        "https://openidconnect.googleapis.com/v1/userinfo",
                        headers={"Authorization": f"Bearer {token['access_token']}"},
                    )
                    if r.status_code == 200:
                        userinfo = r.json()
        email = (userinfo or {}).get("email", "") or ""
        name = (userinfo or {}).get("name", "") or ""
        if not ga.allowed_user(email):
            request.session.clear()
            return HTMLResponse(
                "<h1>Access denied</h1><p>This Google account is not authorized to use this app.</p>"
                '<p><a href="/logout">Sign out</a></p>',
                status_code=403,
            )
        request.session["user"] = {"email": email, "name": name}
        next_path = request.session.pop("oauth_next", "/")
        if not isinstance(next_path, str) or not next_path.startswith("/"):
            next_path = "/"
        return RedirectResponse(url=next_path, status_code=303)

    @app.get("/logout")
    async def logout(request: Request):
        request.session.clear()
        return HTMLResponse(
            '<html><body style="font-family:system-ui;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#f8fafc">'
            '<div style="text-align:center">'
            "<h2>Signed out</h2>"
            '<p style="color:#64748b">You have been logged out.</p>'
            '<a href="/login?prompt=select_account" style="color:#2563eb">Sign in again</a>'
            "</div></body></html>",
            status_code=200,
        )

    @app.get("/api/me")
    async def me(request: Request):
        user = ga.user_session(request)
        if user:
            return user
        return JSONResponse({"user": None}, status_code=401)

    app.include_router(tree.router, prefix="/api")
    app.include_router(city.router, prefix="/api")
    app.include_router(country.router, prefix="/api")
    app.include_router(review.router, prefix="/api")
    app.include_router(sweep.router, prefix="/api")
    app.include_router(audit.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")

    from fastapi.staticfiles import StaticFiles

    dist_path = Path(__file__).parent.parent.parent.parent / "ui-frontend" / "dist"
    if dist_path.exists():
        app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="frontend")

    return app
