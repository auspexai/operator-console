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


def test_assessment_policy_requires_session(client: TestClient) -> None:
    assert client.get("/api/v0/proxy/assessment-policy").status_code == 401
    assert client.post("/api/v0/proxy/assessment-policy", json={}).status_code == 401


# ---- §9 #48 inc-4 auto-approval gate (coordinator-authoritative) ------------


@respx.mock
def test_assessment_policy_get_forwards(authed_client: TestClient) -> None:
    respx.get(f"{COORD_URL}/api/v0/assessment-policy").mock(
        return_value=httpx.Response(200, json={"enabled": False, "min_tier": 2})
    )
    r = authed_client.get("/api/v0/proxy/assessment-policy")
    assert r.status_code == 200 and r.json()["enabled"] is False


@respx.mock
def test_assessment_policy_post_forwards_body(authed_client: TestClient) -> None:
    route = respx.post(f"{COORD_URL}/api/v0/assessment-policy").mock(
        return_value=httpx.Response(200, json={"enabled": True, "min_tier": 3})
    )
    r = authed_client.post(
        "/api/v0/proxy/assessment-policy",
        json={"enabled": True, "min_tier": 3, "reason": "turn autonomy on"},
    )
    assert r.status_code == 200 and r.json()["min_tier"] == 3
    sent = route.calls.last.request
    assert b"turn autonomy on" in sent.content
    assert sent.headers.get("Authorization") == "Bearer test-service-token"


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


# ---- tenant applications (onboarding review queue) ---------------------------


def test_tenant_applications_require_session(client: TestClient) -> None:
    assert client.get("/api/v0/proxy/tenant-applications").status_code == 401
    assert (
        client.post("/api/v0/proxy/tenant-applications/app-1/actions/approve", json={}).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v0/proxy/tenant-applications/app-1/actions/decline", json={"reason": "x"}
        ).status_code
        == 401
    )


@respx.mock
def test_tenant_applications_list_forwards_status_filter(authed_client: TestClient) -> None:
    route = respx.get(f"{COORD_URL}/api/v0/tenant-applications?status_filter=pending").mock(
        return_value=httpx.Response(200, json={"applications": []})
    )
    r = authed_client.get("/api/v0/proxy/tenant-applications?status_filter=pending")
    assert r.status_code == 200
    assert r.json() == {"applications": []}
    assert route.calls.last.request.headers.get("X-Maintainer-Login") == "test-maintainer"


@respx.mock
def test_tenant_application_approve_forwards_override(authed_client: TestClient) -> None:
    route = respx.post(f"{COORD_URL}/api/v0/tenant-applications/app-1/actions/approve").mock(
        return_value=httpx.Response(
            200,
            json={"application_id": "app-1", "status": "approved", "created_tenant_id": "t-x"},
        )
    )
    r = authed_client.post(
        "/api/v0/proxy/tenant-applications/app-1/actions/approve",
        json={"tenant_id_override": "t-x"},
    )
    assert r.status_code == 200
    assert r.json()["created_tenant_id"] == "t-x"
    import json as _json

    assert _json.loads(route.calls.last.request.content) == {"tenant_id_override": "t-x"}


@respx.mock
def test_tenant_application_approve_without_override_sends_no_body(
    authed_client: TestClient,
) -> None:
    route = respx.post(f"{COORD_URL}/api/v0/tenant-applications/app-1/actions/approve").mock(
        return_value=httpx.Response(200, json={"application_id": "app-1", "status": "approved"})
    )
    # The console sends {} when the requested tenant id is kept as-is; the
    # proxy forwards no override (the coordinator uses requested_tenant_id).
    r = authed_client.post("/api/v0/proxy/tenant-applications/app-1/actions/approve", json={})
    assert r.status_code == 200
    assert route.calls.last.request.content in (b"", b"null")


@respx.mock
def test_tenant_application_decline_forwards_reason(authed_client: TestClient) -> None:
    route = respx.post(f"{COORD_URL}/api/v0/tenant-applications/app-1/actions/decline").mock(
        return_value=httpx.Response(200, json={"application_id": "app-1", "status": "declined"})
    )
    r = authed_client.post(
        "/api/v0/proxy/tenant-applications/app-1/actions/decline",
        json={"reason": "not a research fit"},
    )
    assert r.status_code == 200
    import json as _json

    assert _json.loads(route.calls.last.request.content) == {"reason": "not a research fit"}


@respx.mock
def test_tenant_application_decline_upstream_422_passes_through(
    authed_client: TestClient,
) -> None:
    # The coordinator enforces the mandatory reason; its 4xx passes through.
    respx.post(f"{COORD_URL}/api/v0/tenant-applications/app-1/actions/decline").mock(
        return_value=httpx.Response(
            422, json={"error": {"code": "reason_required", "message": "reason is required"}}
        )
    )
    r = authed_client.post(
        "/api/v0/proxy/tenant-applications/app-1/actions/decline", json={"reason": ""}
    )
    assert r.status_code == 422


# ---- release registry (§9 #46; the software-request intake queue was retired) -------


def test_releases_require_session(client: TestClient) -> None:
    assert client.post("/api/v0/proxy/releases", json={}).status_code == 401


@respx.mock
def test_record_release_forwards_body(authed_client: TestClient) -> None:
    route = respx.post(f"{COORD_URL}/api/v0/releases").mock(
        return_value=httpx.Response(201, json={"version": "0.2.0", "channel": "worker"})
    )
    body = {
        "version": "0.2.0",
        "headline": "flavors",
        "fulfils_request_ids": ["swr-1"],
    }
    r = authed_client.post("/api/v0/proxy/releases", json=body)
    assert r.status_code in (200, 201)
    import json as _json

    sent = _json.loads(route.calls.last.request.content)
    assert sent["fulfils_request_ids"] == ["swr-1"]


@respx.mock
def test_releases_list_forwards(authed_client: TestClient) -> None:
    respx.get(f"{COORD_URL}/api/v0/releases").mock(
        return_value=httpx.Response(200, json={"releases": []})
    )
    r = authed_client.get("/api/v0/proxy/releases")
    assert r.status_code == 200
    assert r.json() == {"releases": []}
