"""Coordinator API-docs proxy for the operator console.

The coordinator's OpenAPI schema (`/openapi.json`) and its Swagger/ReDoc UIs are
maintainer-only (gated 2026-06-19, defense-in-depth). A browser holds no
maintainer bearer token, so it can't load them directly. This serves them at the
console's OWN authed origin: the Swagger/ReDoc shells live here, and their
same-origin fetch of `/maintainer/openapi.json` rides the console session cookie
(checked by `require_session`), while the proxy adds the coordinator service
token. So reading the schema works in-browser.

("Try it out" still won't execute — those requests target the coordinator's paths
at the console origin, which only proxies `/api/v0/proxy/*` — so this is a
read-only API reference. Linked from the Nav "API" group.)
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from .auth import coord_headers, require_session

# Same-origin path the Swagger/ReDoc shells fetch — the session cookie rides it.
_OPENAPI_PATH = "/maintainer/openapi.json"


def build_router(config) -> APIRouter:
    router = APIRouter(tags=["apidocs"])

    @router.get("/maintainer/openapi.json", include_in_schema=False)
    async def coord_openapi(request: Request) -> JSONResponse:
        login = require_session(request)
        headers = coord_headers(login, config.coord_service_token)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{config.coord_url}/openapi.json", headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="coordinator unreachable") from exc
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail="coordinator openapi unavailable")
        return JSONResponse(r.json())

    @router.get("/maintainer/docs", include_in_schema=False)
    async def coord_swagger(request: Request) -> HTMLResponse:
        require_session(request)
        return get_swagger_ui_html(openapi_url=_OPENAPI_PATH, title="Coordinator API — Swagger")

    @router.get("/maintainer/redoc", include_in_schema=False)
    async def coord_redoc(request: Request) -> HTMLResponse:
        require_session(request)
        return get_redoc_html(openapi_url=_OPENAPI_PATH, title="Coordinator API — ReDoc")

    return router
