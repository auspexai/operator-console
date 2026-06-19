"""Tests for the coordinator API-docs proxy (Swagger/ReDoc at the console origin).

The coordinator's OpenAPI schema is maintainer-only; the console proxies it with
the service token so a session-authed browser can read it. Covers the auth gate +
the authed forward + the shell pointing at the same-origin proxied schema.
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

COORD_URL = "http://coord.test"


# ---- auth gate (require_session before any upstream call) -------------------


def test_openapi_requires_session(client: TestClient) -> None:
    assert client.get("/maintainer/openapi.json").status_code == 401


def test_docs_requires_session(client: TestClient) -> None:
    assert client.get("/maintainer/docs").status_code == 401


def test_redoc_requires_session(client: TestClient) -> None:
    assert client.get("/maintainer/redoc").status_code == 401


# ---- authed: proxy the maintainer-only coordinator schema -------------------


@respx.mock
def test_openapi_proxies_coordinator_schema(authed_client: TestClient) -> None:
    route = respx.get(f"{COORD_URL}/openapi.json").mock(
        return_value=httpx.Response(
            200, json={"openapi": "3.1.0", "paths": {"/api/v0/health/public": {}}}
        )
    )
    r = authed_client.get("/maintainer/openapi.json")
    assert r.status_code == 200
    assert "/api/v0/health/public" in r.json()["paths"]
    # The proxy attached the maintainer service token to the upstream call.
    sent = route.calls.last.request
    assert sent.headers.get("authorization") == "Bearer test-service-token"
    assert sent.headers.get("x-maintainer-login") == "test-maintainer"


@respx.mock
def test_openapi_surfaces_coordinator_error(authed_client: TestClient) -> None:
    respx.get(f"{COORD_URL}/openapi.json").mock(return_value=httpx.Response(403))
    assert authed_client.get("/maintainer/openapi.json").status_code == 403


def test_docs_serves_swagger_shell_pointing_at_proxy(authed_client: TestClient) -> None:
    r = authed_client.get("/maintainer/docs")
    assert r.status_code == 200
    assert "swagger" in r.text.lower()
    # The shell fetches the schema from the console's own (session-authed) origin.
    assert "/maintainer/openapi.json" in r.text


def test_redoc_serves_redoc_shell(authed_client: TestClient) -> None:
    r = authed_client.get("/maintainer/redoc")
    assert r.status_code == 200
    assert "redoc" in r.text.lower()
    assert "/maintainer/openapi.json" in r.text
