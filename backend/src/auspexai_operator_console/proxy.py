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

from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request

from .auth import coord_headers, require_session


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

    # ---- promotion queue ----

    @router.get("/accounts/{account_id}/receipt-stats")
    async def receipt_stats(request: Request, account_id: str) -> Any:
        return await _proxy_get(
            f"/api/v0/accounts/{account_id}/receipt-stats",
            _headers(request),
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

    # ---- model-requests demand-board (M2) ----

    @router.get("/model-requests")
    async def list_model_requests(request: Request) -> Any:
        status = request.query_params.get("status")
        path = "/api/v0/model-requests"
        if status:
            path += f"?status={quote(status, safe='')}"
        return await _proxy_get(path, _headers(request))

    @router.get("/models/catalog")
    async def models_catalog(request: Request) -> Any:
        return await _proxy_get("/api/v0/models/catalog", _headers(request))

    @router.post("/model-requests/{request_id}/actions/fulfil")
    async def fulfil_model_request(request: Request, request_id: str) -> Any:
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/model-requests/{request_id}/actions/fulfil",
            _headers(request),
            body,
        )

    @router.post("/model-requests/{request_id}/actions/decline")
    async def decline_model_request(request: Request, request_id: str) -> Any:
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/model-requests/{request_id}/actions/decline",
            _headers(request),
            body,
        )

    return router
