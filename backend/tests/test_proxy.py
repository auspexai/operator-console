"""Tests for the coordinator proxy (the first operator-console backend tests).

Covers the auth gate on the M6 firehose route + an authed REST forward + the SSE
forward, all with respx-mocked coordinator upstreams.
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

COORD_URL = "http://coord.test"


# ---- auth gate (require_session before any upstream call) -------------------


def test_events_requires_session(client: TestClient) -> None:
    assert client.get("/api/v0/proxy/events").status_code == 401


def test_workers_requires_session(client: TestClient) -> None:
    assert client.get("/api/v0/proxy/workers").status_code == 401


# ---- authed REST forward (trusted-proxy attribution reaches the coordinator) -


@respx.mock
def test_authed_workers_forwards(authed_client: TestClient) -> None:
    route = respx.get(f"{COORD_URL}/api/v0/workers").mock(
        return_value=httpx.Response(200, json={"workers": [{"worker_id": "w1"}]})
    )
    r = authed_client.get("/api/v0/proxy/workers")
    assert r.status_code == 200
    assert r.json() == {"workers": [{"worker_id": "w1"}]}
    sent = route.calls.last.request
    assert sent.headers.get("X-Maintainer-Login") == "test-maintainer"
    assert sent.headers.get("Authorization") == "Bearer test-service-token"


# ---- SSE firehose forward (M6) ---------------------------------------------


@respx.mock
def test_authed_firehose_forwards_sse(authed_client: TestClient) -> None:
    frames = (
        b": connected\n\n"
        b"id: 1\nevent: experiment.submitted\n"
        b'data: {"experiment_id":"exp-x","status":"submitted"}\n\n'
    )
    route = respx.get(f"{COORD_URL}/api/v0/events").mock(
        return_value=httpx.Response(
            200, content=frames, headers={"content-type": "text/event-stream"}
        )
    )
    r = authed_client.get("/api/v0/proxy/events")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert b"experiment.submitted" in r.content
    # the proxy tailed the maintainer firehose with trusted-proxy headers
    sent = route.calls.last.request
    assert sent.headers.get("X-Maintainer-Login") == "test-maintainer"
    assert sent.headers.get("accept") == "text/event-stream"


@respx.mock
def test_firehose_upstream_error_closes_gracefully(authed_client: TestClient) -> None:
    # An upstream 4xx can't change the already-200 SSE status → comment + close.
    respx.get(f"{COORD_URL}/api/v0/events").mock(return_value=httpx.Response(403))
    r = authed_client.get("/api/v0/proxy/events")
    assert r.status_code == 200
    assert b"upstream error 403" in r.content
