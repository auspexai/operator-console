"""Coordinator API proxy routes for the operator console.

All routes require a signed-in Maintainer session. Every proxied request
carries the X-Maintainer-Login header for per-maintainer audit attribution
on the coordinator side (trusted-proxy model per §11 of
operator_console_design.md).

O-M3: workers fleet, promotion queue, experiment approval.
O-M4: audit log.
O-M5: receipts detail enhancement.
O-M6: experiment detail + work-units.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .auth import coord_headers, require_session

# Forwarded verbatim to the browser so intermediaries flush SSE frames immediately.
_SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


class ProxyError(Exception):
    pass


def build_router(config) -> APIRouter:
    router = APIRouter(prefix="/api/v0/proxy", tags=["proxy"])

    def _headers(request: Request) -> dict[str, str]:
        login = require_session(request)
        return coord_headers(login, config.coord_service_token)

    async def _proxy_get(path: str, headers: dict[str, str]) -> Any:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{config.coord_url}{path}", headers=headers)
        if r.status_code >= 400:
            raise HTTPException(
                status_code=r.status_code,
                detail=r.json()
                if r.headers.get("content-type", "").startswith("application/json")
                else r.text,
            )
        return r.json()

    async def _proxy_post(path: str, headers: dict[str, str], body: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{config.coord_url}{path}", headers=headers, json=body)
        if r.status_code >= 400:
            raise HTTPException(
                status_code=r.status_code,
                detail=r.json()
                if r.headers.get("content-type", "").startswith("application/json")
                else r.text,
            )
        return r.json()

    async def _proxy_sse(path: str, headers: dict[str, str]) -> AsyncIterator[bytes]:
        """Tail an upstream coordinator `text/event-stream` and forward its bytes
        verbatim to the browser (which can't sign coordinator requests). Generic —
        reusable for any coordinator SSE route (the researcher dashboard reuses this
        shape for its tenant-scoped stream). Long-lived: no read timeout (the
        coordinator's `: ping` keepalive holds it open). On an upstream error the
        SSE response status is already 200, so we emit a comment + close and let the
        browser's EventSource reconnect; the real auth gate is `require_session`
        (synchronous, before the stream starts)."""
        timeout = httpx.Timeout(10.0, read=None)
        req_headers = {**headers, "Accept": "text/event-stream"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("GET", f"{config.coord_url}{path}", headers=req_headers) as r:
                if r.status_code >= 400:
                    yield f": upstream error {r.status_code}\n\n".encode()
                    return
                async for chunk in r.aiter_bytes():
                    yield chunk

    # ---- workers fleet ----

    @router.get("/workers")
    async def list_workers(request: Request) -> Any:
        return await _proxy_get("/api/v0/workers", _headers(request))

    @router.post("/workers/{worker_id}/actions/quarantine")
    async def quarantine_worker(request: Request, worker_id: str) -> Any:
        body = (
            await request.json()
            if request.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        return await _proxy_post(
            f"/api/v0/workers/{worker_id}/actions/quarantine",
            _headers(request),
            {"reason": body.get("reason")} if body.get("reason") else None,
        )

    @router.post("/workers/{worker_id}/actions/unquarantine")
    async def unquarantine_worker(request: Request, worker_id: str) -> Any:
        return await _proxy_post(
            f"/api/v0/workers/{worker_id}/actions/unquarantine",
            _headers(request),
        )

    # ---- promotion-gate certifications (RFC 0001 / Ethics §6.7) ----

    @router.get("/certifications")
    async def list_certifications(request: Request) -> Any:
        return await _proxy_get("/api/v0/certifications", _headers(request))

    @router.get("/certifications/staleness")
    async def certification_staleness(request: Request) -> Any:
        # Maintainer-only on the coordinator: per active cert, whether a newer
        # build was submitted (re-certify signal). Defined before the {pkg} route.
        return await _proxy_get("/api/v0/certifications/staleness", _headers(request))

    @router.post("/certifications/{package_sha256}/revoke")
    async def revoke_certification(request: Request, package_sha256: str) -> Any:
        body = (
            await request.json()
            if request.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        return await _proxy_post(
            f"/api/v0/certifications/{package_sha256}/revoke",
            _headers(request),
            {"reason": body.get("reason", "")},
        )

    # ---- promotion queue ----

    @router.get("/accounts/{account_id}/receipt-stats")
    async def receipt_stats(request: Request, account_id: str) -> Any:
        return await _proxy_get(
            f"/api/v0/accounts/{account_id}/receipt-stats",
            _headers(request),
        )

    # ---- research standing (R0-R3) ----
    # The two-axis trust dossier: research standing gates BYOT/high-risk
    # experiments (per the on-ramp arc), distinct from the compute trust tier
    # above. The GET is the reviewer's evidence; the POST is a one-step,
    # mandatory-reason promotion (R1→R2 / R2→R3), gate-warned like tier changes.

    @router.get("/accounts/{account_id}/research-standing")
    async def research_standing(request: Request, account_id: str) -> Any:
        return await _proxy_get(
            f"/api/v0/accounts/{account_id}/research-standing",
            _headers(request),
        )

    @router.post("/accounts/{account_id}/actions/promote-research-standing")
    async def promote_research_standing(request: Request, account_id: str) -> Any:
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/accounts/{account_id}/actions/promote-research-standing",
            _headers(request),
            body,
        )

    @router.post("/accounts/{account_id}/actions/promote")
    async def promote_account(request: Request, account_id: str) -> Any:
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/accounts/{account_id}/actions/promote",
            _headers(request),
            body,
        )

    @router.post("/accounts/{account_id}/actions/demote")
    async def demote_account(request: Request, account_id: str) -> Any:
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/accounts/{account_id}/actions/demote",
            _headers(request),
            body,
        )

    @router.post("/accounts/{account_id}/actions/suspend")
    async def suspend_account(request: Request, account_id: str) -> Any:
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/accounts/{account_id}/actions/suspend",
            _headers(request),
            body,
        )

    @router.post("/accounts/{account_id}/actions/unsuspend")
    async def unsuspend_account(request: Request, account_id: str) -> Any:
        return await _proxy_post(
            f"/api/v0/accounts/{account_id}/actions/unsuspend",
            _headers(request),
        )

    # ---- accounts + promotion queue ----

    @router.get("/accounts")
    async def list_accounts(request: Request) -> Any:
        return await _proxy_get("/api/v0/accounts", _headers(request))

    # ---- experiments ----

    @router.get("/experiments")
    async def list_experiments(request: Request) -> Any:
        return await _proxy_get("/api/v0/experiments", _headers(request))

    @router.get("/experiments/{experiment_id}")
    async def get_experiment(request: Request, experiment_id: str) -> Any:
        return await _proxy_get(f"/api/v0/experiments/{experiment_id}", _headers(request))

    # §9 #48 inc-4: the auto-approval gate (coordinator-authoritative). The
    # console reads/writes it; `decide()` reads it at decision time.
    @router.get("/assessment-policy")
    async def get_assessment_policy(request: Request) -> Any:
        return await _proxy_get("/api/v0/assessment-policy", _headers(request))

    @router.post("/assessment-policy")
    async def set_assessment_policy(request: Request) -> Any:
        body = await request.json()
        return await _proxy_post("/api/v0/assessment-policy", _headers(request), body)

    @router.get("/experiments/{experiment_id}/work-units")
    async def list_work_units(request: Request, experiment_id: str) -> Any:
        return await _proxy_get(
            f"/api/v0/experiments/{experiment_id}/work-units", _headers(request)
        )

    @router.post("/experiments/{experiment_id}/actions/approve")
    async def approve_experiment(request: Request, experiment_id: str) -> Any:
        body = await request.json()
        params = []
        if body.get("integrity_policy"):
            params.append(f"integrity_policy={body['integrity_policy']}")
        # C14: the (replication_target, replication_floor) override takes
        # precedence over the legacy integrity_policy on the coordinator. Forward
        # only when present so an unset key falls back to the experiment default.
        for repl_key in ["replication_target", "replication_floor"]:
            if body.get(repl_key) is not None:
                params.append(f"{repl_key}={body[repl_key]}")
        for key in [
            "max_unit_duration_seconds",
            "max_units",
            "max_concurrent_assignments",
            "max_payload_bytes",
        ]:
            if body.get(key) is not None:
                params.append(f"{key}={body[key]}")
        query = f"?{'&'.join(params)}" if params else ""
        return await _proxy_post(
            f"/api/v0/experiments/{experiment_id}/actions/approve{query}",
            _headers(request),
        )

    @router.post("/experiments/{experiment_id}/actions/pause")
    async def pause_experiment(request: Request, experiment_id: str) -> Any:
        return await _proxy_post(
            f"/api/v0/experiments/{experiment_id}/actions/pause",
            _headers(request),
        )

    @router.post("/experiments/{experiment_id}/actions/resume")
    async def resume_experiment(request: Request, experiment_id: str) -> Any:
        return await _proxy_post(
            f"/api/v0/experiments/{experiment_id}/actions/resume",
            _headers(request),
        )

    @router.post("/experiments/{experiment_id}/actions/abort")
    async def abort_experiment(request: Request, experiment_id: str) -> Any:
        return await _proxy_post(
            f"/api/v0/experiments/{experiment_id}/actions/abort",
            _headers(request),
        )

    # ---- retention hold / release (O-M8) ----
    # The coordinator takes `reason` as a query param (mandatory on hold,
    # mirrors account-suspension); forward the body's reason URL-encoded.

    @router.post("/experiments/{experiment_id}/actions/retention-hold")
    async def retention_hold(request: Request, experiment_id: str) -> Any:
        body = await request.json()
        reason = (body.get("reason") or "").strip()
        if not reason:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": {
                        "code": "reason_required",
                        "message": "a reason is required to place a retention hold",
                    }
                },
            )
        return await _proxy_post(
            f"/api/v0/experiments/{experiment_id}/actions/retention-hold"
            f"?reason={quote(reason, safe='')}",
            _headers(request),
        )

    @router.post("/experiments/{experiment_id}/actions/release-hold")
    async def release_hold(request: Request, experiment_id: str) -> Any:
        return await _proxy_post(
            f"/api/v0/experiments/{experiment_id}/actions/release-hold",
            _headers(request),
        )

    # ---- tenants + linkage (ops worker↔tenant association) ----

    @router.get("/tenants")
    async def list_tenants(request: Request) -> Any:
        return await _proxy_get("/api/v0/tenants", _headers(request))

    @router.get("/tenants/{tenant_id}/linkage")
    async def tenant_linkage(request: Request, tenant_id: str) -> Any:
        """The tenant↔account↔workers all-linkages view (operator-only on the
        coordinator). operator_console_design.md §11."""
        return await _proxy_get(f"/api/v0/tenants/{tenant_id}/linkage", _headers(request))

    @router.post("/tenants/{tenant_id}/actions/link")
    async def link_tenant(request: Request, tenant_id: str) -> Any:
        """Maintainer: link/unlink a tenant to an account (post-registration)."""
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/tenants/{tenant_id}/actions/link", _headers(request), body
        )

    # ---- audit log ----

    @router.get("/audit")
    async def proxy_audit(request: Request) -> Any:
        """Proxy audit log from coordinator."""
        qs = str(request.query_params)
        path = "/api/v0/audit" + (f"?{qs}" if qs else "")
        return await _proxy_get(path, _headers(request))

    # ---- receipts ----

    @router.get("/receipts/{receipt_id}")
    async def get_receipt(request: Request, receipt_id: str) -> Any:
        return await _proxy_get(f"/api/v0/receipts/{receipt_id}", _headers(request))

    @router.post("/receipts/verify")
    async def verify_receipt(request: Request) -> Any:
        body = await request.json()
        return await _proxy_post("/api/v0/receipts/verify", _headers(request), body)

    # ---- model catalog (the network's served-model aggregate; the model-request
    # demand-board was retired — researcher demand now flows via GitHub Discussions) ----

    @router.get("/models/catalog")
    async def models_catalog(request: Request) -> Any:
        return await _proxy_get("/api/v0/models/catalog", _headers(request))

    # ---- tenant applications (onboarding review queue) ----
    # Approve is the one-shot onboarding action on the coordinator: tenant
    # created + applicant key bound + account linked, all in one call.

    @router.get("/tenant-applications")
    async def list_tenant_applications(request: Request) -> Any:
        status_filter = request.query_params.get("status_filter")
        path = "/api/v0/tenant-applications"
        if status_filter:
            path += f"?status_filter={quote(status_filter, safe='')}"
        return await _proxy_get(path, _headers(request))

    @router.post("/tenant-applications/{application_id}/actions/approve")
    async def approve_tenant_application(request: Request, application_id: str) -> Any:
        # Optional body: {tenant_id_override} when the maintainer edits the
        # requested tenant id in the confirm modal; otherwise no body.
        body = (
            await request.json()
            if request.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        return await _proxy_post(
            f"/api/v0/tenant-applications/{application_id}/actions/approve",
            _headers(request),
            {"tenant_id_override": body["tenant_id_override"]}
            if body.get("tenant_id_override")
            else None,
        )

    @router.post("/tenant-applications/{application_id}/actions/decline")
    async def decline_tenant_application(request: Request, application_id: str) -> Any:
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/tenant-applications/{application_id}/actions/decline",
            _headers(request),
            body,
        )

    # ---- release registry (§9 #46; the software-request intake queue was retired) ----

    @router.get("/releases")
    async def list_releases(request: Request) -> Any:
        channel = request.query_params.get("channel")
        params = []
        if channel:
            params.append(f"channel={quote(channel, safe='')}")
        # The console is the maintainer surface: webhook-created DRAFTS are
        # part of its review queue.
        if request.query_params.get("include_drafts"):
            params.append("include_drafts=true")
        path = "/api/v0/releases" + (f"?{'&'.join(params)}" if params else "")
        return await _proxy_get(path, _headers(request))

    @router.post("/releases")
    async def record_release(request: Request) -> Any:
        body = await request.json()
        return await _proxy_post("/api/v0/releases", _headers(request), body)

    @router.post("/releases/{version}/actions/announce")
    async def announce_release(request: Request, version: str) -> Any:
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/releases/{quote(version, safe='')}/actions/announce",
            _headers(request),
            body,
        )

    # ---- scheduler view (M4) ----

    @router.get("/scheduler/state")
    async def scheduler_state(request: Request) -> Any:
        return await _proxy_get("/api/v0/scheduler/state", _headers(request))

    @router.post("/workers/{worker_id}/actions/pause")
    async def pause_worker(request: Request, worker_id: str) -> Any:
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/workers/{worker_id}/actions/pause", _headers(request), body
        )

    @router.post("/workers/{worker_id}/actions/unpause")
    async def unpause_worker(request: Request, worker_id: str) -> Any:
        return await _proxy_post(f"/api/v0/workers/{worker_id}/actions/unpause", _headers(request))

    @router.post("/experiments/{experiment_id}/actions/set-integrity-policy")
    async def set_integrity_policy(request: Request, experiment_id: str) -> Any:
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/experiments/{experiment_id}/actions/set-integrity-policy",
            _headers(request),
            body,
        )

    # C14: the replication-override successor to set-integrity-policy. JSON body
    # {replication_target?, replication_floor?, reason}; the coordinator
    # tier-floors both server-side and applies to FUTURE units only.
    @router.post("/experiments/{experiment_id}/actions/set-replication")
    async def set_replication(request: Request, experiment_id: str) -> Any:
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/experiments/{experiment_id}/actions/set-replication",
            _headers(request),
            body,
        )

    @router.post("/experiments/{experiment_id}/actions/trigger-prestage")
    async def trigger_prestage(request: Request, experiment_id: str) -> Any:
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/experiments/{experiment_id}/actions/trigger-prestage",
            _headers(request),
            body,
        )

    @router.post("/experiments/{experiment_id}/units/{unit_id}/actions/pin")
    async def pin_unit(request: Request, experiment_id: str, unit_id: str) -> Any:
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/experiments/{experiment_id}/units/{unit_id}/actions/pin",
            _headers(request),
            body,
        )

    # ---- live event stream (M6) ----

    @router.get("/events")
    async def proxy_firehose(request: Request) -> StreamingResponse:
        """Maintainer firehose, proxied to the browser: every experiment's events
        (experiment.submitted/status, unit.progress, receipt.issued) + fleet events
        (worker.status, network.status). The console REST-snapshots, then tails this
        to update live (the approval queue surfaces a pending experiment without a
        refresh). `_headers` runs require_session first → 401/403 before streaming."""
        headers = _headers(request)
        return StreamingResponse(
            _proxy_sse("/api/v0/events", headers),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    return router
