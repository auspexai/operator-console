"""FastAPI app factory for the operator console.

O-M1: serves the SvelteKit-built static frontend + a small JSON API.
No auth yet (O-M2). The /api/v0/health endpoint also probes the coord
so the placeholder page can show "backend → coord" connectivity.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .auth import build_router as build_auth_router
from .config import OperatorConsoleConfig


def create_app(config: OperatorConsoleConfig | None = None) -> FastAPI:
    config = config or OperatorConsoleConfig.from_env()
    app = FastAPI(
        title="AuspexAI Operator Console",
        version=__version__,
        description="Maintainer's privileged dashboard. O-M1 placeholder; auth lands in O-M2.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = config

    # Session-cookie middleware (signed via itsdangerous). Cookie is HttpOnly,
    # SameSite=lax, Secure-when-HTTPS. Lifetime: 30 days; sliding so any
    # interaction refreshes the expiry.
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.session_secret,
        session_cookie="auspexai_op_session",
        max_age=30 * 24 * 60 * 60,  # 30 days
        same_site="lax",
        https_only=True,  # set False in dev if testing over plain HTTP
    )

    # Auth routes (/api/v0/auth/{login,poll,whoami,logout}).
    app.include_router(build_auth_router())

    @app.get("/api/v0/health")
    async def health() -> JSONResponse:
        """Health + coord-connectivity probe. Public; read-only."""
        now = datetime.now(UTC).isoformat()
        coord_ok: bool | None = None
        coord_detail: str | None = None
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{config.coord_url}/api/v0/health/public")
                coord_ok = r.status_code == 200
                coord_detail = (
                    r.json().get("status") if coord_ok else f"HTTP {r.status_code}"
                )
        except httpx.HTTPError as e:
            coord_ok = False
            coord_detail = f"error: {e!s}"

        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "server_time": now,
                "phase": "O-M1 (auth pending; no operator actions exposed)",
                "coord": {
                    "url": config.coord_url,
                    "reachable": coord_ok,
                    "detail": coord_detail,
                },
            }
        )

    # Mount the built SvelteKit static bundle under /. The bundle's
    # routes live as HTML files (e.g., /index.html, /workers/index.html);
    # adapter-static produces them at build time. FastAPI's StaticFiles
    # with html=True serves index.html for directory requests.
    if config.static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(config.static_dir), html=True), name="frontend")
    else:
        # Frontend not built yet — surface a clear placeholder.
        @app.get("/")
        async def placeholder() -> FileResponse | JSONResponse:
            return JSONResponse(
                {
                    "status": "frontend bundle not present",
                    "expected_at": str(config.static_dir),
                    "hint": "Run pnpm install + pnpm build in the frontend/ dir and copy the built bundle.",
                }
            )

    return app
